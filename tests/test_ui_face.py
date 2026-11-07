"""Lifecycle and persistence regressions; clocks replace real 60-second waits."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from test_ui_bridge import FakeEngine, wait_for
from ui.presence import Presence
from ui.theme import Appearance
from voice.activation_state import ActivationState


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_manual_face_lease_expires_at_60_seconds_and_can_reawaken(app):
    clock = [10.0]
    presence = Presence(clock=lambda: clock[0])
    assert not presence.awake
    presence.wake()
    clock[0] = 69.999
    presence.tick()
    assert presence.awake
    clock[0] = 70.0
    presence.tick()
    assert not presence.awake
    presence.wake()
    assert presence.awake
    presence.stop()


def test_voice_fsm_owns_expiry_and_resets_after_a_recognized_command(app):
    clock = [0.0]
    now = lambda: clock[0]
    presence = Presence(clock=now)
    fsm = ActivationState(clock=now)
    presence.wake()
    assert fsm.activate()
    presence.voice_state(fsm.state)
    clock[0] = 55
    assert fsm.command_accepted()
    presence.voice_state(fsm.state)
    clock[0] = 65
    presence.tick()
    assert presence.awake  # A real command must finish, even past the old deadline.
    fsm.command_completed(True)
    presence.voice_state(fsm.state)
    clock[0] = 124.999
    presence.voice_state(fsm.tick())
    assert presence.awake
    clock[0] = 125
    presence.voice_state(fsm.tick())
    assert not presence.awake


def test_text_processing_does_not_disappear_mid_command(app):
    clock = [0.0]
    presence = Presence(clock=lambda: clock[0])
    presence.wake()
    presence.set_busy(True)
    clock[0] = 61
    presence.tick()
    assert presence.awake
    presence.set_busy(False)
    assert not presence.awake


def test_only_black_glass_is_available(app, tmp_path):
    from core.config import load_config
    assert load_config(tmp_path)["ui"]["theme"] == "dark"
    appearance = Appearance("blue")
    assert appearance.mode == "dark"
    assert appearance.select("dark")
    assert not appearance.select("blue")
    assert not appearance.select("clear")
    appearance.cycle()
    assert appearance.mode == "dark"


def test_invalid_theme_config_rejected(app, tmp_path):
    import json
    from core.config import load_config
    (tmp_path / "config.json").write_text(json.dumps({"ui": {"theme": "invalid"}}), encoding="utf8")
    with pytest.raises(ValueError, match="Тема"):
        load_config(tmp_path)


def test_face_control_wakes_but_chat_and_theme_do_not(app):
    from ui.app import DesktopUi
    from ui.bridge import Bridge
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    bridge = Bridge(FakeEngine, command_factory=lambda **kw: SimpleNamespace(**kw))
    ui = DesktopUi(app, bridge, enable_tray=False)
    try:
        wait_for(lambda: bridge.ready)
        assert not bridge.presence.awake
        assert ui.mini.findChild(QObject, "themeSwitch") is None
        assert not ui.theme_actions
        orb = ui.mini.findChild(QObject, "energyOrb")
        assert orb.property("time") == 0
        ui.pair.toggleChat()
        ui.pair.toggleChat()
        ui.appearance.select("dark")
        QTest.qWait(150)
        assert not bridge.presence.awake
        assert orb.property("time") == 0
        button = ui.mini.findChild(QObject, "faceActivate")
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseClick(ui.mini, Qt.LeftButton, Qt.NoModifier, point)
        assert bridge.presence.awake
        deadline = bridge.presence._deadline
        ui.appearance.select("blue")
        assert bridge.presence._deadline == deadline
        wait_for(lambda: orb.property("reveal") > 0.99)
        bridge.presence.stop()
        wait_for(lambda: orb.property("reveal") < 0.01)
        QTest.qWait(150)
        sleeping_time = orb.property("time")
        QTest.qWait(150)
        assert orb.property("time") == sleeping_time
        assert not ui.qml_errors
    finally:
        ui.shutdown()
        wait_for(lambda: bridge.isClosed)
        ui.dispose()


@pytest.mark.parametrize("old_theme", ["blue", "clear"])
def test_retired_glass_migrates_without_losing_other_settings(tmp_path, old_theme):
    import json
    from core.config import load_config
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ui": {"theme": old_theme, "chat_visible": False}}), encoding="utf8")
    config = load_config(tmp_path)
    assert config["ui"]["theme"] == "dark"
    assert config["ui"]["chat_visible"] is False
    assert json.loads(path.read_text(encoding="utf8"))["ui"]["theme"] == "dark"


@pytest.mark.parametrize("text,expected,remainder", [
    ("Сириус", True, ""), ("sIrIuS!", True, ""), ("  СИРИУС.  ", True, ""),
    ("Сириус, загрузка процессора", True, "загрузка процессора"),
    ("Sirius загрузка процессора", True, "загрузка процессора"),
    ("Siriusly", False, "Siriusly"), ("сириусы", False, "сириусы"),
    ("буфер сириус", False, "буфер сириус"), ("сервис", False, "сервис"),
])
def test_exact_bilingual_chat_address(text, expected, remainder):
    from core.activation import split_address
    assert split_address(text) == (expected, remainder)


def test_ordinary_text_stays_asleep_and_both_names_wake_without_skill_dispatch(app):
    from test_ui_bridge import make_bridge
    bridge, engines = make_bridge()
    completed = []
    bridge.commandFinished.connect(completed.append)
    try:
        wait_for(lambda: bridge.ready)
        assert bridge.submit("загрузка процессора")
        assert not bridge.presence.awake  # Busy alone is not activation.
        wait_for(lambda: len(completed) == 1)
        assert not bridge.presence.awake
        for name in ("Sirius", "СИРИУС!"):
            assert bridge.submit(name)
            assert bridge.presence.awake
            assert len(engines[0].calls) == 1
            assert bridge.messages.snapshot()[-1]["resultText"] == "Я здесь. Слушаю."
            bridge.presence.stop()
        assert bridge.submit("Сириус, загрузка процессора")
        wait_for(lambda: len(completed) == 2)
        assert engines[0].calls[-1].text == "загрузка процессора"
        assert bridge.presence.awake
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)
