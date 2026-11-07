"""Tab-close regressions: page-root churn must not mask chrome evidence."""
from types import SimpleNamespace

from core.context import Context
from core.models import Intent
from skills.browser.handler import Handler, WindowsBrowserAdapter
from tests.test_native_release_regressions import Windows, API


def test_close_tab_verifies_chrome_even_while_two_document_roots_overlap():
    windows = Windows()
    def tab(identity, selected=False):
        return SimpleNamespace(CurrentControlType=50019, identity=identity,
                               selected=selected, CurrentIsOffscreen=False)
    def document(identity):
        return SimpleNamespace(CurrentControlType=50030, identity=identity,
                               value='http://localhost/fixture', CurrentIsOffscreen=False)
    before = [tab((1,)), tab((2,), True), document((10,))]
    after = [tab((1,), True), document((10,)), document((11,))]
    state = {'elements': before}
    api = API(chrome_elements=lambda window: state['elements'], identity=lambda e: e.identity)
    def pattern(element, kind, interface):
        if kind == 10010 and element.CurrentControlType == 50019:
            return SimpleNamespace(CurrentIsSelected=element.selected)
        if kind == 10002 and element.CurrentControlType == 50030:
            return SimpleNamespace(CurrentValue=element.value)
    api.pattern = pattern
    calls = []
    def chord(window, keys):
        calls.append(keys)
        state['elements'] = after
    keyboard = SimpleNamespace(require_focus=lambda window: None, chord=chord)
    adapter = WindowsBrowserAdapter(windows=windows, keyboard=keyboard,
                                    automation_factory=lambda: api, timeout=0)
    result = Handler(adapter).execute(Intent('browser', 'close_tab'), Context())
    assert result.status == 'success' and result.verified
    assert calls == [(0x11, 0x57)]
