"""Worker-scoped UI Automation; values remain private and are never logged."""
from dataclasses import dataclass
import time
from skills.windows.native import NativeUnavailable

MAX_TEXT = 1_048_576


@dataclass(frozen=True, repr=False)
class TextSnapshot:
    identity: tuple
    text: str
    selected: str
    prefix: str
    suffix: str
    readonly: bool = False


class UIAutomation:
    def __enter__(self):
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        self.comtypes = comtypes
        try:
            # The generated typelib is also collected in the portable build.
            self.types = comtypes.client.GetModule('UIAutomationCore.dll')
            self.api = comtypes.client.CreateObject(self.types.CUIAutomation8, interface=self.types.IUIAutomation2)
            self.api.ConnectionTimeout = 700
            self.api.TransactionTimeout = 1000
            self.walker = self.api.ControlViewWalker
            return self
        except Exception:
            comtypes.CoUninitialize()
            raise NativeUnavailable('Windows UI Automation недоступна; команда не отправлена.') from None

    def __exit__(self, *unused):
        self.walker = self.api = self.types = None
        self.comtypes.CoUninitialize()

    def pattern(self, element, pattern_id, interface):
        try:
            value = element.GetCurrentPattern(pattern_id)
            return value.QueryInterface(getattr(self.types, interface)) if value else None
        except Exception:
            return None

    @staticmethod
    def identity(element):
        return tuple(element.GetRuntimeId())

    def focused(self, window):
        focus = self.api.GetFocusedElement()
        current = focus
        for _ in range(24):
            if not current:
                break
            if current.CurrentIsPassword:
                raise NativeUnavailable('Поле пароля не обрабатывается; команда не отправлена.')
            if current.CurrentNativeWindowHandle == window.hwnd:
                return focus
            current = self.walker.GetParentElement(current)
        raise ValueError('Focused control is outside the identified window')

    def same_focus(self, window, identity):
        try:
            return self.identity(self.focused(window)) == identity
        except Exception:
            return False

    def text_snapshot(self, window):
        focus = self.focused(window)
        identity = self.identity(focus)
        current = focus
        for _ in range(12):
            if not current or current.CurrentIsPassword:
                break
            text = self.pattern(current, 10014, 'IUIAutomationTextPattern')
            if text is not None:
                selections = text.GetSelection()
                if selections.Length != 1:
                    raise NativeUnavailable('Текстовое выделение неоднозначно; команда не отправлена.')
                selected = selections.GetElement(0)
                document = text.DocumentRange
                prefix, suffix = document.Clone(), document.Clone()
                prefix.MoveEndpointByRange(1, selected, 0)
                suffix.MoveEndpointByRange(0, selected, 1)
                values = [r.GetText(MAX_TEXT + 1) for r in (document, selected, prefix, suffix)]
                if any(len(v) > MAX_TEXT for v in values):
                    raise NativeUnavailable('Текст превышает лимит локальной проверки; команда не отправлена.')
                value = self.pattern(current, 10002, 'IUIAutomationValuePattern')
                readonly = bool(value.CurrentIsReadOnly) if value is not None else False
                return TextSnapshot(identity, *values, readonly=readonly)
            if current.CurrentNativeWindowHandle == window.hwnd:
                break
            current = self.walker.GetParentElement(current)
        raise NativeUnavailable('Приложение не предоставляет проверяемое текстовое выделение; команда не отправлена.')

    def chrome_elements(self, window):
        """Browser chrome + document roots, never webpage descendants/spoofed tabs."""
        root = self.api.ElementFromHandle(window.hwnd)
        found, pending = [], [(root, 0)]
        deadline = time.monotonic() + 2
        while pending:
            if len(found) >= 700 or time.monotonic() > deadline:
                raise NativeUnavailable('Дерево браузера не удалось прочитать полностью.')
            element, depth = pending.pop(0)
            found.append(element)
            if element.CurrentControlType == 50030 or depth >= 14:
                continue
            child = self.walker.GetFirstChildElement(element)
            while child:
                pending.append((child, depth + 1))
                if len(pending) + len(found) > 700:
                    raise NativeUnavailable('Дерево браузера слишком большое для достоверной проверки.')
                child = self.walker.GetNextSiblingElement(child)
        return found
