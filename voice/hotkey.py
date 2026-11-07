"""Global Alt+M via RegisterHotKey, without keyboard hooks or elevation."""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes

MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5349
_log = logging.getLogger(__name__)


class Win32HotkeyAPI:
    """Construct and use only on the thread owning the registration/queue."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows required")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                            wintypes.UINT, wintypes.UINT, wintypes.UINT)
        self.user32.PeekMessageW.restype = wintypes.BOOL

    def register(self, modifiers: int, key: int) -> bool:
        msg = wintypes.MSG()
        self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # Create thread queue.
        return bool(self.user32.RegisterHotKey(None, HOTKEY_ID, modifiers, key))

    def poll(self) -> bool:
        msg = wintypes.MSG()
        fired = False
        # Bound drain time so stop remains prompt even with a busy queue.
        for _ in range(64):
            if not self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                break
            fired |= msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID
        return fired

    def unregister(self) -> bool:
        return bool(self.user32.UnregisterHotKey(None, HOTKEY_ID))


class GlobalHotkey:
    def __init__(self, callback, modifiers=1, key=77, on_error=None, *, api_factory=None):
        if type(modifiers) is not int or modifiers < 1 or modifiers & ~0x400F:
            raise ValueError("hotkey.modifiers must contain ALT/CTRL/SHIFT/WIN")
        if not modifiers & 0xF or type(key) is not int or not 1 <= key <= 254:
            raise ValueError("Invalid modified virtual key")
        self.callback = callback
        self.modifiers = modifiers | MOD_NOREPEAT
        self.key = key
        self.on_error = on_error
        self._factory = api_factory or Win32HotkeyAPI
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._registered = threading.Event()
        self._lifecycle = threading.Lock()
        self._thread = None

    @property
    def registered(self) -> bool:
        return self._registered.is_set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait_ready(self, timeout: float = 2.0) -> bool:
        """Ready means registration was attempted; inspect registered for result."""
        return self._ready.wait(timeout)

    def _error(self, message: str) -> None:
        _log.warning(message)
        if self.on_error is not None:
            try:
                self.on_error(message)
            except Exception:
                pass

    def start(self):
        with self._lifecycle:
            if self.running:
                return self
            self._ready.clear()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="SiriusHotkey", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        with self._lifecycle:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if self.running and thread is not threading.current_thread():
            self._error("Поток глобальной клавиши ещё завершает работу.")

    def _run(self) -> None:
        api = None
        registered = False
        try:
            api = self._factory()
            if self._stop.is_set():
                return
            registered = api.register(self.modifiers, self.key)
            if not registered:
                self._error("Глобальная клавиша занята или недоступна; измените hotkey в config.json.")
                return
            self._registered.set()
            self._ready.set()
            while not self._stop.is_set():
                if api.poll() and not self._stop.is_set():
                    try:
                        self.callback()
                    except Exception:
                        self._error("Не удалось активировать голос глобальной клавишей.")
                self._stop.wait(.02)
        except Exception:
            self._error("Не удалось зарегистрировать или обслужить глобальную клавишу Windows.")
        finally:
            if registered and api is not None:
                try:
                    if not api.unregister():
                        self._error("Windows не подтвердил освобождение глобальной клавиши.")
                except Exception:
                    self._error("Ошибка освобождения глобальной клавиши Windows.")
            self._registered.clear()
            self._ready.set()
