"""Release desktop applications once a verified local CS2 window is open."""
import logging
import os
from pathlib import Path

import psutil

from skills.applications.catalog import installed_catalog, installed_cs2, protected, steam_directory
from skills.applications.handler import WindowsApplicationAdapter
from skills.applications.registry import AppSpec, COMMAND_INTERPRETERS, app_registry
from skills.windows.native import PROTECTED_PROCESSES

LOG = logging.getLogger(__name__)
KEEP_NAMES = PROTECTED_PROCESSES | COMMAND_INTERPRETERS | {
    'cs2.exe', 'steam.exe', 'steamservice.exe', 'steamwebhelper.exe', 'gameoverlayui.exe',
    'sirius.exe', 'explorer.exe', 'applicationframehost.exe', 'msedgewebview2.exe',
    'securityhealthsystray.exe', 'sechealthui.exe',
}


def eligible(path, game_dir, windows_dir, steam_dir):
    name = path.name.casefold()
    if not path.is_absolute() or path.suffix.casefold() != '.exe' or name in KEEP_NAMES:
        return False
    if (path.is_relative_to(game_dir) or (steam_dir and path.is_relative_to(steam_dir))
            or protected(str(path)) or protected(name)):
        return False
    if any(part.casefold() in {'steam', 'steamapps', 'steamclient', 'bitsum', 'sirius',
                               'windows defender', 'windows defender advanced threat protection'}
           for part in path.parts):
        return False
    if path.is_relative_to(windows_dir):
        return ((path.parent == windows_dir / 'System32' and name in {'notepad.exe', 'mspaint.exe'})
                or path == windows_dir / 'ImmersiveControlPanel/SystemSettings.exe')
    return True


def desktop_targets(adapter, config, game):
    """Snapshot exact executable paths, process identities and the interactive session."""
    import win32ts
    import pywintypes
    visible = {w.pid: Path(w.executable) for w in adapter.windows.windows()}
    known = set()
    try:
        specs = [*app_registry(config).values(), *installed_catalog().values()]
    except Exception as exc:
        LOG.warning('Game mode: application catalog unavailable (%s)', type(exc).__name__)
        specs = app_registry({}).values()
    for spec in specs:
        if spec and spec.command and not spec.url:
            known.add(Path(os.path.expandvars(spec.command[0])))
    game_dir = Path(game.command[0]).parents[3]
    windows_dir = Path(os.environ['SystemRoot'])
    steam_dir = steam_directory()
    eligible_paths = {p for p in known.union(visible.values()) if eligible(p, game_dir, windows_dir, steam_dir)}
    names = {path.name.casefold() for path in eligible_paths}
    current = psutil.Process()
    exclude = {current.pid, *(p.pid for p in current.parents())}
    user = current.username()
    session = win32ts.ProcessIdToSessionId(current.pid)
    targets = {}
    for proc in psutil.process_iter(['name']):
        if proc.pid in exclude or (proc.info['name'] or '').casefold() not in names:
            continue
        try:
            path = Path(proc.exe())
            if (path in eligible_paths and (path in known or visible.get(proc.pid) == path)
                    and proc.username() == user and win32ts.ProcessIdToSessionId(proc.pid) == session
                    and proc.is_running()):
                targets.setdefault(path, {})[proc.pid] = (proc, proc.create_time())
        except (psutil.Error, OSError, pywintypes.error):
            continue
    return targets


def own_windows(adapter, spec, processes):
    windows = []
    for window in adapter.find_windows(spec, include_untitled=True):
        owner = getattr(window, 'content', None) or window
        entry = processes.get(owner.pid)
        if entry and entry[1] == owner.created:
            windows.append(window)
    return windows


def prompting(window):
    import win32gui
    # Leave existing modal dialogs and their disabled owners for the user.
    return win32gui.GetClassName(window.hwnd) == '#32770' or not win32gui.IsWindowEnabled(window.hwnd)


def release_apps(adapter, targets, active, stop):
    pending = []
    for path, processes in targets.items():
        if not active():
            return False
        spec = AppSpec(path.stem, (str(path),), (path.name.casefold(),))
        try:
            windows = own_windows(adapter, spec, processes)
            if any(prompting(w) for w in windows):
                LOG.info('Game mode: waiting for user in %s', path.name)
                continue
            for window in windows:
                if not active():
                    return False
                adapter.close(window)
            pending.append((path, spec, processes))
        except Exception as exc:
            LOG.info('Game mode: skipped %s (%s)', path.name, type(exc).__name__)
    # Give all applications a shared grace period to save, quit or show a dialog.
    if pending and stop.wait(3):
        return False
    terminated = []
    for path, spec, processes in pending:
        for proc, created in processes.values():
            try:
                if not active():
                    return False
                if own_windows(adapter, spec, processes):
                    LOG.info('Game mode: %s still has a window; leaving it open', path.name)
                    break
                if proc.is_running() and proc.create_time() == created and Path(proc.exe()) == path:
                    proc.terminate()
                    terminated.append(proc)
            except (psutil.NoSuchProcess, ProcessLookupError):
                continue
            except Exception as exc:
                LOG.info('Game mode: skipped %s (%s)', path.name, type(exc).__name__)
    if terminated:
        _, alive = psutil.wait_procs(terminated, timeout=2)
        if alive:
            LOG.info('Game mode: %d processes still exiting', len(alive))
    return active()


def watch_game(config, stop, finished):
    adapter = WindowsApplicationAdapter()
    while not stop.wait(2):
        try:
            if not any((p.info['name'] or '').lower() == 'cs2.exe' for p in psutil.process_iter(['name'])):
                continue
            spec = installed_cs2()
            windows = adapter.find_windows(spec) if spec else []
            if not windows:
                continue
            game_window = windows[0]
            def active():
                return not stop.is_set() and adapter.validate(game_window)
            if active() and release_apps(adapter, desktop_targets(adapter, config, spec), active, stop):
                LOG.info('Game mode: CS2 is ready, exiting Sirius')
                finished()
                return
        except Exception as exc:
            LOG.warning('Game mode: observer unavailable (%s)', type(exc).__name__)
