"""Native boundaries are fake: never changes the host audio endpoint."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest


def module():
    assert (Path(__file__).parents[1] / 'skills/volume/handler.py').is_file(), 'volume handler missing'
    return importlib.import_module('skills.volume.handler')


def intent(action, **parameters):
    return SimpleNamespace(skill='volume', action=action, parameters=parameters)


def context():
    return SimpleNamespace(data={}, last_app=None, last_window=None, last_skill=None, last_action=None)


class Audio:
    def __init__(self, level=40, muted=False, accept=True):
        self.level, self.muted, self.accept = level, muted, accept
        self.writes = []
        self.reads = 0
        self.closed = False

    @contextmanager
    def session(self):
        try:
            yield self
        finally:
            self.closed = True

    def get_level(self):
        self.reads += 1
        return self.level

    def set_level(self, value):
        self.writes.append(value)
        if self.accept:
            self.level = value

    def get_mute(self):
        return self.muted

    def set_mute(self, value):
        self.writes.append(value)
        if self.accept:
            self.muted = value


def test_set_volume_requires_readback():
    audio = Audio()
    result = module().Handler(adapter=audio).execute(intent('set', value=70), context())
    assert result.status == 'success' and result.verified
    assert result.details['value'] == 70
    assert audio.writes == [70] and audio.reads >= 1 and audio.closed


@pytest.mark.parametrize('level,delta,expected', [(40,20,60),(40,-20,20),(95,20,100),(5,-20,0),(40,10,50),(40,-10,30)])
def test_adjust_is_clamped_and_verified(level, delta, expected):
    audio = Audio(level)
    result = module().Handler(adapter=audio).execute(intent('adjust', delta=delta), context())
    assert result.status == 'success' and result.verified
    assert audio.writes == [expected] and result.details['value'] == expected


@pytest.mark.parametrize('action,initial,expected', [('mute',False,True),('unmute',True,False)])
def test_mute_is_read_back(action, initial, expected):
    audio = Audio(muted=initial)
    result = module().Handler(adapter=audio).execute(intent(action), context())
    assert result.status == 'success' and result.details['muted'] is expected


@pytest.mark.parametrize('action,params', [('set',{'value':70}),('adjust',{'delta':20}),('mute',{})])
def test_ignored_driver_write_never_reports_success(action, params):
    result = module().Handler(adapter=Audio(accept=False)).execute(intent(action, **params), context())
    assert result.status == 'failed' and not result.verified


@pytest.mark.parametrize('value', [None,True,3.5,'80','70;calc.exe'])
def test_invalid_value_does_not_write(value):
    audio = Audio()
    result = module().Handler(adapter=audio).execute(intent('set', value=value), context())
    assert result.status == 'failed' and not audio.writes


@pytest.mark.parametrize('value,expected', [(-10,0),(130,100)])
def test_set_clamps(value, expected):
    audio = Audio()
    assert module().Handler(adapter=audio).execute(intent('set', value=value), context()).verified
    assert audio.writes == [expected]


def test_unknown_action_does_not_touch_native_state():
    audio = Audio()
    assert module().Handler(adapter=audio).execute(intent('launch'), context()).status == 'failed'
    assert not audio.writes


def test_driver_exception_is_a_failed_result_without_exception_payload():
    audio = Audio()
    def broken(value):
        raise OSError('private endpoint payload')
    audio.set_level = broken
    result = module().Handler(adapter=audio).execute(intent('set', value=20), context())
    assert result.status == 'failed' and 'private' not in result.message and audio.closed


def test_real_adapter_owns_com_and_converts_scalar(monkeypatch):
    import sys
    calls = []
    endpoint = SimpleNamespace(
        SetMasterVolumeLevelScalar=lambda v, _: calls.append(('set', v)),
        GetMasterVolumeLevelScalar=lambda: 0.70,
        SetMute=lambda v, _: calls.append(('mute', v)),
        GetMute=lambda: 1,
    )
    monkeypatch.setitem(sys.modules, 'comtypes', SimpleNamespace(
        CoInitialize=lambda: calls.append('init'), CoUninitialize=lambda: calls.append('uninit')))
    monkeypatch.setitem(sys.modules, 'pycaw.pycaw', SimpleNamespace(AudioUtilities=SimpleNamespace(
        GetSpeakers=lambda: SimpleNamespace(EndpointVolume=endpoint))))
    handler = module().Handler()
    result = handler.execute(intent('set', value=70), context())
    assert result.verified and calls == ['init', ('set', 0.7), 'uninit']
    result = handler.execute(intent('mute'), context())
    assert result.verified and calls[-3:] == ['init', ('mute', 1), 'uninit']


def test_absent_audio_device_is_unsupported_and_com_is_released(monkeypatch):
    import sys
    calls = []
    monkeypatch.setitem(sys.modules, 'comtypes', SimpleNamespace(
        CoInitialize=lambda: None, CoUninitialize=lambda: calls.append('uninit')))
    monkeypatch.setitem(sys.modules, 'pycaw.pycaw', SimpleNamespace(
        AudioUtilities=SimpleNamespace(GetSpeakers=lambda: None)))
    result = module().Handler().execute(intent('set', value=70), context())
    assert result.status == 'unsupported' and calls == ['uninit']
