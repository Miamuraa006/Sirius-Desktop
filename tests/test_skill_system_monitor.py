"""Native boundaries are injected: no fabricated production telemetry."""
from importlib import import_module
from types import SimpleNamespace

import pytest


def command(action, **parameters):
    return SimpleNamespace(skill='system_monitor', action=action, parameters=parameters)


@pytest.mark.parametrize('action,expected', [
    ('cpu', {'percent': 37.5}),
    ('ram', {'percent': 25.0, 'used': 100, 'available': 300, 'total': 400}),
    ('disk', {'percent': 40.0, 'used': 200, 'free': 300, 'total': 500}),
    ('battery', {'percent': 87.0, 'power_plugged': True, 'seconds_left': None}),
    ('temperature', {'celsius': 52.5, 'sensors': 1}),
])
def test_metric_handler_reports_only_native_values(action, expected):
    native = SimpleNamespace(
        cpu_percent=lambda **kw: 37.5,
        virtual_memory=lambda: SimpleNamespace(percent=25., used=100, available=300, total=400),
        disk_usage=lambda path: SimpleNamespace(percent=40., used=200, free=300, total=500),
        sensors_battery=lambda: SimpleNamespace(percent=87., power_plugged=True, secsleft=-2),
        sensors_temperatures=lambda: {'cpu': [SimpleNamespace(current=52.5)]},
    )
    handler = module().Handler(module().WindowsMonitorAdapter(native))
    result = handler.execute(command(action), SimpleNamespace(data={}))
    assert result.status == 'success'
    assert result.verified
    for key, value in expected.items():
        assert result.details[key] == value


@pytest.mark.parametrize('action', ['battery', 'temperature'])
def test_unavailable_sensor_is_unsupported(action):
    native = SimpleNamespace(sensors_battery=lambda: None, sensors_temperatures=lambda: {})
    result = module().Handler(module().WindowsMonitorAdapter(native)).execute(command(action), None)
    assert result.status == 'unsupported'
    assert not result.verified


@pytest.mark.parametrize('percent', [float('nan'), float('inf'), -1, 101, 'fake'])
def test_invalid_native_sample_is_never_success(percent):
    adapter = SimpleNamespace(read=lambda *args: {'percent': percent})
    result = module().Handler(adapter).execute(command('cpu'), None)
    assert result.status == 'failed'
    assert not result.verified


def test_unknown_action_never_calls_adapter():
    result = module().Handler(object()).execute(command('shutdown'), None)
    assert result.status == 'failed'


def module():
    try:
        return import_module('skills.system_monitor.handler')
    except ModuleNotFoundError as exc:
        assert False, f'Monitor implementation is missing: {exc}'


def test_disk_message_has_one_drive_colon():
    adapter = SimpleNamespace(read=lambda *args: {'percent': 40., 'used': 200, 'free': 300, 'total': 500})
    result = module().Handler(adapter).execute(command('disk'), None)
    assert result.verified and '::' not in result.message


def test_cpu_uses_interval_sample_not_unprimed_cached_value():
    calls = []
    native = SimpleNamespace(cpu_percent=lambda **kw: calls.append(kw) or 37.5)
    adapter = module().WindowsMonitorAdapter(native)
    assert adapter.read('cpu') == {'percent': 37.5}
    assert calls == [{'interval': 0.15}]
