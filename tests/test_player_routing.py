from types import SimpleNamespace

import pytest

from core.context import Context
from core.models import Intent
from skills.media.handler import Handler, NoActiveSession, WindowsMediaAdapter
from skills.windows.native import NativeUnavailable


def test_web_target_never_controls_browser_wide_media_session(monkeypatch):
    from skills.media import web_player
    seen = []
    target = {'site': 'https://www.youtube.com/', 'tab_id': (7,), 'source': 'youtube'}
    def play_web(t):
        seen.append(t)
        return {'state': 'playing'}
    monkeypatch.setattr(web_player, 'play_web_target', play_web)
    adapter = WindowsMediaAdapter(manager_factory=lambda: pytest.fail('unrelated session requested'))
    assert Handler(adapter).execute(Intent('media', 'play', target), Context()).verified
    assert seen == [target]


def test_missing_session_recovers_only_a_verified_open_player(monkeypatch):
    from skills.media import open_player
    target = {'source': 'ru.yandex.desktop.music', 'hwnd': 12}
    def perform(action, target=None):
        if target is None:
            raise NoActiveSession()
        return {'state': 'playing'} if target['hwnd'] == 12 else {}
    def resolve(config, hwnd):
        if hwnd != 12:
            raise NativeUnavailable('Выберите плеер.')
        return target
    monkeypatch.setattr(open_player, 'find_open_player', resolve)
    handler = Handler(SimpleNamespace(perform=perform))
    assert handler.execute(Intent('media', 'play'), Context(last_window=12)).verified
    assert handler.execute(Intent('media', 'play'), Context(last_window=13)).status == 'unsupported'
