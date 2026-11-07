"""Browser UIA state transitions with native input fully mocked."""
from contextlib import contextmanager
import importlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from core.context import Context
from core.models import Intent
from skills.windows.native import WindowRef


def module():
    assert (Path(__file__).parents[1] / 'skills/browser/handler.py').exists(), 'browser handler missing'
    return importlib.import_module('skills.browser.handler')


class Browser:
    def __init__(self):
        self.calls = []
        self.accept = True
    def perform(self, action, context, url=None):
        self.calls.append((action, url))
        return self.accept


@pytest.mark.parametrize('action', ['new_tab', 'close_tab', 'refresh', 'back', 'forward'])
def test_handler_never_verifies_only_dispatched_shortcuts(action):
    adapter = Browser()
    handler = module().Handler(adapter)
    assert handler.execute(Intent('browser', action), Context()).verified
    adapter.accept = False
    result = handler.execute(Intent('browser', action), Context())
    assert result.status == 'unsupported' and not result.verified and 'отправлена' in result.message


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///C:/secret', 'https://u:p@example.org',
    'https://example.org\nENTER', 'https://example.org\\x', 'cmd.exe', '', None, True,
    'https://example.org:99999', 'https://example.org/%00'])
def test_unsafe_urls_never_reach_input(url):
    adapter = Browser()
    result = module().Handler(adapter).execute(Intent('browser', 'open', {'url': url}), Context())
    assert result.status == 'failed' and not adapter.calls


@pytest.mark.parametrize('url,expected', [('https://example.org/Case?Q=MiXeD','https://example.org/Case?Q=MiXeD'),
    ('example.org/Case','https://example.org/Case'), ('http://127.0.0.1:12345/fixture','http://127.0.0.1:12345/fixture')])
def test_web_urls_remain_case_preserved(url, expected):
    adapter = Browser()
    result = module().Handler(adapter).execute(Intent('browser', 'open', {'url': url}), Context())
    assert result.verified and adapter.calls == [('open', expected)]


def test_search_encodes_exact_query():
    adapter = Browser()
    result = module().Handler(adapter).execute(Intent('browser', 'search', {'query': 'C++ & Ёж'}), Context())
    assert result.verified
    from urllib.parse import parse_qs, urlsplit
    assert parse_qs(urlsplit(adapter.calls[0][1]).query)['q'] == ['C++ & Ёж']


def test_search_rejects_unsafe_provider():
    adapter = Browser()
    result = module().Handler(adapter, {'browser': {'search_url':'javascript:{query}'}}).execute(Intent('browser', 'search', {'query':'hello'}), Context())
    assert result.status == 'failed' and not adapter.calls


class Windows:
    def __init__(self):
        self.ref = WindowRef(12, 34, 'msedge.exe', 'Dedicated fixture', 1, 'C:/Edge/msedge.exe')
        self.valid = True
    def foreground(self):
        return self.ref
    def validate(self, window):
        return self.valid
    def require(self, window):
        if not self.valid:
            raise ValueError('stale')
    def window(self, hwnd):
        return self.ref if self.valid else None


class Automation:
    def __init__(self):
        self.tabs = ((1,), (2,))
        self.selected = (2,)
        self.url = 'https://example.org/old'
        self.document_id = (100,)
        self.loading = False
    def __enter__(self):
        return self
    def __exit__(self, *unused):
        pass


class Keyboard:
    def __init__(self, windows, effect):
        self.windows, self.effect = windows, effect
        self.calls = []
    def require_focus(self, window):
        self.windows.require(window)
    def chord(self, window, keys, guard=None):
        self.require_focus(window)
        self.calls.append(keys)
        self.effect()


