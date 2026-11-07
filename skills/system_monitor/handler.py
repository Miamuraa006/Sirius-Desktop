"""System counters obtained from psutil, never estimated or synthesised."""
import math
import os
from pathlib import Path


class SensorUnavailable(RuntimeError):
    """No supported native sensor exists on this device."""


class WindowsMonitorAdapter:
    def __init__(self, native=None):
        self._native = native

    @property
    def native(self):
        if self._native is None:
            import psutil
            self._native = psutil
        return self._native

    def read(self, action, path=None):
        if action == 'cpu':
            return {'percent': self.native.cpu_percent(interval=0.15)}
        if action == 'ram':
            value = self.native.virtual_memory()
            return {key: getattr(value, key) for key in ('percent', 'used', 'available', 'total')}
        if action == 'disk':
            value = self.native.disk_usage(str(path))
            return {key: getattr(value, key) for key in ('percent', 'used', 'free', 'total')}
        if action == 'battery':
            value = self.native.sensors_battery()
            if value is None:
                raise SensorUnavailable('Аккумулятор не найден или датчик недоступен.')
            return {'percent': value.percent, 'power_plugged': value.power_plugged,
                    'seconds_left': value.secsleft if value.secsleft >= 0 else None}
        if action == 'temperature':
            sensor = getattr(self.native, 'sensors_temperatures', None)
            if sensor is None:
                raise SensorUnavailable('Windows не предоставляет доступный датчик температуры.')
            readings = [entry.current for group in sensor().values() for entry in group
                        if isinstance(entry.current, (int, float)) and math.isfinite(entry.current)]
            if not readings:
                raise SensorUnavailable('Датчик температуры недоступен.')
            return {'celsius': max(readings), 'sensors': len(readings)}
        raise ValueError('Неизвестный системный показатель.')


class Handler:
    ACTIONS = frozenset({'cpu', 'ram', 'disk', 'battery', 'temperature'})

    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsMonitorAdapter()
        self.config = config or {}

    def execute(self, intent, context):
        from core.models import Result
        if intent.skill != 'system_monitor' or intent.action not in self.ACTIONS:
            return Result.fail('Неизвестный системный показатель.')
        try:
            path = Path(os.environ.get('SystemDrive', Path.home().drive or 'C:') + '/')
            data = self.adapter.read(intent.action, path)
            if not isinstance(data, dict):
                raise ValueError('Недопустимый ответ датчика.')
            if intent.action != 'temperature':
                percent = data['percent']
                if (isinstance(percent, bool) or not isinstance(percent, (int, float))
                        or not math.isfinite(percent) or not 0 <= percent <= 100):
                    raise ValueError('Недопустимое показание датчика.')
            if intent.action == 'cpu':
                message = f'Загрузка CPU: {percent:.1f}%.'
            elif intent.action == 'ram':
                message = f'Занято RAM: {percent:.1f}%, доступно {data["available"] / 1024**3:.2f} ГБ.'
            elif intent.action == 'disk':
                message = f'Свободно на диске {path.drive} {data["free"] / 1024**3:.2f} ГБ.'
            elif intent.action == 'battery':
                message = f'Заряд батареи: {percent:.1f}%, ' + ('питание от сети.' if data['power_plugged'] else 'питание от батареи.')
            else:
                if not math.isfinite(data['celsius']):
                    raise ValueError('Недопустимая температура.')
                message = f'Температура доступных датчиков: до {data["celsius"]:.1f} °C.'
            return Result.ok(message, **data)
        except SensorUnavailable as exc:
            return Result.unsupported(str(exc))
        except ImportError:
            return Result.unsupported('Для мониторинга требуется установленный psutil.')
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return Result.fail('Не удалось прочитать достоверный системный показатель.')
