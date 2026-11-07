"""Local file operations; all success messages follow filesystem readback."""
from pathlib import Path

from .paths import local_path


class WindowsFileAdapter:
    @staticmethod
    def mkdir(path):
        path.mkdir(parents=True, exist_ok=False)

    @staticmethod
    def touch(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb'):
            pass
    @staticmethod
    def move(path, destination):
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        api.MoveFileExW.restype = wintypes.BOOL
        # COPY_ALLOWED for cross-volume files; never REPLACE_EXISTING.
        if not api.MoveFileExW(str(path), str(destination), 2):
            raise ctypes.WinError(ctypes.get_last_error())

    @staticmethod
    def trash(path):
        from send2trash import send2trash
        send2trash(str(path))

    @staticmethod
    def open(path):
        import time
        import pythoncom
        import win32com.client
        import win32gui
        import win32process
        from win32com.shell import shell, shellcon
        pythoncom.CoInitialize()
        process = None
        try:
            if path.is_dir():
                explorer = win32com.client.Dispatch('Shell.Application')
                explorer.Open(str(path))
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline:
                    for window in explorer.Windows():
                        try:
                            actual = Path(window.Document.Folder.Self.Path).resolve()
                            if actual == path:
                                return True
                        except (AttributeError, OSError, pythoncom.com_error):
                            continue
                    time.sleep(0.05)
                return False
            launched = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
                                            lpVerb='open', lpFile=str(path), nShow=1)
            process = launched.get('hProcess')
            if not process:
                # Existing singleton applications may not provide an observable PID.
                return False
            pid = win32process.GetProcessId(process)
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                matches = []
                def observe(hwnd, unused):
                    if (win32gui.IsWindowVisible(hwnd)
                            and win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                            and path.name.casefold() in win32gui.GetWindowText(hwnd).casefold()):
                        matches.append(hwnd)
                win32gui.EnumWindows(observe, None)
                if matches:
                    return True
                time.sleep(0.05)
            return False
        finally:
            if process:
                process.Close()
            pythoncom.CoUninitialize()


class Handler:
    ACTIONS = frozenset({'mkdir', 'touch', 'open', 'rename', 'move', 'trash'})

    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsFileAdapter()
        self.config = config or {}

    def execute(self, intent, context):
        from core.models import Result
        if intent.skill != 'files' or intent.action not in self.ACTIONS:
            return Result.fail('Неизвестная файловая операция.')
        try:
            settings = self.config.get('files', {})
            root = local_path(settings.get('root', str(Path.home() / 'Documents' / 'Sirius')))
            path = local_path(intent.parameters.get('path'), base=root)
            roots = [root, *(local_path(p) for p in settings.get('allowed_roots', []))]
            if path in roots and intent.action != 'open':
                raise ValueError('Нельзя изменять корень доверенного каталога.')
            destination = None
            if intent.action in {'rename', 'move'}:
                destination = local_path(intent.parameters.get('destination'), base=root)
                if destination in roots or destination == path or destination.is_relative_to(path):
                    raise ValueError('Недопустимая цель перемещения.')
                if destination.exists():
                    raise ValueError('Цель уже существует; перезапись запрещена.')
            from security.permissions import trusted_root
            source_root = trusted_root(path,roots)
            target_root = trusted_root(destination,roots) if destination else source_root
            requires_grant = (intent.action == 'trash' or source_root is None
                              or target_root is None or source_root != target_root)
            grant = getattr(context, 'data', {}).pop('file_grant', None)
            expected = tuple(str(p) for p in (path, destination) if p is not None)
            if requires_grant and grant != expected:
                return Result('needs_confirmation', 'Требуется подтверждение ядра для операции с файлом.',
                              details={'action': intent.action, 'paths': list(expected)})
            if intent.action in {'mkdir', 'touch'}:
                if path.exists():
                    raise ValueError('Объект уже существует; перезапись запрещена.')
                if intent.action == 'touch' and path.suffix.casefold() != '.txt':
                    raise ValueError('Можно создать только пустой файл .txt.')
                getattr(self.adapter, intent.action)(path)
                # Revalidate after the call as well, including reparse ancestors.
                local_path(path)
                verified = path.is_dir() if intent.action == 'mkdir' else path.is_file() and path.stat().st_size == 0
                if not verified:
                    return Result.fail('Создание не подтверждено файловой системой.')
                return Result.ok('Папка создана.' if intent.action == 'mkdir' else 'Пустой TXT-файл создан.', path=str(path))
            if not path.exists():
                raise ValueError('Файл или папка не найдены.')
            if intent.action in {'rename', 'move'}:
                if not destination.parent.is_dir():
                    raise ValueError('Папка назначения не существует.')
                source_stat = path.stat()
                was_file = path.is_file()
                self.adapter.move(path, destination)
                local_path(destination)
                verified = not path.exists() and destination.exists()
                if verified and was_file:
                    verified = destination.is_file() and destination.stat().st_size == source_stat.st_size
                if not verified:
                    return Result.fail('Перемещение не подтверждено файловой системой.')
                return Result.ok('Файл или папка перемещены.' if intent.action == 'move' else 'Имя изменено.', path=str(destination))
            if intent.action == 'trash':
                self.adapter.trash(path)
                if path.exists():
                    return Result.fail('Отправка в корзину не подтверждена.')
                return Result.ok('Объект отправлен в корзину Windows.', path=str(path))
            if intent.action == 'open':
                safe_documents = {'.txt', '.md', '.pdf', '.png', '.jpg', '.jpeg', '.bmp',
                                  '.gif', '.webp', '.mp3', '.mp4', '.wav', '.flac', '.ogg',
                                  '.docx', '.xlsx', '.pptx', '.csv', '.rtf'}
                if not path.is_dir() and path.suffix.casefold() not in safe_documents:
                    raise ValueError('Открытие исполняемых файлов и сценариев запрещено.')
                if self.adapter.open(path) is not True:
                    return Result.unsupported('Команда открытия отправлена, но приложение не подтвердило открытый документ.')
                return Result.ok('Файл или папка открыты.', path=str(path))
            return Result.fail('Неизвестная файловая операция.')
        except ValueError as exc:
            return Result.fail(str(exc))
        except (OSError, TypeError, AttributeError):
            return Result.fail('Не удалось выполнить файловую операцию. Проверьте путь и доступ.')
