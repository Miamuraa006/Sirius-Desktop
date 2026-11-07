"""Application identities and exact aliases shared by skills and settings."""
from dataclasses import dataclass, replace
import os
from pathlib import Path, PureWindowsPath
from skills.windows.native import PROTECTED_PROCESSES


BROWSER_PROCESSES = ('chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe', 'browser.exe')
SAFE_EXECUTABLES = {'notepad.exe', 'calc.exe', 'explorer.exe', 'mspaint.exe'}
# Packaged Windows apps may own the window opened by a System32 launcher.
STOCK_PACKAGES = {
    'calc.exe': ('Microsoft.WindowsCalculator_8wekyb3d8bbwe!App', 'CalculatorApp.exe'),
    'notepad.exe': ('Microsoft.WindowsNotepad_8wekyb3d8bbwe!App', r'Notepad\Notepad.exe'),
    'mspaint.exe': ('Microsoft.Paint_8wekyb3d8bbwe!App', 'PaintApp/mspaint.exe'),
}
COMMAND_INTERPRETERS = {'cmd.exe','powershell.exe','pwsh.exe','wscript.exe','cscript.exe',
                        'mshta.exe','rundll32.exe','regsvr32.exe','python.exe','pythonw.exe',
                        'node.exe','bash.exe','wsl.exe','sh.exe','conhost.exe'}


@dataclass(frozen=True)
class AppSpec:
    name: str
    command: tuple[str, ...]
    process_names: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    companion_paths: tuple[str, ...] = ()
    package_id: str = ''
    url: str = ''
    media_source: str = ''
    play_buttons: tuple[str, ...] = ()
    shell_item: str = ""


DEFAULT_APPS = (
    AppSpec('notepad', ('notepad.exe',), ('notepad.exe',), ('блокнот',)),
    AppSpec('calculator', ('calc.exe',), ('calc.exe','calculator.exe','calculatorapp.exe'), ('калькулятор',)),
    AppSpec('explorer', ('explorer.exe',), ('explorer.exe',), ('проводник',)),
    AppSpec('browser', ('@default-browser',), BROWSER_PROCESSES, ('браузер',)),
)

OPTIONAL_APPS = (
    AppSpec('steam', (r'%ProgramFiles(x86)%\Steam\steam.exe',), ('steam.exe', 'steamwebhelper.exe'),
            ('стим', 'стиим'), (r'bin\cef\cef.win64\steamwebhelper.exe', r'bin\cef\cef.win7x64\steamwebhelper.exe')),
    AppSpec('telegram', (r'%APPDATA%\Telegram Desktop\Telegram.exe',), ('telegram.exe',), ('телеграм',),
            package_id='38833FF26BA1D.UnigramPreview_g9c9v27vpyspw!App'),
    AppSpec('yandex_music', (r'%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe',), ('яндекс музыка.exe',),
            ('яндекс музыка', 'яндекс музыку', 'яндекс.музыка', 'яндекс.музыку', 'yandex music'),
            media_source='ru.yandex.desktop.music', play_buttons=('Воспроизведение Моей волны', 'Воспроизведение')),
    AppSpec('youtube', (), (), ('ютуб',), url='https://www.youtube.com/', media_source='youtube'),
)


def app_registry(config):
    specs = {app.name: app for app in DEFAULT_APPS}
    configured = config.get('applications', {})
    if not isinstance(configured, dict):
        raise ValueError('Invalid application configuration')
    for name, entry in configured.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
            raise ValueError('Invalid app entry')
        command = entry.get('command')
        processes = entry.get('process_names')
        aliases = entry.get('aliases', [])
        if (not isinstance(command, list) or not command or len(command) > 32
                or any(not isinstance(s, str) or not s or any(ord(c) < 32 for c in s) for s in command)):
            raise ValueError('Explicit command array required')
        executable = os.path.expandvars(command[0])
        path = PureWindowsPath(executable)
        basename = path.name.casefold()
        if basename in COMMAND_INTERPRETERS | PROTECTED_PROCESSES:
            raise ValueError('Shells and system processes cannot be registered')
        if path.suffix.casefold() != '.exe' or (not path.is_absolute() and executable.casefold() not in SAFE_EXECUTABLES):
            raise ValueError('Executable must be an absolute EXE or built-in name')
        if path.is_absolute() and (executable.startswith(('\\\\','//')) or not Path(executable).is_file()):
            raise ValueError('Configured executable must exist locally')
        if (not isinstance(processes, list) or not processes
                or any(not isinstance(p,str) or PureWindowsPath(p).name != p or not p.casefold().endswith('.exe')
                       or p.casefold() in COMMAND_INTERPRETERS | PROTECTED_PROCESSES for p in processes)):
            raise ValueError('Explicit safe process names required')
        if not isinstance(aliases, list) or any(not isinstance(a,str) or not a.strip() for a in aliases):
            raise ValueError('Invalid aliases')
        key = name.strip().casefold()
        specs[key] = AppSpec(key, (executable, *command[1:]), tuple(p.casefold() for p in processes), tuple(a.strip().casefold() for a in aliases))
    aliases = {}
    for spec in specs.values():
        for name in (spec.name, *spec.aliases):
            if name in aliases and aliases[name].name != spec.name:
                raise ValueError('Ambiguous application alias')
            aliases[name] = spec
    for default in OPTIONAL_APPS:
        # Previously valid user entries own their names and aliases, including new built-in names.
        spec = aliases.get(default.name, replace(default, aliases=()))
        if spec.name != default.name:
            continue
        available = tuple(alias for alias in default.aliases if alias not in aliases)
        companions = spec.companion_paths
        if (default.companion_paths and spec.command and
                PureWindowsPath(spec.command[0]).name.casefold() == PureWindowsPath(default.command[0]).name.casefold()):
            companions = default.companion_paths
        spec = replace(spec, aliases=(*spec.aliases, *available),
                       companion_paths=companions)
        for name in (spec.name, *spec.aliases):
            aliases[name] = spec
    return aliases
