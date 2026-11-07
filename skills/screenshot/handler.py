"""On-demand local PNG capture, exclusive creation and decoded pixel readback."""
from datetime import datetime
from pathlib import Path
import os
import sys
from uuid import uuid4

from core.models import Result
from skills.files.paths import local_path
from skills.windows.native import WindowsAdapter, NativeUnavailable, context_target


class WindowsScreenshotAdapter:
    def __init__(self, windows=None, grab=None):
        self.windows = windows if windows is not None else WindowsAdapter()
        self.grab = grab

    def target(self, context):
        return context_target(self.windows, context)

    def capture(self, window=None):
        if sys.platform != 'win32':
            raise NativeUnavailable('Снимки экрана требуют Windows.')
        from PIL import ImageGrab
        grab = self.grab or ImageGrab.grab
        if window is None:
            return grab(all_screens=True)
        self.windows.require(window)
        if self.windows.state(window) == 'minimized':
            raise NativeUnavailable('Разверните целевое окно перед снимком.')
        image = grab(window=window.hwnd)
        try:
            self.windows.require(window)
        except Exception:
            image.close()
            raise
        return image


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsScreenshotAdapter()
        self.config = config or {}

    def execute(self, intent, context):
        if intent.skill != 'screenshot' or intent.action not in {'full', 'window'}:
            return Result.fail('Неизвестный вид снимка экрана.')
        path = None
        created = False
        image = None
        try:
            window = None
            if intent.action == 'window':
                window = self.adapter.target(context)
                if window is None:
                    return Result.fail('Активное внешнее окно не определено; снимок не сделан.')
            settings = self.config.get('screenshot', {})
            directory = local_path(settings.get('directory', str(Path.home() / 'Pictures' / 'Sirius Screenshots')))
            directory.mkdir(parents=True, exist_ok=True)
            local_path(directory)
            image = self.adapter.capture(window)
            if min(image.size) <= 0:
                raise ValueError('Empty capture')
            path = directory / (datetime.now().strftime('Sirius_%Y%m%d_%H%M%S_') + uuid4().hex + '.png')
            with path.open('xb') as stream:
                created = True
                image.save(stream, format='PNG')
                stream.flush()
                os.fsync(stream.fileno())
            from PIL import Image
            local_path(path)
            with Image.open(path) as observed:
                observed.load()
                if observed.format != 'PNG' or observed.size != image.size or observed.convert('RGB').tobytes() != image.convert('RGB').tobytes():
                    raise ValueError('Capture readback mismatch')
            return Result.ok('Снимок сохранён и проверен.', path=str(path), width=image.size[0], height=image.size[1])
        except NativeUnavailable as exc:
            return Result.unsupported(str(exc))
        except Exception:
            if created and path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            return Result.fail('Не удалось сделать или проверить снимок экрана.')
        finally:
            if image is not None:
                image.close()
