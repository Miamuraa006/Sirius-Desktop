"""Opt-in Windows hardware QA. It restores volume/brightness in finally blocks.

No microphone capture, no browser access and no clipboard content collection.
File and UI integration are exercised by separate controlled acceptance scripts.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import platform
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.models import Intent,Result
from core.context import Context


def run(output: Path, *, volume=False, brightness=False):
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),
            'python':sys.version,'cases':[], 'microphone_opened':False}
    def save():
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def record(name,call):
        start=time.perf_counter()
        try:
            result=call()
            row={'name':name,**asdict(result)}
        except Exception as exc:
            row={'name':name,'status':'failed','verified':False,'message':'Native probe raised '+type(exc).__name__,'details':{}}
        row['elapsed_ms']=round((time.perf_counter()-start)*1000,3)
        report['cases'].append(row);save()
        return row
    from skills.system_monitor.handler import Handler as Monitor
    for action in ('cpu','ram','disk','battery','temperature'):
        record('system_monitor.'+action,lambda a=action:Monitor().execute(Intent('system_monitor',a),Context()))
    from skills.volume.handler import WindowsVolumeAdapter,Handler as Volume
    va=WindowsVolumeAdapter()
    try:
        with va.session() as endpoint:
            level=endpoint.get_level();muted=endpoint.get_mute()
        report['volume_baseline']={'level':level,'muted':muted};save()
        if volume:
            try:
                desired=level-1 if level>0 else 1
                record('volume.set',lambda:Volume().execute(Intent('volume','set',{'value':desired}),Context()))
                record('volume.mute_toggle',lambda:Volume().execute(Intent('volume','unmute' if muted else 'mute'),Context()))
            finally:
                record('volume.restore_level',lambda:Volume().execute(Intent('volume','set',{'value':level}),Context()))
                record('volume.restore_mute',lambda:Volume().execute(Intent('volume','mute' if muted else 'unmute'),Context()))
                with va.session() as endpoint:
                    report['volume_restored']=endpoint.get_level()==level and endpoint.get_mute()==muted
                save()
    except Exception as exc:
        report['volume_probe_error']=type(exc).__name__;save()
    from skills.brightness.handler import WindowsBrightnessAdapter,Handler as Brightness
    ba=WindowsBrightnessAdapter()
    try:
        with ba.session() as display:
            level=display.get_level()
        report['brightness_baseline']=level;save()
        if brightness:
            try:
                desired=level-1 if level>1 else 2
                record('brightness.set',lambda:Brightness().execute(Intent('brightness','set',{'value':desired}),Context()))
            finally:
                record('brightness.restore',lambda:Brightness().execute(Intent('brightness','set',{'value':level}),Context()))
                with ba.session() as display:
                    report['brightness_restored']=display.get_level()==level
                save()
    except Exception as exc:
        report['brightness_probe_error']=type(exc).__name__;save()
    report['passed']=all(c['status'] in ('success','unsupported') and (c['status']!='success' or c['verified']) for c in report['cases']) and not any(k.endswith('_error') for k in report)
    if volume:report['passed'] &= report.get('volume_restored',False)
    if brightness:report['passed'] &= report.get('brightness_restored',False)
    save()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--volume',action='store_true')
    parser.add_argument('--brightness',action='store_true')
    args=parser.parse_args()
    report=run(args.output,volume=args.volume,brightness=args.brightness)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
