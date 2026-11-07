"""Rounded native windows with QML glass and no system acrylic."""
import ctypes
from ctypes import wintypes
import os
import sys


def apply_backdrop(window, mode):
    if os.name != "nt" or sys.getwindowsversion().build < 22621:
        return {"supported": False, "material": "qml-transparency"}
    # Offscreen test handles are not real HWNDs.
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() != "windows":
        return {"supported": False, "material": "offscreen"}
    try:
        api = ctypes.WinDLL("dwmapi", use_last_error=True)
        api.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        api.DwmSetWindowAttribute.restype = ctypes.c_long
        hwnd = int(window.winId())
        def set_value(attribute, value):
            data = ctypes.c_int(value)
            return int(api.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)))
        set_value(20, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_value(33, 2)  # DWMWA_WINDOW_CORNER_PREFERENCE: round
        result = set_value(38, 1)  # DWMSBT_NONE: no milky Desktop Acrylic.
        return {"supported": result == 0, "hresult": result,
                "material": "qml-transparency"}
    except (OSError, ValueError):
        return {"supported": False, "material": "qml-transparency"}
