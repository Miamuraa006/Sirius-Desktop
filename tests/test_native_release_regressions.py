"""Regression cases discovered by the real disposable Windows release probe.

These are boundary regressions, not substitutes for docs/NATIVE_TESTS.json.
"""
from types import SimpleNamespace

from core.context import Context
from core.models import Intent
from skills.browser.handler import BrowserSnapshot, Handler, WindowsBrowserAdapter
from skills.windows.native import WindowRef


class Windows:
    ref = WindowRef(12, 34, 'chrome.exe', 'Disposable fixture', 1, 'C:/Chrome/chrome.exe')

    def foreground(self):
        return self.ref

    def require(self, window):
        assert window == self.ref

    def validate(self, window):
        return window == self.ref


class API(SimpleNamespace):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_browser_can_navigate_from_blank_without_preexisting_document():
    windows, api = Windows(), API()
    address = SimpleNamespace(CurrentControlType=50004, CurrentAutomationId='omnibox', CurrentName='')
    api.focused = lambda window: address
    api.identity = lambda element: (55,)
    api.same_focus = lambda window, identity: identity == (55,)
    state = {'url': None, 'focused': False}
    target = 'http://127.0.0.1:8765/fixture'

    def chord(window, keys, guard=None):
        assert guard is None or guard()
        if keys == (0x11, 0x4C):
            state['focused'] = True
        elif keys == (0x0D,):
            state.update(url=target, focused=False)

    keyboard = SimpleNamespace(require_focus=lambda window: None, chord=chord,
                               text=lambda window, value, guard: guard())
    adapter = WindowsBrowserAdapter(windows=windows, keyboard=keyboard, automation_factory=lambda: api, timeout=0)
    adapter.snapshot = lambda window, api: BrowserSnapshot(
        address='about:blank', document_url=state['url'], document_id=(10,) if state['url'] else None,
        tabs=((1,),), selected=(1,), address_focused=state['focused'])
    result = Handler(adapter).execute(Intent('browser', 'open', {'url': target}), Context())
    assert result.status == 'success' and result.verified


def test_browser_ignores_chrome_svg_document_without_a_url():
    windows = Windows()
    elements = [SimpleNamespace(CurrentControlType=50030, CurrentIsOffscreen=False,
                                CurrentName='Search icon', identity=(1,), value=''),
                SimpleNamespace(CurrentControlType=50030, CurrentIsOffscreen=False,
                                CurrentName='Fixture', identity=(2,), value='http://127.0.0.1:8765/fixture')]
    api = SimpleNamespace(chrome_elements=lambda window: elements, identity=lambda e: e.identity,
                          pattern=lambda e, kind, interface: SimpleNamespace(CurrentValue=e.value))
    observed = WindowsBrowserAdapter(windows=windows).snapshot(windows.ref, api)
    assert observed.document_id == (2,)
    assert observed.document_url == 'http://127.0.0.1:8765/fixture'


def test_browser_retries_replaced_uia_document_but_does_not_repeat_input():
    windows, api = Windows(), API()
    calls = []
    keyboard = SimpleNamespace(require_focus=lambda window: None,
                               chord=lambda window, keys: calls.append(keys))
    adapter = WindowsBrowserAdapter(windows=windows, keyboard=keyboard,
                                    automation_factory=lambda: api, timeout=0.2)
    class StaleDocument(Exception):
        hresult = -2147220991
    snapshots = iter([BrowserSnapshot(document_id=(1,), document_url='http://localhost/one'),
                      StaleDocument(),
                      BrowserSnapshot(document_id=(2,), document_url='http://localhost/two')])
    def snapshot(window, api):
        value = next(snapshots)
        if isinstance(value, Exception):
            raise value
        return value
    adapter.snapshot = snapshot
    result = Handler(adapter).execute(Intent('browser', 'forward'), Context())
    assert result.status == 'success' and result.verified
    assert calls == [(0x12, 0x27)]


def test_uwp_core_window_soft_close_uses_system_close_message():
    from skills.windows.native import WindowsAdapter
    messages = []
    gui = SimpleNamespace(GetClassName=lambda hwnd: 'Windows.UI.Core.CoreWindow',
                          PostMessage=lambda *args: messages.append(args))
    adapter = WindowsAdapter(api=(gui, None, None))
    adapter.require = lambda window: None
    adapter.close(Windows.ref)
    assert messages == [(Windows.ref.hwnd, 0x0112, 0xF060, 0)]


def test_app_enumeration_ignores_unrelated_host_that_disappeared():
    from skills.applications.handler import WindowsApplicationAdapter, app_registry
    host = WindowRef(40, 50, 'applicationframehost.exe', created=1)
    notepad = WindowRef(41, 51, 'notepad.exe', created=2)
    def children(window):
        raise ValueError('Window identity is no longer valid')
    windows = SimpleNamespace(windows=lambda: [host, notepad], children=children,
                              validate=lambda window: window == notepad)
    adapter = WindowsApplicationAdapter(windows=windows)
    assert adapter.find_windows(app_registry({})['notepad']) == [notepad]
