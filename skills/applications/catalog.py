"""Exact-name discovery from Windows AppsFolder and current visible application windows."""
import os
from pathlib import Path
import time
from threading import Lock
from xml.etree import ElementTree

from skills.applications.registry import AppSpec, COMMAND_INTERPRETERS, app_registry
from skills.windows.native import PROTECTED_PROCESSES, WindowsAdapter

_cache = {}
_until = 0.
_lock = Lock()
ALIASES = {'чат гпт': 'chatgpt', 'чат джипити': 'chatgpt', 'гугл хром': 'google chrome',
           'кс два': 'counter-strike 2', 'кс 2': 'counter-strike 2', 'кс2': 'counter-strike 2',
           'cs2': 'counter-strike 2', 'counter-strike': 'counter-strike 2', 'контр страйк': 'counter-strike 2',
           'каунтер страйк': 'counter-strike 2', 'контр страйк два': 'counter-strike 2'}
CS2_NAMES = {
    'counter strike', 'counter strike 2', 'counter-strike 2', 'каунтер страйк два',
    'игровой режим', 'режим игры', 'режим реградаций', 'режим реградации', 'режим деградации',
    *(f'{base} {number}' for base in ('каэс', 'каес', 'ка эс', 'ка ес', 'кс', 'к с')
      for number in ('2', 'два')),
}
ALIASES.update(dict.fromkeys(CS2_NAMES, 'counter-strike 2'))


def protected(name):
    folded = name.casefold().replace(' ', '')
    return ('parkcontrol' in folded or 'nvidia' in folded or folded.startswith(('nvcontainer', 'nvcpl', 'nvdisplay')))


def _read_installed():
    import pythoncom
    from win32com.client import Dispatch
    found = {}
    pythoncom.CoInitialize()
    try:
        for item in Dispatch('Shell.Application').NameSpace('shell:AppsFolder').Items():
            try:
                name, identity = item.Name.strip(), item.Path
                if not name or protected(name) or any(v in name.casefold() for v in ('uninstall', 'деинстал', 'удаление')):
                    continue
                path = Path(item.ExtendedProperty('System.Link.TargetParsingPath') or '')
                if item.ExtendedProperty('System.Link.Arguments'):
                    continue  # A shortcut with arguments can share its host process with another app.
                root = item.ExtendedProperty('System.AppUserModel.PackageInstallPath')
                if root and '!' in identity:
                    manifest = ElementTree.parse(Path(root) / 'AppxManifest.xml')
                    entry = next((e for e in manifest.findall('.//{*}Applications/{*}Application')
                                  if e.get('Id') == identity.split('!', 1)[1]), None)
                    if entry is not None:
                        path = Path(root) / entry.get('Executable', '')
                if (not path.is_absolute() or path.suffix.casefold() != '.exe' or not path.is_file()
                        or path.name.casefold() in COMMAND_INTERPRETERS | PROTECTED_PROCESSES or protected(path.name)):
                    continue
                spec = AppSpec(name, (str(path),), (path.name.casefold(),), shell_item=identity)
                key = name.casefold()
                if key not in found or found[key] == spec:
                    found[key] = spec
                else:
                    found[key] = None
            except (OSError, ValueError, ElementTree.ParseError):
                continue
    finally:
        pythoncom.CoUninitialize()
    return found


def installed_catalog():
    global _until, _cache
    with _lock:
        if time.monotonic() >= _until:
            _cache = _read_installed()
            _until = time.monotonic() + 60
        return _cache


def steam_directory():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as reg:
            path = Path(winreg.QueryValueEx(reg, 'SteamPath')[0])
            return path if path.is_absolute() else None
    except OSError:
        return None


def installed_cs2():
    """Only the CS2 binary inside a local Steam library can trigger game mode."""
    import re
    steam = steam_directory()
    if steam is None:
        return None
    try:
        libs = (steam / 'steamapps/libraryfolders.vdf').read_text('utf-8', errors='replace')
    except OSError:
        libs = ''
    for library in [steam, *(Path(v.replace(chr(92)*2, chr(92))) for v in re.findall(r'"path"\s*"([^"]+)"', libs))]:
        game = library / 'steamapps/common/Counter-Strike Global Offensive/game/bin/win64/cs2.exe'
        if library.is_absolute() and game.is_file():
            return AppSpec('Counter-Strike 2', (str(game),), ('cs2.exe',), shell_item='steam://rungameid/730')
    return None


def resolve_app(name, config):
    key = name.strip().casefold()
    spec = app_registry(config).get(key)
    if spec:
        return spec
    key = ALIASES.get(key, key)
    if protected(key) or os.name != 'nt':
        return None
    if key == 'counter-strike 2':
        return installed_cs2()
    catalog = installed_catalog()
    if key in catalog:
        return catalog[key]
    paths = {Path(w.executable) for w in WindowsAdapter().windows()
             if Path(w.executable).stem.casefold() == key and w.process_name not in PROTECTED_PROCESSES | COMMAND_INTERPRETERS}
    if len(paths) == 1:
        path = paths.pop()
        return AppSpec(path.stem, (str(path),), (path.name.casefold(),))
    return None

def taskbar_labels(tray=False):
    import win32gui
    from skills.windows.automation import UIAutomation
    classes = ('Shell_TrayWnd', 'NotifyIconOverflowWindow', 'TopLevelWindowForOverflowXamlIsland') if tray else ('Shell_TrayWnd',)
    labels = []
    with UIAutomation() as api:
        opener = None
        if tray and not any(win32gui.IsWindowVisible(win32gui.FindWindow(cls, None)) for cls in classes[1:]):
            bar = api.api.ElementFromHandle(win32gui.FindWindow('Shell_TrayWnd', None))
            buttons = bar.FindAll(4, api.api.CreatePropertyCondition(30003, 50000))
            for index in range(buttons.Length):
                el = buttons.GetElement(index)
                if (el.CurrentName or '').casefold() in {'показать скрытые значки', 'show hidden icons'}:
                    pattern = api.pattern(el, 10000, 'IUIAutomationInvokePattern')
                    if pattern:
                        pattern.Invoke()
                        opener = pattern
                        for _ in range(12):
                            if any(win32gui.IsWindowVisible(win32gui.FindWindow(cls, None)) for cls in classes[1:]):
                                break
                            time.sleep(.05)
                    break
        try:
            for cls in classes:
                hwnd = win32gui.FindWindow(cls, None)
                if not hwnd:
                    continue
                root = api.api.ElementFromHandle(hwnd)
                buttons = root.FindAll(4, api.api.CreatePropertyCondition(30003, 50000))
                for index in range(buttons.Length):
                    el = buttons.GetElement(index)
                    if cls == 'Shell_TrayWnd':
                        wanted = ((el.CurrentClassName or '').startswith('SystemTray.NotifyIcon') if tray else
                                  (el.CurrentAutomationId or '').startswith('Appid:'))
                        if not wanted:
                            continue
                    label = (el.CurrentName or '').splitlines()
                    if label and label[0] not in labels:
                        labels.append(label[0])
        finally:
            if opener and any(win32gui.IsWindowVisible(win32gui.FindWindow(cls, None)) for cls in classes[1:]):
                opener.Invoke()
    return labels
