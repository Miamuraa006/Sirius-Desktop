"""Shared targeting/input guard: no input is sent in any test."""
import importlib
import os
from types import SimpleNamespace
import pytest
from core.context import Context
from skills.windows.native import WindowRef


def native():
    mod = importlib.import_module('skills.windows.native')
    assert hasattr(mod, 'context_target'), 'Shared context target resolver missing'
    return mod


@pytest.mark.parametrize('key', ['window_pid', 'last_window_pid'])
def test_shared_target_accepts_engine_snapshot_but_not_reused_pid(key):
    ref = WindowRef(12, 34, 'notepad.exe', created=1.0)
    adapter = SimpleNamespace(foreground=lambda: None, window=lambda hwnd: ref, validate=lambda w: True)
    context = Context(last_window=12, data={key: 34})
    assert native().context_target(adapter, context) == ref
    context.data[key] = 35
    assert native().context_target(adapter, context) is None


def test_keyboard_never_sends_to_stale_or_background_window():
    from pathlib import Path
    assert (Path(__file__).parents[1] / 'skills/windows/interaction.py').is_file(), 'Input guard missing'
    from skills.windows.interaction import KeyboardInput
    ref = WindowRef(12, 34, 'notepad.exe', created=1.0)
    calls = []
    adapter = SimpleNamespace(foreground=lambda: None, require=lambda w: None)
    keyboard = KeyboardInput(adapter, sender=calls.append, modifiers_clear=lambda: True)
    with pytest.raises(ValueError):
        keyboard.chord(ref, (0x11, 0x43))
    assert not calls
    adapter.foreground = lambda: ref
    keyboard.chord(ref, (0x11, 0x43))
    assert calls == [[(0x11, 0, 0), (0x43, 0, 0), (0x43, 0, 2), (0x11, 0, 2)]]


def test_uia_browser_walk_excludes_web_document_descendants():
    from skills.windows.automation import UIAutomation
    page_tab = SimpleNamespace(CurrentControlType=50019)
    document = SimpleNamespace(CurrentControlType=50030)
    real_tab = SimpleNamespace(CurrentControlType=50019)
    root = SimpleNamespace(CurrentControlType=50032)
    children = {id(root): [real_tab, document], id(document): [page_tab]}
    parents = {id(real_tab): root, id(document): root, id(page_tab): document}
    def first(item):
        return next(iter(children.get(id(item), [])), None)
    def sibling(item):
        items = children[id(parents[id(item)])]
        index = next(i for i, node in enumerate(items) if node is item) + 1
        return items[index] if index < len(items) else None
    automation = UIAutomation()
    automation.api = SimpleNamespace(ElementFromHandle=lambda hwnd: root)
    automation.walker = SimpleNamespace(GetFirstChildElement=first, GetNextSiblingElement=sibling)
    found = automation.chrome_elements(WindowRef(12, 34, 'msedge.exe'))
    assert len(found) == 3 and all(item is not page_tab for item in found)


def test_uia_rejects_password_without_reading_text():
    from skills.windows.automation import UIAutomation
    from skills.windows.native import NativeUnavailable
    password = SimpleNamespace(CurrentIsPassword=True)
    automation = UIAutomation()
    automation.api = SimpleNamespace(GetFocusedElement=lambda: password)
    with pytest.raises(NativeUnavailable):
        automation.text_snapshot(WindowRef(12, 34, 'notepad.exe'))


def test_unicode_input_uses_utf16_and_never_touches_clipboard():
    from skills.windows.interaction import KeyboardInput
    ref = WindowRef(12, 34, 'notepad.exe', created=1)
    calls = []
    adapter = SimpleNamespace(foreground=lambda: ref, require=lambda w: None)
    keyboard = KeyboardInput(adapter, sender=calls.append, modifiers_clear=lambda: True)
    keyboard.text(ref, 'Ё😀')
    assert calls == [[(0, 0x401, 4), (0, 0x401, 6), (0, 0xD83D, 4), (0, 0xD83D, 6), (0, 0xDE00, 4), (0, 0xDE00, 6)]]


def test_shared_target_rejects_sirius_and_reused_process_creation():
    ref = WindowRef(12, os.getpid(), 'Sirius.exe', created=1.0)
    adapter = SimpleNamespace(foreground=lambda: ref, window=lambda hwnd: ref, validate=lambda w: True)
    assert native().context_target(adapter, Context()) is None
    ref = WindowRef(12, 34, 'notepad.exe', created=2.0)
    adapter.foreground = lambda: None
    assert native().context_target(adapter, Context(last_window=12, data={'window_pid': 34, 'last_window_created': 1.0})) is None
