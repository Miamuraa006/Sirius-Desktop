"""Run delivered EXE, never source main.py; record boundary and hash honestly."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import psutil


def clean_environment(base=None):
    env=dict(os.environ if base is None else base)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX','QT_QPA_PLATFORM','QT_QUICK_BACKEND','QT_SCALE_FACTOR','QML2_IMPORT_PATH','QT_PLUGIN_PATH'):
        env.pop(key,None)
    system=env.get('SYSTEMROOT','C:/Windows')
    env['PATH']=system+';'+system+'/System32'
    env['PYTHONUTF8']='1'
    return env


def run(root):
    root=Path(root).resolve()
    exe=root/'dist/Sirius/Sirius.exe'
    digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    output=root/'.qa'/('frozen-'+uuid.uuid4().hex)
    output.mkdir(parents=True)
    unrelated=output/'unrelated-working-directory';unrelated.mkdir()
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'exe':str(exe),'exe_sha256':digest,
            'output_directory':str(output),'checks':{},'runs':[],
            'isolation':{'path':'Only Windows and System32','python_environment_removed':True,
                         'fresh_profiles':True,'unrelated_working_directory':str(unrelated),
                         'network_disconnected':False,'clean_machine_without_installed_python':False},
            'limitations':['Network adapters were not disconnected; sampled connections are observation, not firewall isolation.',
                           'Installed host Python was not removed; loaded DLL paths and sanitized PATH establish bundled runtime only.',
                           'GUI smoke disables voice capture; live human speech and physical Alt+M press are separate untested gates.']}
    dlls=set();connections=set();sampling_errors=set()
    def execute(name,args,result_path,timeout=150,scale=None):
        env=clean_environment()
        if scale is not None:env['QT_SCALE_FACTOR']=str(scale)
        started=time.perf_counter()
        process=subprocess.Popen([str(exe),*args],cwd=unrelated,env=env)
        row={'name':name,'pid':process.pid,'args':args}
        try:
            while process.poll() is None:
                if time.perf_counter()-started>timeout:
                    row['timeout']=True
                    for child in psutil.Process(process.pid).children(recursive=True):child.kill()
                    process.kill();process.wait(10);break
                try:
                    native=psutil.Process(process.pid)
                    for proc in [native,*native.children(recursive=True)]:
                        try:
                            dlls.update(m.path for m in proc.memory_maps() if 'python' in m.path.casefold())
                            connections.update(str(c.raddr) for c in proc.net_connections(kind='inet'))
                        except (psutil.NoSuchProcess,psutil.AccessDenied) as exc:
                            if isinstance(exc,psutil.AccessDenied):sampling_errors.add(type(exc).__name__)
                except psutil.NoSuchProcess:pass
                time.sleep(.15)
            row['exitcode']=process.wait(5)
            row['elapsed_seconds']=round(time.perf_counter()-started,3)
            data=json.loads(result_path.read_text(encoding='utf8')) if result_path.is_file() else {}
            row['report']=str(result_path);row['passed']=row['exitcode']==0 and data.get('passed') is True
        except Exception as exc:
            row['passed']=False;row['error_type']=type(exc).__name__;data={}
        report['runs'].append(row)
        return data,row['passed']
    d=output/'diagnostics.json'
    data,passed=execute('diagnostics',['--data-dir',str(output/'diag-profile'),'--diagnose','--text','загрузка процессора','--text','оперативная память','--report',str(d)],d)
    report['checks']['diagnostics']=passed and data.get('frozen') is True and len(data.get('skills',[]))==10 and all(data.get('resources',{}).values())
    v=output/'voice.json'
    _,report['checks']['voice']=execute('voice',['--data-dir',str(output/'voice-profile'),'--voice-probe',str(output/'voice'),'--report',str(v)],v)
    native_dir=output/'ui-native'
    native,passed=execute('ui-native',['--data-dir',str(output/'ui-native-profile'),'--no-voice','--smoke-output',str(native_dir)],native_dir/'report.json',timeout=60)
    native_dpr=native.get('geometries',{}).get('mini',{}).get('device_pixel_ratio',0)
    report['native_dpr']=native_dpr
    for dpi,desired in ((100,1.0),(125,1.25),(150,1.5)):
        target=output/f'ui{dpi}'
        if not passed or not native_dpr:
            report['checks'][f'ui{dpi}']=False;continue
        ui,ok=execute(f'ui{dpi}',['--data-dir',str(output/f'ui{dpi}-profile'),'--no-voice','--smoke-output',str(target)],target/'report.json',timeout=60,scale=desired/native_dpr)
        dpr=ui.get('geometries',{}).get('mini',{}).get('device_pixel_ratio',0)
        report['checks'][f'ui{dpi}']=ok and abs(dpr-desired)<.001 and all(ui.get('checks',{}).values()) and ui.get('shutdown_clean') is True
    bundle=str(exe.parent).casefold()
    external=[path for path in dlls if not path.casefold().startswith(bundle)]
    report['python_related_dlls']=sorted(dlls)
    report['external_python_dlls']=external
    report['checks']['bundled_python']=not external and any(Path(p).name.casefold()=='python312.dll' for p in dlls)
    report['network_connections_observed']=sorted(connections)
    report['sampling_errors']=sorted(sampling_errors)
    report['passed']=all(report['checks'].values()) and hashlib.sha256(exe.read_bytes()).hexdigest()==digest
    text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    (output/'FROZEN_ACCEPTANCE.json').write_text(text,encoding='utf8')
    (root/'docs/FROZEN_ACCEPTANCE.json').write_text(text,encoding='utf8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    result=run(parser.parse_args().root)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
