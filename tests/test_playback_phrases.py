from pathlib import Path
import pytest
from core.intent_router import IntentRouter

@pytest.mark.parametrize('text,action', [
    ('поставь паузу','pause'), ('паузу','pause'), ('поставь видео на паузу','pause'),
    ('продолжи','play'), ('включи музыку','play'), ('приостанови музыку','pause'),
    ('следующий','next'), ('следующая','next'), ('следующее','next'),
    ('следующая музыка','next'), ('следующая песня','next'), ('пропусти','next'),
    ('включи следующий трек','next'), ('предыдущая музыка','previous'),
    ('предыдущее видео','previous'), ('назад','previous'), ('предыдущий','previous'),
])
def test_natural_media_commands_are_recognized(text, action):
    router = IntentRouter(Path(__file__).parents[1] / 'skills')
    parsed = router.parse(text)
    assert parsed is not None and (parsed.skill, parsed.action) == ('media', action)


def test_search_alias_preserves_exact_query_and_browser_back_stays_distinct():
    router = IntentRouter(Path(__file__).parents[1] / 'skills')
    intent = router.parse('поищи в интернете C++ API')
    assert (intent.skill, intent.action, intent.parameters['query']) == ('browser', 'search', 'C++ API')
    assert router.parse('перейди назад').skill == 'browser'
    assert router.parse('назад в браузере').skill == 'browser'


def test_open_browser_does_not_force_an_empty_document(monkeypatch):
    from skills.applications import handler
    calls = []
    adapter = handler.WindowsApplicationAdapter()
    monkeypatch.setattr(handler.sys, 'platform', 'win32')
    monkeypatch.setattr(adapter, 'default_browser', lambda: 'C:/browser/chrome.exe')
    monkeypatch.setattr(handler.subprocess, 'Popen', lambda argv, **kwargs: calls.append((argv, kwargs)))
    adapter.launch(next(s for s in handler.DEFAULT_APPS if s.name == 'browser'))
    assert calls == [(['C:/browser/chrome.exe'], {'shell': False, 'close_fds': True})]
