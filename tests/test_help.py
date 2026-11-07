import pytest
from core.help import ENTRIES, is_help
from core.models import Command
from core.intent_router import IntentRouter, SKILL_IDS
from pathlib import Path


@pytest.mark.parametrize("text", ["help", "HELP!", "/help", "хелп", "ХЭЛП", "помощь", "справка", "что ты умеешь?"])
def test_help_aliases_use_the_real_pipeline_without_device_calls(tmp_path, text):
    from test_engine import make
    engine, handler, events = make(tmp_path)
    try:
        assert engine.recognizes(text)
        result = engine.execute(Command(text, "voice"))
        assert result.verified and result.details["presentation"] == "help"
        assert set(result.details["available_skills"]) == set(engine.registry)
        assert not handler.calls
        assert [e["type"] for e in events] == ["recognized", "completed"]
        assert all(e["text"] == "help" for e in events)
        assert engine.history.recent()[0]["text"] == "help"
    finally:
        engine.close()


@pytest.mark.parametrize("text", ["helper", "help me erase files", "буфер help", "хлеб", " ", ""])
def test_help_does_not_swallow_other_text(text):
    assert not is_help(text)


def test_help_examples_are_supported_and_cover_registered_skills():
    router = IntentRouter(Path(__file__).parents[1] / "skills")
    assert set(s for s, _, _ in ENTRIES) == set(SKILL_IDS)
    for skill, _, example in ENTRIES:
        assert router.parse(example).skill == skill


def test_help_preserves_pending_confirmation(tmp_path):
    from test_engine import make
    engine, handler, _ = make(tmp_path)
    try:
        assert engine.execute(Command("закрой блокнот")).status == "needs_confirmation"
        assert engine.execute(Command("help")).verified
        assert not handler.calls
        assert engine.execute(Command("подтверждаю")).verified
    finally:
        engine.close()
