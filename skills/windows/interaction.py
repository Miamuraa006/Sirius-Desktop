"""Small SendInput boundary. Every batch is tied to a verified foreground HWND."""
import ctypes
from ctypes import wintypes


class KeyboardInput:
    def __init__(self, windows, sender=None, modifiers_clear=None):
        self.windows = windows
        self.sender = sender or self._native_send
        self.modifiers_clear = modifiers_clear or self._modifiers_clear

    def require_focus(self, window):
        self.windows.require(window)
        active = self.windows.foreground()
        if active is None or (active.hwnd, active.pid, active.created) != (window.hwnd, window.pid, window.created):
            raise ValueError('Target lost foreground focus')

    @staticmethod
    def _modifiers_clear():
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        return not any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))

    @staticmethod
    def _native_send(events):
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                        ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]
        class DATA(ctypes.Union):
            _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('data', DATA)]
        inputs = (INPUT * len(events))(*(INPUT(1, DATA(ki=KEYBDINPUT(vk, scan, flags, 0, 0))) for vk, scan, flags in events))
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        if user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT)) != len(inputs):
            # A partial injection must not leave synthetic modifiers held down.
            releases = [(vk, scan, flags | 2) for vk, scan, flags in events if not flags & 2]
            if releases:
                up = (INPUT * len(releases))(*(INPUT(1, DATA(ki=KEYBDINPUT(vk, scan, flags, 0, 0))) for vk, scan, flags in releases))
                user32.SendInput(len(up), up, ctypes.sizeof(INPUT))
            raise OSError('Windows input injection was rejected')

    def chord(self, window, keys, guard=None):
        self.require_focus(window)
        if not self.modifiers_clear() or (guard is not None and not guard()):
            raise ValueError('Input target or physical modifiers changed')
        self.sender([(key, 0, 0) for key in keys] + [(key, 0, 2) for key in reversed(keys)])

    def text(self, window, value, guard=None):
        # UTF-16 Unicode input does not change the user's clipboard or layout.
        encoded = value.encode('utf-16-le')
        units = [int.from_bytes(encoded[i:i + 2], 'little') for i in range(0, len(encoded), 2)]
        for start in range(0, len(units), 64):
            self.require_focus(window)
            if not self.modifiers_clear() or (guard is not None and not guard()):
                raise ValueError('Input target changed')
            self.sender([event for code in units[start:start + 64] for event in ((0, code, 4), (0, code, 6))])
