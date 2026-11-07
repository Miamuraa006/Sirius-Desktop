from pathlib import Path, PureWindowsPath
import sys
from unittest.mock import Mock

import pytest

from core.intent_router import IntentRouter
from skills.applications import catalog, game_mode
from voice.normalization import normalize_command


@pytest.mark.parametrize('phrase', [
    'режим игры', 'игровой режим', 'режим реградаций', 'включи игровой режим',
    'каэс два', 'каес два', 'каес 2', 'ка эс два', 'кс два', 'CS2', 'Counter-Strike 2',
    'Открой каес 2', 'открой каэс два', 'запусти игровой режим', 'открой Counter-Strike',
    'кэс два', 'открой кэс два', 'ка из два', 'кэрри с два', 'контэр страйк', 'режим ри градаций',
])
def test_command_selects_steam_cs2(phrase, monkeypatch):
    router = IntentRouter(Path(__file__).parents[1] / 'skills')
    intent = router.parse(normalize_command(phrase))
    assert (intent.skill, intent.action) == ('applications', 'open_app')
    steam_game = object()
    monkeypatch.setattr(catalog, 'installed_cs2', lambda: steam_game)
    monkeypatch.setattr(catalog.os, 'name', 'nt')
    assert catalog.resolve_app(intent.parameters['app'], {}) is steam_game


@pytest.mark.parametrize(('path', 'allowed'), [
    (r'C:\Apps\Telegram\Telegram.exe', True),
    (r'C:\Windows\System32\csrss.exe', False),
    (r'C:\Windows\explorer.exe', False),
    (r'C:\Apps\Bitsum\ParkControl.exe', False),
    (r'C:\Program Files\NVIDIA Corporation\Overlay\helper.exe', False),
    (r'C:\Program Files\Sirius\Sirius.exe', False),
    (r'D:\Games\ValveClient\bin\helper.exe', False),
    (r'D:\CS2\game\bin\win64\helper.exe', False),
    (r'C:\Apps\steamwebhelper.exe', False),
    (r'C:\Apps\runtime\msedgewebview2.exe', False),
])
def test_game_mode_exclusions(path, allowed):
    p = PureWindowsPath
    assert game_mode.eligible(p(path), p('D:/CS2'), p('C:/Windows'), p('D:/Games/ValveClient')) is allowed


def test_no_cleanup_without_real_game_window(monkeypatch):
    stop, adapter, proc = Mock(), Mock(), Mock()
    proc.info = {'name': 'cs2.exe'}
    stop.wait.side_effect = [False, True]
    adapter.find_windows.return_value = []
    monkeypatch.setattr(game_mode.psutil, 'process_iter', lambda attrs: [proc])
    monkeypatch.setattr(game_mode, 'WindowsApplicationAdapter', lambda: adapter)
    monkeypatch.setattr(game_mode, 'installed_cs2', lambda: Mock())
    release, finished = Mock(), Mock()
    monkeypatch.setattr(game_mode, 'release_apps', release)
    game_mode.watch_game({}, stop, finished)
    release.assert_not_called()
    finished.assert_not_called()


def test_verified_game_triggers_one_cleanup_then_one_exit(monkeypatch):
    stop, adapter, proc = Mock(), Mock(), Mock()
    proc.info = {'name': 'cs2.exe'}
    stop.wait.return_value = stop.is_set.return_value = False
    adapter.find_windows.return_value = [Mock()]
    monkeypatch.setattr(game_mode.psutil, 'process_iter', lambda attrs: [proc])
    monkeypatch.setattr(game_mode, 'WindowsApplicationAdapter', lambda: adapter)
    monkeypatch.setattr(game_mode, 'installed_cs2', lambda: Mock())
    monkeypatch.setattr(game_mode, 'desktop_targets', lambda *args: {})
    release, finished = Mock(return_value=True), Mock()
    monkeypatch.setattr(game_mode, 'release_apps', release)
    game_mode.watch_game({}, stop, finished)
    release.assert_called_once()
    finished.assert_called_once()


