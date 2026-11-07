"""Registered Windows apps; migrated allowlist from legacy lite/open_app.py.

Discarded unsafe terminate loop from lite/close_app.py. Windows are identified
by HWND/PID/start time, soft-closed, and verified; no spoken command arguments.
"""
from dataclasses import dataclass, replace
from pathlib import Path
import os
import subprocess
import sys
from skills.windows.native import WindowsAdapter, WindowRef, NativeUnavailable, PROTECTED_PROCESSES, focus_window
from skills.applications.registry import (
    AppSpec, DEFAULT_APPS, app_registry, BROWSER_PROCESSES, COMMAND_INTERPRETERS, SAFE_EXECUTABLES, STOCK_PACKAGES,
)
from skills.applications.manager import ApplicationManager
from skills.applications.web_target import WebTab, WebTargets


@dataclass(frozen=True)
class HostedWindow(WindowRef):
    content: WindowRef | None = None


class WindowsApplicationAdapter:
    """Allowlisted EXE launch and identity-checked, non-destructive WM_CLOSE."""

    def __init__(self, windows=None):
        self.windows = windows if windows is not None else WindowsAdapter()
        self.web = WebTargets(self.windows)

    @staticmethod
    def _package_executable(app_id, filename):
        # Resolve the installed package through Windows, independent of its version.
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        try:
            item = Dispatch('Shell.Application').NameSpace('shell:AppsFolder').ParseName(app_id)
            if item and item.ExtendedProperty('System.AppUserModel.ID') == app_id:
                root = item.ExtendedProperty('System.AppUserModel.PackageInstallPath')
                if root:
                    path = Path(root) / filename
                    if path.is_absolute() and path.is_file():
                        return str(path)
        finally:
            pythoncom.CoUninitialize()
        return None

    def prepare(self, spec):
        if spec.url or spec.shell_item:
            return spec
        if spec.command == ('@default-browser',):
            path = self.default_browser()
            return replace(spec, command=(path,), process_names=(Path(path).name.casefold(),))
        path = Path(os.path.expandvars(spec.command[0]))
        if not path.is_absolute():
            executable = self._executable(str(path))
            package = STOCK_PACKAGES.get(str(path).casefold())
            owner = self._package_executable(*package) if package else None
            return replace(spec, command=(executable, *spec.command[1:]),
                           companion_paths=(owner,) if owner else ())
        if spec.name == 'yandex_music' and spec.media_source and not path.is_file():
            return replace(spec, url='https://music.yandex.ru/')
        if spec.package_id and not path.is_file():
            package_exe = self._package_executable(spec.package_id, path.name)
            if package_exe:
                return replace(spec, command=(package_exe,))
        return replace(spec, command=(str(path), *spec.command[1:]), package_id='')

    @staticmethod
    def _executable(token):
        path = Path(os.path.expandvars(token))
        basename = path.name.casefold()
        if basename in COMMAND_INTERPRETERS | PROTECTED_PROCESSES:
            raise ValueError('Unsafe executable')
        if not path.is_absolute():
            if token.casefold() not in SAFE_EXECUTABLES:
                raise ValueError('Executable is not allowlisted')
            path = Path(os.environ.get('SystemRoot', 'C:/Windows')) / ('explorer.exe' if basename == 'explorer.exe' else 'System32/' + basename)
        if path.suffix.casefold() != '.exe' or str(path).startswith(('\\\\', '//')) or not path.is_file():
            raise ValueError('Local executable is unavailable')
        return str(path)

    @staticmethod
    def default_browser():
        import ctypes
        from ctypes import wintypes
        dll = ctypes.WinDLL('shlwapi', use_last_error=True)
        query = dll.AssocQueryStringW
        query.argtypes = [wintypes.DWORD, ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR,
                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = ctypes.c_long
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        # Ask Windows for the executable, not an interpolated shell command.
        if query(0x1000, 2, 'https', 'open', buffer, ctypes.byref(size)) != 0:
            raise NativeUnavailable('Windows не сообщает установленный браузер по умолчанию.')
        path = Path(buffer.value)
        if not path.is_absolute() or path.name.casefold() not in BROWSER_PROCESSES:
            raise NativeUnavailable('Браузер по умолчанию не поддерживается; зарегистрируйте его явно.')
        return WindowsApplicationAdapter._executable(str(path))

    def launch(self, spec):
        if sys.platform != 'win32':
            raise NativeUnavailable('Запуск приложений требует Windows.')
        if spec.shell_item:
            if spec.shell_item == 'steam://rungameid/730':
                os.startfile(spec.shell_item)
            else:
                os.startfile('shell:AppsFolder' + chr(92) + spec.shell_item)
            return
        if spec.package_id:
            os.startfile('shell:AppsFolder\\' + spec.package_id)
            return
        if spec.url:
            argv = [self.default_browser(), spec.url]
        elif spec.command == ('@default-browser',):
            argv = [self.default_browser()]
        else:
            if Path(spec.command[0]).is_absolute() and not Path(spec.command[0]).is_file():
                raise NativeUnavailable(f'Не найден файл {spec.command[0]}. Проверьте путь в config.json.')
            argv = [self._executable(spec.command[0]), *spec.command[1:]]
        # Never resolve a free-speech token through PATH or a command interpreter.
        subprocess.Popen(argv, shell=False, close_fds=True)

    def find_windows(self, spec, *, include_untitled=False):
        if spec.url:
            targets = []
            for window in self.windows.windows():
                if window.process_name in BROWSER_PROCESSES:
                    tab = self.web.identify(window, spec.url)
                    if tab is not None:
                        targets.append(tab)
            return targets
        exe = Path(spec.command[0])
        paths = {exe, *(exe.parent / relative for relative in spec.companion_paths)} if exe.is_absolute() else set()
        result = []
        visible = self.windows.windows(include_untitled=True) if include_untitled else self.windows.windows()
        for window in visible:
            identity = window
            if window.process_name == 'applicationframehost.exe':
                # Windows 10 UWP windows are owned by a host; identify the real app child.
                try:
                    children = [child for child in self.windows.children(window)
                                if child.process_name in spec.process_names and self.windows.validate(child)]
                except ValueError:
                    # An unrelated UWP host may disappear during enumeration.
                    # It must not abort observation of the application we launched.
                    continue
                if len({(child.pid, child.created) for child in children}) != 1:
                    continue
                identity = children[0]
                window = HostedWindow(window.hwnd, window.pid, window.process_name,
                                      window.title, window.created, window.executable, identity)
            if identity.process_name.casefold() not in spec.process_names or not self.validate(window):
                continue
            if paths and Path(identity.executable) not in paths:
                continue
            result.append(window)
        return result

    def existing_player(self, spec):
        native = [] if spec.url else self.find_windows(spec)
        if native:
            return native[0]
        sites = {'youtube': ('https://www.youtube.com/',),
                 'yandex_music': ('https://music.yandex.ru/', 'https://music.yandex.com/')}
        return self.web.locate(self.windows.windows(), sites.get(spec.name, ()), spec.name)

    def validate(self, window):
        if not self.windows.validate(window):
            return False
        if isinstance(window, WebTab):
            return self.web.validate(window)
        content = getattr(window, 'content', None)
        return content is None or (self.windows.validate(content) and content in self.windows.children(window))

    def focus(self, window):
        return focus_window(self.windows, window, self.validate)

    def background_processes(self, spec):
        from skills.applications.catalog import protected
        import psutil
        if spec.url or not spec.command or protected(spec.name):
            return []
        path = Path(spec.command[0])
        if not path.is_absolute() or protected(str(path)) or path.is_relative_to(Path(os.environ['SystemRoot'])):
            return []
        own = {p.pid for p in psutil.Process().parents()} | {os.getpid()}
        found = []
        for proc in psutil.process_iter(['pid', 'exe']):
            exe = proc.info['exe']
            if exe and proc.pid not in own and Path(exe) == path and path.name.casefold() not in PROTECTED_PROCESSES | COMMAND_INTERPRETERS:
                found.append(proc)
        return found

    def finish_background(self, spec, processes):
        import psutil
        for proc in processes:
            try:
                if self.find_windows(spec):
                    return False
                if proc.is_running() and Path(proc.exe()) == Path(spec.command[0]):
                    proc.terminate()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                return False
        _, alive = psutil.wait_procs(processes, timeout=2)
        return not alive and not self.background_processes(spec)

    def close(self, window):
        from skills.applications.catalog import protected
        if protected(window.process_name) or protected(window.executable):
            raise NativeUnavailable('Эта программа защищена от закрытия.')
        if not self.validate(window):
            raise ValueError('Application window identity changed')
        if isinstance(window, WebTab):
            self.web.close(window)
        else:
            self.windows.close(window)


class Handler(ApplicationManager):
    def __init__(self, adapter=None, config=None):
        super().__init__(adapter if adapter is not None else WindowsApplicationAdapter(), config)
