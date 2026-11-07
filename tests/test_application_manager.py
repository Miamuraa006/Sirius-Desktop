"""Route real commands, replacing only Windows writes with observable test doubles."""
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest
from core.config import validate
from core.context import Context
from core.engine import Engine
from core.models import Command, Intent
from skills.applications.handler import Handler, WindowsApplicationAdapter
from skills.applications.registry import app_registry
from skills.applications.web_target import WebTab, same_site
from skills.browser.handler import BrowserSnapshot
from skills.windows.native import WindowRef
from test_skill_applications import Apps
from test_skill_browser import Automation


@pytest.fixture
def engine(tmp_path):
    service = Engine({}, tmp_path)
    service.registry['applications'].adapter = Apps()
    yield service
    service.close()


@pytest.mark.parametrize('source', ['voice', 'text'])
@pytest.mark.parametrize('name,canonical', [
    ('Steam', 'steam'), ('СТИМ', 'steam'), ('стиим', 'steam'),
    ('Telegram', 'telegram'), ('телеграм', 'telegram'), ('YouTube', 'youtube'), ('ютуб', 'youtube'),
])
def test_alias_lifecycle_preserves_other_app(engine, name, canonical, source):
    other = 'telegram' if canonical == 'steam' else 'steam'
    def say(text):
        return engine.execute(Command(text, source=source))
    assert say('открой ' + other).verified
    opened = say('запусти ' + name)
    assert opened.verified and opened.details['app'] == canonical
    assert say('переключись на ' + name).details['hwnd'] == opened.details['hwnd']
    assert engine.contexts['desktop'].last_app == canonical
    apps = engine.registry['applications'].adapter
    assert say('закрой его').status == 'needs_confirmation'
    assert len(apps.items) == 2
    assert say('подтверждаю').verified
    assert [w.app for w in apps.items] == [other]


@pytest.mark.parametrize('name', ['стииим', 'Телегром', 'Ste', 'Steam Helper', 'Steam.exe /quit', 'неизвестное'])
@pytest.mark.parametrize('verb', ['открой', 'закрой', 'переключись на'])
def test_unknown_or_misspelled_names_have_no_effect(engine, name, verb):
    assert engine.execute(Command('открой Steam')).verified
    apps = engine.registry['applications'].adapter
    apps.actions.clear()
    result = engine.execute(Command(f'{verb} {name}', source='voice'))
    assert result.status == 'failed' and 'не зарегистрировано' in result.message
    assert not engine.policy.pending and not apps.actions and len(apps.items) == 1


def test_focus_never_launches_an_absent_app(engine):
    assert engine.execute(Command('переключись на Telegram')).status == 'failed'
    assert not engine.registry['applications'].adapter.actions


def test_config_only_registration_through_normal_entry(tmp_path):
    exe = tmp_path / 'study.exe'
    exe.touch()
    config = validate({'applications': {'study': {
        'command': [str(exe)], 'process_names': ['study.exe'], 'aliases': ['учёба', 'стим'],
    }}})
    # An alias in a previously valid user config takes precedence over new defaults.
    service = Engine(config, tmp_path)
    apps = Apps()
    service.registry['applications'].adapter = apps
    try:
        assert service.execute(Command('открой учёба')).verified
        assert service.execute(Command('переключись на стим')).details['app'] == 'study'
        assert service.execute(Command('закрой study')).status == 'needs_confirmation'
        assert service.execute(Command('подтверждаю')).verified and not apps.items
        assert apps.actions[0] == ('launch', 'study', (str(exe),))
    finally:
        service.close()


@pytest.mark.parametrize('name', ['steam', 'telegram'])
def test_close_sends_only_to_verified_window_even_with_same_exe_name(tmp_path, monkeypatch, name):
    spec = app_registry({})[name]
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setenv('ProgramFiles(x86)', str(tmp_path))
    native = WindowsApplicationAdapter()
    # Use the real default declarations with the installation root redirected.
    primary = Path(spec.command[0].replace('%APPDATA%', str(tmp_path)).replace('%ProgramFiles(x86)%', str(tmp_path)))
    primary.parent.mkdir(parents=True)
    primary.touch()
    owner = primary.parent / spec.companion_paths[0] if spec.companion_paths else primary
    wanted = WindowRef(10, 20, owner.name.lower(), 'target', 1, str(owner))
    impostor = replace(wanted, hwnd=11, pid=21, executable=str(tmp_path / owner.name))
    unrelated = replace(wanted, hwnd=12, pid=22, process_name='chrome.exe', title=name)
    seen = [impostor, unrelated, wanted]
    native.windows = SimpleNamespace(windows=lambda: list(seen), validate=lambda w: w in seen, close=seen.remove)
    result = Handler(native).execute(Intent('applications', 'close_app', {'app': name}), Context(data={'confirmed': True}))
    assert result.verified and result.details['closed'] == 1 and seen == [impostor, unrelated]


def test_store_client_uses_registered_package_for_launch_and_identity(tmp_path, monkeypatch):
    native = WindowsApplicationAdapter()
    monkeypatch.setenv('APPDATA', str(tmp_path))
    package_exe = tmp_path / 'WindowsApps' / 'Telegram.exe'
    spec = app_registry({})['telegram']
    lookup = Mock(return_value=str(package_exe))
    monkeypatch.setattr(native, '_package_executable', lookup)
    start = Mock()
    monkeypatch.setattr('os.startfile', start)
    target = native.prepare(spec)
    native.launch(target)
    lookup.assert_called_once_with(spec.package_id, 'Telegram.exe')
    assert target.command == (str(package_exe),)
    start.assert_called_once_with('shell:AppsFolder\\' + spec.package_id)