def test_game_disappears_during_grace_keeps_background_process():
    adapter, proc, stop = Mock(), Mock(), Mock()
    adapter.find_windows.return_value = []
    active = Mock(side_effect=[True, False])
    stop.wait.return_value = False
    assert not game_mode.release_apps(adapter, {Path('demo.exe'): {12: (proc, 1)}}, active, stop)
    proc.terminate.assert_not_called()


def test_scattered_words_and_literal_payload_never_start_game():
    router = IntentRouter(Path(__file__).parents[1] / 'skills')
    for text in ('объясни режим игры', 'как включить режим ри градаций', 'скопируй текст кэс два'):
        intent = router.parse(normalize_command(text))
        assert intent is None or intent.skill != 'applications'


@pytest.mark.parametrize(('first', 'second', 'accepted'), [
    ('открой кэс два', 'открой кэс два', True),
    ('режим игры', 'режим игры', True),
    ('кэс два', 'закрой', False),
    ('открой кэс два', 'кэс два', False),
    ('игры', 'режим игры', False),
])
def test_low_confidence_game_audio_requires_two_matching_full_commands(first, second, accepted):
    from voice.help_stt import HelpAwareSTT
    from voice.stt import Word, Transcript
    decoder = HelpAwareSTT(object(), stt_factory=Mock())
    original = Transcript(first, (Word(first, .5, 0, .8),))
    decoder._replay = Mock(return_value=[Word(w, .9, 0, .3) for w in second.split()])
    result = decoder._check_game(original)
    assert (result.confidence >= .65) is accepted
    if first == 'игры':
        decoder._replay.assert_not_called()


@pytest.mark.skipif(sys.platform != 'win32', reason='real Windows WM_CLOSE and tray behavior')
@pytest.mark.parametrize('behavior', ['exit', 'tray', 'keep'])
def test_native_exit_tray_and_unsaved_window(tmp_path, behavior):
    import subprocess
    import threading
    import psutil
    from skills.windows.native import wait_for

    # This process creates only our off-screen test window. Never target other desktop processes.
    script = '''
import os, sys
from pathlib import Path
import win32gui, win32con
def dispatch(hwnd, msg, wp, lp):
    if msg == win32con.WM_CLOSE:
        if sys.argv[1] == "exit":
            win32gui.PostQuitMessage(0)
        elif sys.argv[1] == "tray":
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wp, lp)
wc = win32gui.WNDCLASS()
wc.lpszClassName = "SiriusGameTest"
wc.lpfnWndProc = dispatch
atom = win32gui.RegisterClass(wc)
hwnd = win32gui.CreateWindow(atom, "Game mode fixture", win32con.WS_OVERLAPPEDWINDOW,
                             -30000, -30000, 100, 100, 0, 0, 0, None)
win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
Path(sys.argv[2]).write_text(str(os.getpid()))
win32gui.PumpMessages()
'''
    ready = tmp_path / 'ready'
    child = subprocess.Popen([sys.executable, '-c', script, behavior, str(ready)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    proc = None
    try:
        assert wait_for(lambda: ready.exists() and ready.read_text().isdigit(), timeout=10)
        proc = psutil.Process(int(ready.read_text()))
        path = Path(proc.exe())
        targets = {path: {proc.pid: (proc, proc.create_time())}}
        adapter = game_mode.WindowsApplicationAdapter()
        assert any(w.pid == proc.pid for w in adapter.windows.windows())
        assert game_mode.release_apps(adapter, targets, lambda: True, threading.Event())
        if behavior == 'keep':
            assert proc.is_running() and any(w.pid == proc.pid for w in adapter.windows.windows())
        else:
            assert wait_for(lambda: not proc.is_running(), timeout=2)
    finally:
        if proc and proc.is_running():
            proc.kill()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
