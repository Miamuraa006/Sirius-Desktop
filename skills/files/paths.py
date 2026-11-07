"""Local-only path checks used in addition to the core permission policy.

No UNC/device namespace, ADS, traversal, DOS aliases, reparse ancestors or
protected system directories. These checks do not grant user confirmation.
"""
import ntpath
import os
import re
from pathlib import Path, PureWindowsPath


_FORBIDDEN = frozenset({'windows', 'program files', 'program files (x86)',
                        'programdata', 'system volume information', '$recycle.bin',
                        'recovery', 'config.msi'})
_RESERVED = re.compile(r'(?i)(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z')


def _syntax(raw):
    if not isinstance(raw, (str, Path)):
        raise ValueError('Путь должен быть строкой.')
    text = str(raw)
    if not text or text in {'.', '..'} or any(ord(c) < 32 for c in text):
        raise ValueError('Недопустимый путь.')
    if text.startswith(('\\', '/')):
        raise ValueError('Сетевые и неполные абсолютные пути запрещены.')
    drive, tail = ntpath.splitdrive(text)
    if drive and (not re.fullmatch('[A-Za-z]:', drive) or not tail.startswith(('\\', '/'))):
        raise ValueError('Требуется полный локальный путь.')
    if ':' in tail:
        raise ValueError('Альтернативные потоки файлов запрещены.')
    for part in re.split(r'[\\/]', tail):
        if not part:
            continue
        if (part in {'.', '..'} or part.endswith((' ', '.')) or _RESERVED.fullmatch(part)
                or any(c in '<>"|?*' for c in part)):
            raise ValueError('Недопустимый компонент пути.')
    return text


def local_path(raw, *, base=None, allow_root=False):
    """Canonicalise a local path without permitting Windows path aliases."""
    text = _syntax(raw)
    expanded = os.path.expandvars(text)
    text = _syntax(expanded)
    path = Path(text)
    if not PureWindowsPath(text).is_absolute():
        if base is None:
            raise ValueError('Требуется абсолютный локальный путь.')
        path = Path(base) / path
    # Validate every supplied base component as well, not just the relative name.
    _syntax(path)
    for item in (path, *path.parents):
        try:
            if getattr(item.lstat(), 'st_file_attributes', 0) & 0x400 or item.is_symlink():
                raise ValueError('Пути через ссылки и точки повторной обработки запрещены.')
        except FileNotFoundError:
            continue
    path = path.resolve(strict=False)
    _syntax(path)
    if path == Path(path.anchor) and not allow_root:
        raise ValueError('Операция над корнем диска запрещена.')
    if any(part.casefold() in _FORBIDDEN for part in path.parts[1:]):
        raise ValueError('Защищённый системный каталог запрещён.')
    # Also cover non-standard Windows installations configured by the OS.
    for key in ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'):
        configured = os.environ.get(key)
        if configured and path.is_relative_to(Path(configured).resolve()):
            raise ValueError('Защищённый системный каталог запрещён.')
    return path
