"""Brightness tests use fake displays and fake WMI/SBC boundaries only."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest


def module():
    assert (Path(__file__).parents[1] / 'skills/brightness/handler.py').is_file(), 'brightness handler missing'
    return importlib.import_module('skills.brightness.handler')


def intent(action, **parameters):
    return SimpleNamespace(skill='brightness', action=action, parameters=parameters)


class Display:
    def __init__(self, level=40, accept=True):
        self.level, self.accept = level, accept
        self.writes = []
        self.closed = False

    @contextmanager
    def session(self):
        try:
            yield self
        finally:
            self.closed = True

    def get_level(self):
        return self.level

    def set_level(self, value):
        self.writes.append(value)
        if self.accept:
            self.level = value


def test_brightness_set_verifies_same_display():
    display = Display()
    result = module().Handler(adapter=display).execute(intent('set', value=70), SimpleNamespace(data={}))
    assert result.status == 'success' and result.details['value'] == 70
    assert display.writes == [70] and display.closed


@pytest.mark.parametrize('action,params,expected', [('adjust',{'delta':20},60),('adjust',{'delta':-20},20),('adjust',{'delta':-80},0),('adjust',{'delta':80},100),('set',{'value':-10},0),('set',{'value':130},100)])
def test_adjustment_clamps(action, params, expected):
    display = Display()
    result = module().Handler(adapter=display).execute(intent(action, **params), SimpleNamespace(data={}))
    assert result.verified and display.writes == [expected]


@pytest.mark.parametrize('value', [None,True,2.5,'40','20 & shutdown'])
def test_invalid_brightness_is_rejected(value):
    display = Display()
    result = module().Handler(adapter=display).execute(intent('set', value=value), SimpleNamespace(data={}))
    assert result.status == 'failed' and not display.writes


def test_ignored_brightness_write_is_not_success():
    result = module().Handler(adapter=Display(accept=False)).execute(intent('set', value=80), SimpleNamespace(data={}))
    assert result.status == 'failed' and not result.verified


def test_brightness_exception_is_not_success():
    display = Display()
    display.set_level = lambda value: (_ for _ in ()).throw(OSError('private display'))
    result = module().Handler(adapter=display).execute(intent('set', value=80), SimpleNamespace(data={}))
    assert result.status == 'failed' and 'private' not in result.message and display.closed


def test_real_brightness_adapter_uses_pinned_display(monkeypatch):
    import sys
    calls = []
    native = SimpleNamespace(
        list_monitors_info=lambda: [{'name':'panel'}],
        get_brightness=lambda **kw: calls.append(('get', kw)) or [70],
        set_brightness=lambda value, **kw: calls.append(('set', value, kw)),
    )
    monkeypatch.setitem(sys.modules, 'screen_brightness_control', native)
    monkeypatch.setitem(sys.modules, 'comtypes', SimpleNamespace(
        CoInitialize=lambda: calls.append('init'), CoUninitialize=lambda: calls.append('uninit')))
    result = module().Handler().execute(intent('set', value=70), SimpleNamespace(data={}))
    assert result.verified
    assert calls[0] == 'init' and calls[-1] == 'uninit'
    assert ('set', 70, {'display':0}) in calls and ('get', {'display':0}) in calls


def test_absent_monitor_is_unsupported(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'comtypes', SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None))
    monkeypatch.setitem(sys.modules, 'screen_brightness_control', SimpleNamespace(list_monitors_info=lambda: []))
    assert module().Handler().execute(intent('set', value=70), SimpleNamespace(data={})).status == 'unsupported'