@pytest.mark.parametrize('url', ['https://www.youtube.com.example.org/', 'http://www.youtube.com/',
                                'https://www.youtube.com:444/', 'https://www.youtube.com@evil.example/', None])
def test_lookalike_or_missing_document_does_not_identify_youtube(url):
    assert not same_site(url, app_registry({})['ютуб'].url)


@pytest.mark.parametrize('change', ['none', 'tab', 'origin'])
def test_youtube_closes_only_verified_tab_and_never_whole_window(change):
    spec = app_registry({})['ютуб']
    window = WindowRef(11, 21, 'chrome.exe', 'browser', 1, 'C:/browser/chrome.exe')
    windows = SimpleNamespace(windows=lambda: [window], validate=lambda w: True,
                              require=lambda w: None, foreground=lambda: window,
                              window=lambda hwnd: window, close=Mock())
    native = WindowsApplicationAdapter(windows)
    auto = Automation()
    auto.url = spec.url + 'watch?v=example'
    browser = native.web.browser
    browser.automation_factory = lambda: auto
    browser.snapshot = lambda w, api: BrowserSnapshot(document_url=api.url, selected=api.selected, tabs=api.tabs)
    keys = []
    def chord(w, shortcut, guard):
        if change == 'tab':
            auto.selected = (1,)
        if change == 'origin':
            auto.url = 'https://example.org/'
        if not guard():
            raise ValueError('selected tab changed')
        keys.append(shortcut)
        auto.tabs = ((1,),)
        auto.selected = (1,)
        auto.url = 'https://example.org/'
    browser.keyboard = SimpleNamespace(require_focus=lambda w: None, chord=chord)
    assert isinstance(native.find_windows(spec)[0], WebTab)
    result = Handler(native).execute(Intent('applications', 'close_app', {'app': 'YouTube'}),
                                     Context(data={'confirmed': True}))
    assert result.verified == (change == 'none')
    assert keys == ([(0x11, 0x57)] if change == 'none' else [])
    windows.close.assert_not_called()


def test_custom_steam_location_inherits_unclaimed_aliases_and_scopes_helper(tmp_path):
    steam = tmp_path / 'Steam.exe'
    steam.touch()
    config = validate({'applications': {'steam': {'command': [str(steam)],
                    'process_names': ['Steam.exe', 'steamwebhelper.exe'], 'aliases': ['игры']}}})
    registry = app_registry(config)
    assert registry['стиим'] == registry['игры'] == registry['стим']
    assert registry['стим'].command == (str(steam),) and registry['стим'].companion_paths


def test_windows_denied_focus_does_not_claim_success_or_change_context(monkeypatch):
    import pywintypes
    from skills.windows import native as win32
    window = WindowRef(10, 20, 'notepad.exe', executable=WindowsApplicationAdapter._executable('notepad.exe'))
    other = WindowRef(11, 21, 'calc.exe')
    windows = SimpleNamespace(windows=lambda: [window], foreground=lambda: other,
                              validate=lambda w: True, activate=Mock(side_effect=pywintypes.error(
                                  0, 'SetForegroundWindow', 'denied')))
    monkeypatch.setattr(win32, 'wait_for', lambda check: check())
    ctx = Context()
    result = Handler(WindowsApplicationAdapter(windows)).execute(
        Intent('applications', 'focus_app', {'app': 'блокнот'}), ctx)
    assert result.status == 'failed' and 'чат Sirius' in result.message and ctx.last_window is None

def test_default_browser_only_matches_selected_browser_executable(tmp_path, monkeypatch):
    chrome = tmp_path / 'Chrome' / 'chrome.exe'
    windows = [
        WindowRef(1, 10, 'chrome.exe', executable=str(chrome)),
        WindowRef(2, 11, 'chrome.exe', executable=str(tmp_path / 'other' / 'chrome.exe')),
        WindowRef(3, 12, 'firefox.exe', executable=str(tmp_path / 'firefox.exe')),
    ]
    native = WindowsApplicationAdapter(SimpleNamespace(windows=lambda: windows, validate=lambda w: True))
    monkeypatch.setattr(native, 'default_browser', lambda: str(chrome))
    assert native.find_windows(native.prepare(app_registry({})['браузер'])) == [windows[0]]


def test_stock_launcher_cannot_claim_unrelated_process(tmp_path, monkeypatch):
    spoof = WindowRef(4, 14, 'chrome.exe', executable=str(tmp_path / 'chrome.exe'))
    native = WindowsApplicationAdapter(SimpleNamespace(windows=lambda: [spoof], validate=lambda w: True))
    monkeypatch.setattr(native, '_package_executable', lambda *args: None)
    config = {'applications': {'wrong': {'command': ['notepad.exe'], 'process_names': ['chrome.exe']}}}
    assert native.find_windows(native.prepare(app_registry(config)['wrong'])) == []

def test_pronoun_after_failed_switch_never_closes_previous_app(engine):
    assert engine.execute(Command('открой Telegram')).verified
    assert engine.execute(Command('переключись на Steam')).status == 'failed'
    assert engine.execute(Command('закрой его')).status == 'failed'
    assert not engine.policy.pending
    assert [w.app for w in engine.registry['applications'].adapter.items] == ['telegram']
