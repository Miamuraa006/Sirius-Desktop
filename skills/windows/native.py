"""Lazy Windows boundaries shared by owned skills; no import-time native work."""
from dataclasses import dataclass
import os
import sys
import time


class NativeUnavailable(RuntimeError):
    """Platform or a genuinely unavailable hardware/UI automation capability."""


PROTECTED_PROCESSES = frozenset({
    'parkcontrol.exe', 'nvcplui.exe', 'nvcontainer.exe', 'nvidia app.exe', 'nvdisplay.container.exe',
    'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe',
    'lsass.exe', 'winlogon.exe', 'svchost.exe', 'dwm.exe', 'sihost.exe',
    'shellexperiencehost.exe', 'startmenuexperiencehost.exe', 'searchhost.exe',
    'securityhealthsystray.exe',
})
SHELL_CLASSES = frozenset({'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'})


@dataclass(frozen=True)
class WindowRef:
    hwnd: int
    pid: int
    process_name: str
    title: str = ''
    created: float | None = None
    executable: str = ''


def wait_for(predicate, timeout=1.5, interval=0.05):
    """Bounded readback; never interpret a dispatched call as its outcome."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def focus_window(adapter, window, validate):
    if not validate(window):
        return False
    def focused():
        active = adapter.foreground()
        return active is not None and (active.hwnd, active.pid) == (window.hwnd, window.pid) and validate(window)
    if focused():
        return True
    try:
        adapter.activate(window)
    except Exception as exc:
        if getattr(exc, 'funcname', None) != 'SetForegroundWindow':
            raise
    return wait_for(focused)


def remember_window(context, window):
    context.last_window = window.hwnd
    context.data['window_pid'] = window.pid
    context.data['last_window_pid'] = window.pid
    context.data['last_window_created'] = window.created


def context_target(adapter, context):
    """Current external target, or an identity-checked UI snapshot, never a guess."""
    def safe(window):
        return window is not None and window.pid != os.getpid() and adapter.validate(window)
    active = adapter.foreground()
    if safe(active):
        return active
    hwnd = context.last_window
    pid = context.data.get('window_pid', context.data.get('last_window_pid'))
    if type(hwnd) is not int or type(pid) is not int:
        return None
    window = adapter.window(hwnd)
    created = context.data.get('last_window_created')
    if not safe(window) or window.pid != pid or (created is not None and window.created != created):
        return None
    return window


class WindowsAdapter:
    def __init__(self, api=None):
        self._api = api

    def _modules(self):
        if self._api is None:
            if sys.platform != 'win32':
                raise NativeUnavailable('Управление окнами требует Windows.')
            import win32gui
            import win32process
            import psutil
            self._api = win32gui, win32process, psutil
        return self._api

    def window(self, hwnd):
        if type(hwnd) is not int or hwnd <= 0:
            return None
        gui, process, psutil = self._modules()
        try:
            if not gui.IsWindow(hwnd) or not gui.IsWindowVisible(hwnd):
                return None
            if gui.GetClassName(hwnd) in SHELL_CLASSES:
                return None
            _, pid = process.GetWindowThreadProcessId(hwnd)
            if pid in (0, 4, os.getpid()):
                return None
            proc = psutil.Process(pid)
            name = proc.name().casefold()
            if name in PROTECTED_PROCESSES:
                return None
            return WindowRef(hwnd, pid, name, gui.GetWindowText(hwnd), proc.create_time(), proc.exe())
        except (OSError, RuntimeError):
            return None
        except Exception as exc:
            # psutil AccessDenied/NoSuchProcess derive from psutil.Error.
            if type(exc).__module__.startswith(('psutil', 'pywintypes')):
                return None
            raise

    def foreground(self):
        return self.window(self._modules()[0].GetForegroundWindow())

    def windows(self, *, include_untitled=False):
        found = []
        def collect(hwnd, _):
            window = self.window(hwnd)
            if window is not None and (include_untitled or window.title):
                found.append(window)
            return True
        self._modules()[0].EnumWindows(collect, None)
        return found

    def validate(self, window):
        if window is None:
            return False
        current = self.window(window.hwnd)
        return (current is not None and current.pid == window.pid
                and current.created == window.created
                and current.process_name == window.process_name
                and current.executable.casefold() == window.executable.casefold())

    def children(self, window):
        self.require(window)
        found = []
        def collect(hwnd, unused):
            child = self.window(hwnd)
            if child is not None:
                found.append(child)
            return True
        self._modules()[0].EnumChildWindows(window.hwnd, collect, None)
        return found

    def require(self, window):
        if not self.validate(window):
            raise ValueError('Window identity is no longer valid')

    def state(self, window):
        self.require(window)
        gui = self._modules()[0]
        if gui.IsIconic(window.hwnd):
            return 'minimized'
        return 'maximized' if gui.GetWindowPlacement(window.hwnd)[1] == 3 else 'normal'

    def show(self, window, action):
        mode = {'minimize': 6, 'maximize': 3, 'restore': 9}[action]
        self.require(window)
        self._modules()[0].ShowWindow(window.hwnd, mode)

    def activate(self, window):
        self.require(window)
        gui = self._modules()[0]
        if gui.IsIconic(window.hwnd):
            gui.ShowWindow(window.hwnd, 9)
        self.require(window)
        gui.SetForegroundWindow(window.hwnd)

    def close(self, window):
        # Engine confirmation precedes this operation. Never terminate/kill.
        self.require(window)
        gui = self._modules()[0]
        if gui.GetClassName(window.hwnd) == 'Windows.UI.Core.CoreWindow':
            # A newly launched UWP CoreWindow may not yet have its frame host.
            # It handles SC_CLOSE, while WM_CLOSE can be silently ignored.
            gui.PostMessage(window.hwnd, 0x0112, 0xF060, 0)
        else:
            gui.PostMessage(window.hwnd, 0x0010, 0, 0)
