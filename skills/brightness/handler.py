"""Brightness migrated from legacy normal/brightness.py.

Preserves clamped relative arithmetic; replaces the legacy first-list-element
and unverified global write with one selected display and explicit readback.
"""
from contextlib import contextmanager
import sys
import time
from core.models import Result


class DisplayUnavailable(RuntimeError):
    """The hardware does not expose a brightness control."""


class Display:
    def __init__(self, library, identifier):
        self.library, self.identifier = library, identifier

    def get_level(self):
        levels = self.library.get_brightness(display=self.identifier)
        if not levels or len(levels) != 1 or levels[0] is None:
            raise DisplayUnavailable('Дисплей не предоставляет значение яркости.')
        value = levels[0]
        if type(value) not in (int, float) or not 0 <= value <= 100:
            raise ValueError('Invalid brightness readback')
        return round(value)

    def set_level(self, value):
        self.library.set_brightness(value, display=self.identifier)


class WindowsBrightnessAdapter:
    def __init__(self, display=0):
        self.display = display

    @contextmanager
    def session(self):
        if sys.platform != 'win32':
            raise DisplayUnavailable('Управление яркостью требует Windows.')
        import comtypes
        comtypes.CoInitialize()
        try:
            import screen_brightness_control as sbc
            if type(self.display) is not int or self.display < 0:
                raise ValueError('brightness.display must be a nonnegative index')
            monitors = sbc.list_monitors_info()
            if self.display >= len(monitors):
                raise DisplayUnavailable('Поддерживаемый дисплей не найден; проверьте WMI/DDC/CI.')
            info = monitors[self.display]
            identifier = info.get('serial') or info.get('edid') or self.display
            yield Display(sbc, identifier)
        finally:
            comtypes.CoUninitialize()


class Handler:
    def __init__(self, adapter=None, config=None):
        display = (config or {}).get('brightness', {}).get('display', 0)
        self.adapter = adapter if adapter is not None else WindowsBrightnessAdapter(display)

    def execute(self, intent, context):
        if intent.action not in {'set', 'adjust'}:
            return Result.fail('Неизвестное действие с яркостью.')
        value = intent.parameters.get('value' if intent.action == 'set' else 'delta')
        if type(value) is not int:
            return Result.fail('Яркость и шаг должны быть целыми числами.')
        try:
            with self.adapter.session() as display:
                desired = value if intent.action == 'set' else display.get_level() + value
                desired = max(0, min(100, desired))
                display.set_level(desired)
                actual = display.get_level()
                deadline = time.monotonic() + 0.6
                while actual != desired and time.monotonic() < deadline:
                    time.sleep(0.05)
                    actual = display.get_level()
                if type(actual) not in (int, float) or actual != desired:
                    return Result.fail('Дисплей не подтвердил изменение яркости.')
                return Result.ok(f'Яркость: {actual}%.', value=actual)
        except DisplayUnavailable as exc:
            return Result.unsupported(str(exc))
        except Exception:
            return Result.fail('Не удалось прочитать или изменить яркость через WMI/DDC/CI.')
