from types import SimpleNamespace
from unittest.mock import Mock
import threading

from core.context import Context
from core.models import Intent
from skills.applications.catalog import protected
from skills.applications.manager import ApplicationManager
from skills.applications.registry import app_registry
from skills.media.handler import WindowsMediaAdapter
from voice.normalization import normalize_command


def test_vosk_observed_opening_does_not_reinterpret_close():
    assert normalize_command('открой системе') == 'открой Steam'
    assert normalize_command('закрой системе') == 'закрой системе'


def test_media_work_isolated_from_caller_com_apartment():
    adapter = WindowsMediaAdapter()
    caller = threading.get_ident()
    adapter._run_media = lambda action, target: (action, target, threading.get_ident())
    action, target, owner = adapter.perform('play', {'source': 'fixture'})
    assert action == 'play' and target['source'] == 'fixture' and owner != caller


def test_background_exit_only_after_disappearance(monkeypatch):
    adapter = Mock()
    manager = ApplicationManager(adapter)
    monkeypatch.setattr(manager, '_windows', lambda spec: [])
    adapter.find_windows.return_value = []
    adapter.background_processes.return_value = ['fixture']
    adapter.finish_background.return_value = False
    result = manager.close_app(app_registry({})['steam'], Context())
    assert not result.verified
    assert adapter.finish_background.call_count == 1


def test_protected_names_rejected_even_with_confirmation():
    for name in ('ParkControl', 'Настройки NVIDIA'):
        assert protected(name)
        adapter = Mock()
        result = ApplicationManager(adapter).execute(Intent('applications', 'close_app', {'app':name}),
                                                    SimpleNamespace(data={'confirmed':True}))
        assert not result.verified and not adapter.mock_calls
