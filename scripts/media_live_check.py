"""Explicit live playback check; keeps track metadata and audio out of reports."""
import argparse
import asyncio
import json
from pathlib import Path

from core.config import load_config
from core.engine import Engine
from core.models import Command


async def sessions():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    manager = await Manager.request_async()
    return {s.source_app_user_model_id: s for s in manager.get_sessions()}


async def snapshot():
    return {key: {'state': s.get_playback_info().playback_status.name.lower(),
                  'next': s.get_playback_info().controls.is_next_enabled,
                  'previous': s.get_playback_info().controls.is_previous_enabled}
            for key, s in (await sessions()).items()}


async def set_playing(key, playing):
    available = await sessions()
    session = available.get(key)
    if session is None:
        raise RuntimeError('Session closed during check: ' + key)
    desired = 'playing' if playing else 'paused'
    method = session.try_play_async if playing else session.try_pause_async
    if session.get_playback_info().playback_status.name.lower() != desired:
        if not await method():
            raise RuntimeError('Player rejected test preparation: ' + key)
    for attempt in range(100):
        if session.get_playback_info().playback_status.name.lower() == desired:
            return
        # A newly selected network track may still be loading. This is setup,
        # not the command under test; repeat only an explicit desired state.
        if attempt in {30, 60}:
            await method()
        await asyncio.sleep(.05)
    raise RuntimeError('Player did not reach test state: ' + key)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--control', action='store_true')
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    before = asyncio.run(snapshot())
    report = {'before': before, 'checks': [], 'restored': False, 'passed': False}
    if not args.control:
        print(json.dumps(before, ensure_ascii=False, indent=2))
        return
    config = load_config(args.output / 'data')
    config['history']['enabled'] = False
    engine = Engine(config, args.output / 'data')
    keys = [k for k in before if k == 'ru.yandex.desktop.music' or k.casefold().startswith('chrome')]
    try:
        for key in keys:
            for other in keys:
                asyncio.run(set_playing(other, False))
            asyncio.run(set_playing(key, True))
            for command in ['поставь паузу', 'пауза', 'продолжи', 'пауза']:
                result = engine.execute(Command(command, 'text', 'playback-live'))
                states = asyncio.run(snapshot())
                expected = 'playing' if command == 'продолжи' else 'paused'
                passed = result.verified and states[key]['state'] == expected and all(
                    states[other]['state'] == 'paused' for other in keys if other != key)
                report['checks'].append({'player': key, 'command': command, 'passed': passed,
                                         'status': result.status, 'state': states[key]['state']})
                if not passed:
                    raise RuntimeError('Live playback check failed')
            # Track switching is checked only where Windows advertises support.
            for command, control in [('следующая', 'next'), ('предыдущая', 'previous')]:
                if not before[key][control]:
                    report['checks'].append({'player': key, 'command': command, 'supported': False})
                    continue
                asyncio.run(set_playing(key, True))
                result = engine.execute(Command(command, 'text', 'playback-live'))
                report['checks'].append({'player': key, 'command': command, 'passed': result.verified,
                                         'status': result.status, 'details': result.details})
                if not result.verified:
                    raise RuntimeError('Live track check failed')
                asyncio.run(set_playing(key, False))
        report['passed'] = bool(keys) and all(c.get('passed', True) for c in report['checks'])
    finally:
        engine.close()
        restore_errors = []
        for key in keys:
            try:
                asyncio.run(set_playing(key, before[key]['state'] == 'playing'))
            except Exception as exc:
                restore_errors.append(type(exc).__name__)
        report['restored'] = not restore_errors
        report['restore_errors'] = restore_errors
        report['after'] = asyncio.run(snapshot())
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
