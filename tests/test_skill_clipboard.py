"""Clipboard privacy and native-boundary readback. Never touches real clipboard."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import pytest
from core.models import Intent
from core.context import Context
from skills.windows.native import WindowRef


def module():
    assert (Path(__file__).parents[1] / 'skills/clipboard/handler.py').exists(), 'clipboard handler missing'
    return importlib.import_module('skills.clipboard.handler')


class Clipboard:
    def __init__(self):
        self.text = 'private fixture'
        self.calls = []
        self.accept = True
    def read_text(self):
        return self.text
    def write_text(self, text):
        self.calls.append(('set', text))
        if self.accept:
            self.text = text
    def perform(self, action, context):
        self.calls.append((action, context.last_window))
        return self.accept


@pytest.mark.parametrize('text', ['MiXeD Ёж  \n', '', 'текст'])
def test_set_exact_readback_without_disclosing_text(text):
    adapter = Clipboard()
    result = module().Handler(adapter).execute(Intent('clipboard', 'set', {'text': text}), Context())
    assert result.verified and adapter.text == text
    if text:
        assert text not in str(result)
    assert set(result.details) <= {'has_text'}


def test_set_noop_fails_instead_of_fake_success():
    adapter = Clipboard()
    adapter.accept = False
    result = module().Handler(adapter).execute(Intent('clipboard', 'set', {'text': 'new secret'}), Context())
    assert result.status == 'failed' and not result.verified
    assert 'new secret' not in str(result)


@pytest.mark.parametrize('value', [None, True, 4, 'bad\x00payload'])
def test_set_rejects_invalid_payload(value):
    adapter = Clipboard()
    result = module().Handler(adapter).execute(Intent('clipboard', 'set', {'text': value}), Context())
    assert result.status == 'failed' and not adapter.calls


@pytest.mark.parametrize('text,exists', [(None, False), ('', False), ('Private secret', True)])
def test_status_presence_only(text, exists):
    adapter = Clipboard()
    adapter.text = text
    result = module().Handler(adapter).execute(Intent('clipboard', 'status'), Context())
    assert result.verified and result.details == {'has_text': exists}
    assert 'Private secret' not in str(result)


@pytest.mark.parametrize('action', ['copy', 'paste', 'select_all'])
def test_input_requires_positive_readback(action):
    adapter = Clipboard()
    handler = module().Handler(adapter)
    assert handler.execute(Intent('clipboard', action), Context()).verified
    adapter.accept = False
    result = handler.execute(Intent('clipboard', action), Context())
    assert result.status == 'unsupported' and not result.verified
    assert 'отправлена' in result.message


def test_native_clipboard_adapter_does_not_type_without_target():
    mod = module()
    windows = SimpleNamespace(foreground=lambda: None)
    adapter = mod.WindowsClipboardAdapter(windows=windows)
    result = mod.Handler(adapter).execute(Intent('clipboard', 'paste'), Context())
    assert result.status == 'failed' and not result.verified


@pytest.mark.parametrize('action', ['copy', 'paste', 'select_all'])
@pytest.mark.parametrize('changed', [True, False])
def test_native_edit_commands_compare_private_uia_readback(action, changed):
    from skills.windows.automation import TextSnapshot
    mod = module()
    ref = WindowRef(12, 34, 'notepad.exe', created=1)
    windows = SimpleNamespace(foreground=lambda: ref, validate=lambda w: True, require=lambda w: None)
    store = Clipboard()
    store.text = 'NEW'
    store.number = 1
    store.sequence = lambda: store.number
    before = TextSnapshot((10,), 'old text', 'old', '', ' text')
    class UIA:
        current = before
        def __enter__(self):
            return self
        def __exit__(self, *unused):
            pass
        def text_snapshot(self, window):
            return self.current
        def same_focus(self, window, identity):
            return identity == (10,)
    uia = UIA()
    calls = []
    def send(window, keys, guard=None):
        assert guard()
        calls.append(keys)
        if changed:
            if action == 'copy':
                store.text, store.number = 'old', 2
            elif action == 'paste':
                uia.current = TextSnapshot((10,), 'NEW text', '', 'NEW', ' text')
            else:
                uia.current = TextSnapshot((10,), 'old text', 'old text', '', '')
    keyboard = SimpleNamespace(require_focus=lambda w: None, chord=send)
    adapter = mod.WindowsClipboardAdapter(windows=windows, clipboard=store, keyboard=keyboard,
                                         automation_factory=lambda: uia, timeout=0)
    result = mod.Handler(adapter).execute(Intent('clipboard', action), Context())
    assert result.verified is changed
    assert len(calls) == 1
    assert 'old text' not in str(result) and 'NEW' not in str(result)


def test_native_copy_rejects_empty_selection_before_keys():
    from skills.windows.automation import TextSnapshot
    mod = module()
    ref = WindowRef(12, 34, 'notepad.exe', created=1)
    windows = SimpleNamespace(foreground=lambda: ref, validate=lambda w: True, require=lambda w: None)
    @contextmanager
    def uia():
        yield SimpleNamespace(text_snapshot=lambda w: TextSnapshot((1,), 'secret', '', 'secret', ''))
    calls = []
    adapter = mod.WindowsClipboardAdapter(windows=windows, clipboard=Clipboard(),
        keyboard=SimpleNamespace(require_focus=lambda w: None, chord=lambda *args, **kw: calls.append(args)),
        automation_factory=uia)
    result = mod.Handler(adapter).execute(Intent('clipboard', 'copy'), Context())
    assert result.status == 'unsupported' and not calls and 'не отправлена' in result.message


def test_win32_clipboard_balances_locks_and_owns_writes(monkeypatch):
    import sys
    mod = module()
    calls = []
    store = {'value':'fixture'}
    native = SimpleNamespace(OpenClipboard=lambda h: calls.append(('open',h)),
        CloseClipboard=lambda: calls.append(('close',)),
        IsClipboardFormatAvailable=lambda f: True, GetClipboardData=lambda f: store['value'],
        EmptyClipboard=lambda: calls.append(('empty',)),
        SetClipboardText=lambda value, f: store.update(value=value))
    monkeypatch.setitem(sys.modules, 'win32clipboard', native)
    monkeypatch.setitem(sys.modules, 'win32gui', SimpleNamespace(CreateWindowEx=lambda *args: 50,
        DestroyWindow=lambda h: calls.append(('destroy',h))))
    adapter = mod.Win32Clipboard()
    adapter.write_text('secret fixture')
    assert adapter.read_text() == 'secret fixture'
    assert calls == [('open',50), ('empty',), ('close',), ('destroy',50), ('open',None), ('close',)]


def test_exceptions_never_expose_payload():
    adapter = Clipboard()
    def error():
        raise OSError('PRIVATE SECRET')
    adapter.read_text = error
    result = module().Handler(adapter).execute(Intent('clipboard', 'status'), Context())
    assert result.status == 'failed' and 'PRIVATE SECRET' not in str(result)
