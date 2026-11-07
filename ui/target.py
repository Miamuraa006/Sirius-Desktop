"""Remember only an external foreground HWND/PID, never titles or contents."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class Win32Focus:
    def __init__(self):
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetForegroundWindow.argtypes = ()
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.IsWindow.argtypes = (wintypes.HWND,)
        self.api.IsWindow.restype = wintypes.BOOL
        self.api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.api.GetWindowThreadProcessId.restype = wintypes.DWORD

    def foreground_window(self):
        return self.api.GetForegroundWindow()

    def window_pid(self, hwnd):
        if not hwnd or not self.api.IsWindow(hwnd):
            return None
        pid = wintypes.DWORD()
        if not self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        return pid.value or None


class ExternalTarget:
    """Poll briefly on the GUI thread; adapters must revalidate at execution."""

    def __init__(self, *, api=None, own_pid=None):
        self.api = api if api is not None else (Win32Focus() if os.name == "nt" else None)
        self.own_pid = own_pid if own_pid is not None else os.getpid()
        self._last = None

    def snapshot(self):
        if self.api is None:
            return None
        try:
            hwnd = self.api.foreground_window()
            pid = self.api.window_pid(hwnd)
            if hwnd and pid and pid != self.own_pid:
                self._last = {"hwnd": int(hwnd), "pid": int(pid)}
            if self._last and self.api.window_pid(self._last["hwnd"]) != self._last["pid"]:
                self._last = None
        except (OSError, ValueError):
            self._last = None
        return dict(self._last) if self._last else None
