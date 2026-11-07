"""Resolve an already-open player when Windows has not published a media session."""
from dataclasses import replace

from skills.applications.handler import WindowsApplicationAdapter
from skills.applications.manager import playback_target
from skills.applications.registry import app_registry
from skills.windows.native import NativeUnavailable


def find_open_player(config, preferred_hwnd=None):
    adapter = WindowsApplicationAdapter()
    apps = app_registry(config)
    candidates = []
    for name in ('yandex_music', 'youtube'):
        spec = adapter.prepare(apps[name])
        if not spec.media_source:
            continue
        variants = [spec]
        if name == 'yandex_music' and not spec.url:
            variants += [replace(spec, url=site) for site in ('https://music.yandex.ru/', 'https://music.yandex.com/')]
        for variant in variants:
            for window in adapter.find_windows(variant):
                if adapter.validate(window):
                    candidates.append(playback_target(variant, window))
    focused = [t for t in candidates if t['hwnd'] == preferred_hwnd]
    if len(focused) == 1:
        return focused[0]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise NativeUnavailable('Открыты разные плееры. Скажите «включи видео на ютубе» или «включи музыку в Яндекс Музыке».')
    raise NativeUnavailable('Открытый плеер не найден. Откройте Яндекс Музыку или вкладку YouTube с видео.')
