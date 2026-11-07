"""Verified Windows master volume.

Migrated from SIRIUS_v0.3 orginal/skills/lite/volume.py: scalar conversion,
worker-thread COM ownership and clamped relative adjustment. Unlike legacy,
all writes require endpoint readback, including mute.
"""
from contextlib import contextmanager
import sys
from core.models import Result


class AudioUnavailable(RuntimeError):
    """No Windows render endpoint, not a dependency/programming failure."""


class Endpoint:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def get_level(self):
        return round(float(self.endpoint.GetMasterVolumeLevelScalar()) * 100)

    def set_level(self, value):
        self.endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)

    def get_mute(self):
        return bool(self.endpoint.GetMute())

    def set_mute(self, value):
        self.endpoint.SetMute(int(value), None)


class WindowsVolumeAdapter:
    @contextmanager
    def session(self):
        if sys.platform != 'win32':
            raise AudioUnavailable('Windows Audio недоступен на этой системе.')
        import comtypes
        comtypes.CoInitialize()
        try:
            from pycaw.pycaw import AudioUtilities
            device = AudioUtilities.GetSpeakers()
            if device is None:
                raise AudioUnavailable('Устройство вывода звука не обнаружено.')
            endpoint = Endpoint(device.EndpointVolume)
            try:
                yield endpoint
            finally:
                # Release COM references before balancing the worker's COM init.
                endpoint.endpoint = None
                device = None
        finally:
            comtypes.CoUninitialize()


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsVolumeAdapter()

    def execute(self, intent, context):
        action = intent.action
        if action not in {'set', 'adjust', 'mute', 'unmute'}:
            return Result.fail('Неизвестное действие с громкостью.')
        value = intent.parameters.get('value' if action == 'set' else 'delta')
        if action in {'set', 'adjust'} and type(value) is not int:
            return Result.fail('Громкость и шаг должны быть целыми числами.')
        try:
            with self.adapter.session() as audio:
                if action in {'mute', 'unmute'}:
                    muted = action == 'mute'
                    audio.set_mute(muted)
                    actual = audio.get_mute()
                    if actual is not muted:
                        return Result.fail('Windows не подтвердила переключение звука.')
                    return Result.ok('Звук выключен.' if muted else 'Звук включён.', muted=actual)
                desired = value if action == 'set' else audio.get_level() + value
                desired = max(0, min(100, desired))
                audio.set_level(desired)
                actual = audio.get_level()
                if type(actual) not in (int, float) or not 0 <= actual <= 100 or abs(actual - desired) > 1:
                    return Result.fail('Windows не подтвердила изменение громкости.')
                return Result.ok(f'Громкость: {actual}%.', value=actual)
        except AudioUnavailable as exc:
            return Result.unsupported(str(exc))
        except Exception:
            return Result.fail('Не удалось изменить громкость через Windows Audio.')