@pytest.mark.parametrize('action', ['new_tab', 'close_tab', 'back', 'forward', 'refresh'])
@pytest.mark.parametrize('changed', [True, False])
def test_native_adapter_requires_observed_state_transition(action, changed):
    mod = module()
    windows, automation = Windows(), Automation()
    def effect():
        if not changed:
            return
        if action == 'new_tab':
            automation.tabs += ((3,),)
            automation.selected = (3,)
        elif action == 'close_tab':
            automation.tabs = ((1,),)
            automation.selected = (1,)
        elif action in {'back', 'forward'}:
            automation.url = 'https://example.org/new'
        elif action == 'refresh':
            automation.document_id = (101,)
    keyboard = Keyboard(windows, effect)
    adapter = mod.WindowsBrowserAdapter(windows=windows, keyboard=keyboard,
                                       automation_factory=lambda: automation, timeout=0)
    adapter.snapshot = lambda window, api: mod.BrowserSnapshot(
        address=automation.url, document_url=automation.url, tabs=automation.tabs,
        selected=automation.selected, document_id=automation.document_id, loading=automation.loading)
    result = mod.Handler(adapter).execute(Intent('browser', action), Context())
    assert result.verified is changed
    assert len(keyboard.calls) == 1


@pytest.mark.parametrize('navigation_observed', [True, False])
def test_native_navigation_requires_document_not_only_address(navigation_observed):
    mod = module()
    windows, automation = Windows(), Automation()
    target = 'https://example.org/Case?Q=MiXeD'
    automation.address = automation.url
    automation.address_focused = False
    address = SimpleNamespace(CurrentControlType=50004, CurrentAutomationId='addressEditBox', CurrentName='Address and search bar')
    automation.focused = lambda window: address
    automation.identity = lambda element: (55,)
    automation.same_focus = lambda window, identity: identity == (55,)
    calls = []
    def chord(window, keys, guard=None):
        assert guard is None or guard()
        calls.append(keys)
        if keys == (0x11, 0x4C):
            automation.address_focused = True
        elif keys == (0x0D,):
            automation.address_focused = False
            if navigation_observed:
                automation.url = automation.address
    def text(window, value, guard=None):
        assert guard()
        automation.address = value
        calls.append(('type', value))
    keyboard = SimpleNamespace(require_focus=lambda window: None, chord=chord, text=text)
    adapter = mod.WindowsBrowserAdapter(windows=windows, keyboard=keyboard,
        automation_factory=lambda: automation, timeout=0)
    adapter.snapshot = lambda window, api: mod.BrowserSnapshot(address=automation.address,
        document_url=automation.url, document_id=(100,), tabs=automation.tabs,
        selected=automation.selected, address_focused=automation.address_focused)
    result = mod.Handler(adapter).execute(Intent('browser', 'open', {'url': target}), Context())
    assert result.verified is navigation_observed
    assert calls == [(0x11, 0x4C), ('type', target), (0x0D,)]


def test_browser_snapshot_reads_native_properties_without_page_text():
    mod = module()
    windows = Windows()
    def element(role, identity, name='', automation_id='', value=None, selected=False):
        return SimpleNamespace(CurrentControlType=role, CurrentIsOffscreen=False,
            CurrentHasKeyboardFocus=False, CurrentIsEnabled=True, CurrentName=name,
            CurrentAutomationId=automation_id, identity=identity, value=value, selected=selected)
    elements = [element(50004, (1,), automation_id='addressEditBox', value='https://example.org/'),
                element(50019, (2,), selected=True), element(50019, (3,)),
                element(50030, (4,), value='https://example.org/'), element(50000, (5,), name='Stop loading')]
    def pattern(item, kind, interface):
        if kind == 10002 and item.value is not None:
            return SimpleNamespace(CurrentValue=item.value)
        if kind == 10010 and item.CurrentControlType == 50019:
            return SimpleNamespace(CurrentIsSelected=item.selected)
    api = SimpleNamespace(chrome_elements=lambda window: elements, identity=lambda e: e.identity, pattern=pattern)
    snapshot = mod.WindowsBrowserAdapter(windows=windows).snapshot(windows.ref, api)
    assert snapshot.address == snapshot.document_url == 'https://example.org/'
    assert snapshot.tabs == ((2,), (3,)) and snapshot.selected == (2,) and snapshot.loading


def test_native_adapter_rejects_other_app_without_shortcut():
    mod = module()
    windows = Windows()
    windows.ref = WindowRef(12, 34, 'notepad.exe', created=1)
    keyboard = Keyboard(windows, lambda: None)
    adapter = mod.WindowsBrowserAdapter(windows=windows, keyboard=keyboard)
    result = mod.Handler(adapter).execute(Intent('browser','new_tab'), Context())
    assert result.status == 'unsupported' and not keyboard.calls
