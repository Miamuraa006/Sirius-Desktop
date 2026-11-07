"""Private clipboard operations and focus-bound, UIA-verified edit commands."""
from contextlib import contextmanager
import time
from core.models import Result
from skills.windows.native import WindowsAdapter, NativeUnavailable, context_target, wait_for
from skills.windows.interaction import KeyboardInput
from skills.windows.automation import UIAutomation, MAX_TEXT


def plain(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


class Win32Clipboard:
    @contextmanager
    def opened(self, writing=False):
        import win32clipboard
        import win32gui
        hwnd = None
        opened = False
        try:
            if writing:
                # A real owner is required for EmptyClipboard/SetClipboardData.
                hwnd = win32gui.CreateWindowEx(0, 'STATIC', '', 0, 0, 0, 0, 0, -3, 0, 0, None)
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    win32clipboard.OpenClipboard(hwnd)
                    opened = True
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise OSError('Clipboard is busy') from None
                    time.sleep(0.02)
            yield win32clipboard
        finally:
            if opened:
                win32clipboard.CloseClipboard()
            if hwnd:
                win32gui.DestroyWindow(hwnd)

    def read_text(self):
        with self.opened() as clipboard:
            if not clipboard.IsClipboardFormatAvailable(13):
                return None
            text = clipboard.GetClipboardData(13)
            if not isinstance(text, str) or len(text) > MAX_TEXT:
                raise NativeUnavailable('Содержимое буфера превышает лимит проверки.')
            return text

    def write_text(self, text):
        with self.opened(writing=True) as clipboard:
            clipboard.EmptyClipboard()
            clipboard.SetClipboardText(text, 13)

    @staticmethod
    def sequence():
        import win32clipboard
        return win32clipboard.GetClipboardSequenceNumber()


class WindowsClipboardAdapter:
    def __init__(self, windows=None, clipboard=None, keyboard=None, automation_factory=None, timeout=1.5):
        self.windows = windows if windows is not None else WindowsAdapter()
        self.clipboard = clipboard if clipboard is not None else Win32Clipboard()
        self.keyboard = keyboard if keyboard is not None else KeyboardInput(self.windows)
        self.automation_factory = automation_factory or UIAutomation
        self.timeout = timeout

    def read_text(self):
        return self.clipboard.read_text()

    def write_text(self, text):
        self.clipboard.write_text(text)

    def target(self, context):
        return context_target(self.windows, context)

    def perform(self, action, context):
        window = self.target(context)
        if window is None:
            raise ValueError('External target is not identified')
        self.windows.require(window)
        active = self.windows.foreground()
        if active is None or active.hwnd != window.hwnd:
            self.windows.activate(window)
        self.keyboard.require_focus(window)
        with self.automation_factory() as automation:
            before = automation.text_snapshot(window)
            guard = lambda: automation.same_focus(window, before.identity)
            if action == 'copy':
                if not before.selected:
                    raise NativeUnavailable('Нет проверяемого текстового выделения; команда не отправлена.')
                sequence = self.clipboard.sequence()
                expected = before.selected
                key = 0x43
            elif action == 'paste':
                if before.readonly:
                    raise NativeUnavailable('Текстовое поле доступно только для чтения; команда не отправлена.')
                payload = self.read_text()
                if payload is None:
                    raise NativeUnavailable('В буфере нет проверяемого текста; команда не отправлена.')
                sequence = self.clipboard.sequence()
                expected = before.prefix + payload + before.suffix
                key = 0x56
                # A concurrent clipboard change must not substitute a different payload.
                if self.read_text() != payload or self.clipboard.sequence() != sequence:
                    raise ValueError('Clipboard changed before paste')
            elif action == 'select_all':
                expected, key = before.text, 0x41
            else:
                raise ValueError('Unknown clipboard action')
            self.keyboard.chord(window, (0x11, key), guard=guard)
            def verified():
                self.keyboard.require_focus(window)
                if not guard():
                    return False
                if action == 'copy':
                    observed = self.read_text()
                    return self.clipboard.sequence() != sequence and observed is not None and plain(observed) == plain(expected)
                after = automation.text_snapshot(window)
                if action == 'select_all':
                    return (plain(after.text) == plain(expected) and plain(after.selected) == plain(expected)
                            and not after.prefix and not after.suffix)
                return plain(after.text) == plain(expected)
            try:
                return wait_for(verified, timeout=self.timeout)
            except Exception:
                # Input was sent, but lost focus/API prevents truthful confirmation.
                return False


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsClipboardAdapter()

    def execute(self, intent, context):
        action = intent.action
        if intent.skill != 'clipboard' or action not in {'status', 'set', 'copy', 'paste', 'select_all'}:
            return Result.fail('Неизвестная операция с буфером обмена.')
        try:
            if action == 'status':
                present = bool(self.adapter.read_text())
                return Result.ok('В буфере есть текст.' if present else 'Текста в буфере нет.', has_text=present)
            if action == 'set':
                text = intent.parameters.get('text')
                if not isinstance(text, str) or '\x00' in text or len(text) > MAX_TEXT:
                    return Result.fail('Нужен текст допустимой длины без нулевых символов.')
                self.adapter.write_text(text)
                if self.adapter.read_text() != text:
                    return Result.fail('Изменение буфера обмена не подтверждено.')
                return Result.ok('Текст установлен в буфере обмена.', has_text=bool(text))
            if self.adapter.perform(action, context) is not True:
                return Result.unsupported('Команда отправлена целевому окну, но приложение не предоставило подтверждение результата.')
            return Result.ok({'copy': 'Копирование выделенного текста подтверждено.',
                              'paste': 'Вставка текста подтверждена.',
                              'select_all': 'Выделение всего текста подтверждено.'}[action])
        except NativeUnavailable:
            return Result.unsupported('Нет доступного проверяемого текста или UI Automation; команда не отправлена.')
        except Exception:
            return Result.fail('Операция с буфером обмена не подтверждена. Содержимое не сохранялось в журнал.')
