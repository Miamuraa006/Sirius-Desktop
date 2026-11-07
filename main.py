"""Sirius Foundation entry point; source and frozen EXE use exactly the same core."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
from pathlib import Path
import sys


def _write_report(path, report):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf8')


def _configure_logging(data_dir):
    handler=RotatingFileHandler(Path(data_dir)/'diagnostics.log',maxBytes=512*1024,backupCount=2,encoding='utf8')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s',handlers=[handler],force=True)
    # Commands, document/clipboard payloads and PCM must never be logged.
    logging.getLogger('comtypes').setLevel(logging.ERROR)


def parser():
    cli=argparse.ArgumentParser(description='SIRIUS v0.3 Foundation — автономный помощник Windows')
    cli.add_argument('--data-dir',type=Path,help='Отдельный каталог config/SQLite/диагностики; по умолчанию LOCALAPPDATA/Sirius')
    cli.add_argument('--no-voice',action='store_true',help='Не открывать микрофон в этом запуске')
    cli.add_argument('--text',action='append',help='Выполнить текстовую команду без GUI; флаг можно повторять')
    cli.add_argument('--report',type=Path,help='Записать реальный результат CLI в JSON')
    cli.add_argument('--diagnose',action='store_true',help='Проверить ресурсы и устройства без записи звука')
    cli.add_argument('--speech-check', action='store_true', help='Запись микрофона по кнопке и STT без выполнения команд')
    cli.add_argument('--speech-wav', type=Path, help='Прогнать WAV через Vosk без выполнения команд')
    cli.add_argument('--voice-probe',type=Path,help='Проверка Vosk на SAPI-аудио в файле, без микрофона и динамиков; каталог отчёта')
    cli.add_argument('--smoke-output',type=Path,help='Запустить настоящий GUI, CPU-команду, снимки и завершиться; каталог отчёта')
    cli.add_argument('--face-check-output',type=Path,help='Проверить чёрное стекло, пробуждение и реальный таймер 60 секунд; без микрофона')
    cli.add_argument('--help-check-output',type=Path,help='Проверить подсказку и справку в настоящем чате; без микрофона')
    return cli


def main(argv=None):
    args=parser().parse_args(argv)
    if args.face_check_output:
        args.smoke_output = args.face_check_output
    if args.help_check_output:
        args.smoke_output = args.help_check_output
    from core.config import load_config
    try:
        config=load_config(args.data_dir)
    except (ValueError,OSError) as exc:
        message=str(exc) if isinstance(exc,ValueError) else 'Каталог пользовательских настроек недоступен.'
        if sys.stderr is not None:
            print(message,file=sys.stderr)
        if args.report:
            _write_report(args.report,{'passed':False,'error':message})
        if not (args.text or args.diagnose or args.smoke_output or args.voice_probe):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'Sirius: настройки',0x10)
        return 2
    data_dir=Path(config['_data_dir'])
    config['_face_check'] = args.face_check_output is not None
    config['_help_check'] = args.help_check_output is not None
    _configure_logging(data_dir)
    try:
        if args.speech_check:
            from voice.diagnostic import run_diagnostic
            return run_diagnostic(config)
        if args.speech_wav:
            from voice.probe import diagnostic_vosk
            from voice.probe import analyze_speech_file
            report = analyze_speech_file(args.speech_wav, diagnostic_vosk(config))
            _write_report(args.report or args.speech_wav.with_suffix('.stt.json'), report)
            return 0
        if args.voice_probe:
            from voice.probe import run_probe
            report=run_probe(config,args.voice_probe)
            if args.report:_write_report(args.report,report)
            return 0 if report.get('passed') else 1
        if args.text or args.diagnose:
            from core.engine import Engine
            from core.models import Command
            engine=Engine(config,data_dir)
            report={'timestamp':datetime.now(timezone.utc).isoformat(),'frozen':bool(getattr(sys,'frozen',False)),
                    'resource_root':config['_resource_root'],'data_dir':str(data_dir),'results':[]}
            try:
                if args.diagnose:
                    import sounddevice
                    from core.intent_router import SKILL_IDS
                    root=Path(config['_resource_root'])
                    report['skills']=list(engine.registry)
                    report['resources']={str(p): (root/p).is_file() for p in ['models/ru_vosk/am/final.mdl','models/ru_vosk/conf/model.conf','ui/qml/MiniWindow.qml','ui/qml/ChatWindow.qml']}
                    try:
                        report['audio_input_devices']=[{'index':i,'name':d['name'],'channels':d['max_input_channels'],'default_samplerate':d['default_samplerate']} for i,d in enumerate(sounddevice.query_devices()) if d['max_input_channels']>0]
                    except Exception as exc:
                        report['audio_error']=type(exc).__name__
                    report['passed']=tuple(engine.registry)==SKILL_IDS and all(report['resources'].values())
                for text in args.text or []:
                    result=engine.execute(Command(text,'text','cli'))
                    report['results'].append(result.to_dict())
                if args.text:
                    report['passed']=report.get('passed',True) and all(r['status']=='success' and r['verified'] for r in report['results'])
            finally:
                engine.close()
            if args.report:_write_report(args.report,report)
            if sys.stdout is not None:
                print(json.dumps(report,ensure_ascii=False,indent=2))
            return 0 if report.get('passed') else 1
        from ui.app import run
        return run(config,data_dir,smoke_output=args.smoke_output,no_voice=args.no_voice or args.smoke_output is not None)
    except Exception as exc:
        logging.getLogger('sirius').error('Startup/diagnostic failure: %s (payload suppressed)',type(exc).__name__)
        if args.smoke_output and isinstance(exc, ImportError):
            import traceback
            _write_report(args.smoke_output / 'report.json', {
                'passed': False, 'startup_import_error': str(exc), 'traceback': traceback.format_exc()})
        if args.report:_write_report(args.report,{'passed':False,'error_type':type(exc).__name__})
        if sys.stderr is not None:
            print('Sirius: '+type(exc).__name__+'; см. diagnostics.log',file=sys.stderr)
        return 1

if __name__=='__main__':
    multiprocessing.freeze_support()
    for stream in (sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf8',errors='replace')
    raise SystemExit(main())
