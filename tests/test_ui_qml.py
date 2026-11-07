"""Load the actual production QML; engine-only units never call Windows skills."""
import importlib.util
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_ui_bridge import FakeEngine, wait_for


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app):
    assert importlib.util.find_spec("ui.app") is not None, "Production Qt host is missing"
    from ui.app import DesktopUi
    from ui.bridge import Bridge
    from types import SimpleNamespace
    bridge = Bridge(FakeEngine, command_factory=lambda **kw: SimpleNamespace(**kw))
    ui = DesktopUi(app, bridge, chat_visible=True, enable_tray=False)
    wait_for(lambda: bridge.ready)
    yield ui
    ui.shutdown()
    wait_for(lambda: bridge.isClosed)
    ui.dispose()
    QCoreApplication.processEvents()


def test_real_qml_two_frameless_equal_height_windows(desktop):
    mini, chat = desktop.mini, desktop.chat
    assert not desktop.qml_errors
    assert mini.objectName() == "miniWindow"
    assert chat.objectName() == "chatWindow"
    assert mini.flags() & Qt.FramelessWindowHint
    assert chat.flags() & Qt.FramelessWindowHint
    assert chat.width() == 2 * mini.width()
    assert mini.height() == chat.height()
    assert mini.y() == chat.y()
    for name in ("miniChatToggle", "miniClose", "faceActivate"):
        assert mini.findChild(QObject, name) is not None
    for name in ("chatClose", "commandInput", "sendButton", "messageList"):
        assert chat.findChild(QObject, name) is not None
    assert desktop.bridge.messages.rowCount() == 0


def test_chat_toggle_does_not_move_mini_and_no_tray_never_orphans_app(desktop):
    mini = desktop.mini
    original = mini.geometry()
    desktop.pair.hideChat()
    assert not desktop.chat.isVisible()
    assert mini.isVisible()
    desktop.pair.toggleChat()
    assert desktop.chat.isVisible()
    assert mini.geometry() == original
    desktop.pair.hideMini()
    assert mini.isVisible(), "Without a usable tray X must leave a recovery path"
    assert mini.windowState() == Qt.WindowMinimized
    desktop.pair.showWindows()
    wait_for(lambda: mini.windowState() != Qt.WindowMinimized)


def test_closed_chat_releases_right_edge_in_real_controller(desktop):
    from PySide6.QtCore import QPoint
    mini, chat = desktop.mini, desktop.chat
    area = mini.screen().availableGeometry()
    desktop.pair.hideChat()
    desktop.pair.reflow(anchor=(area.right() + 1000, mini.y()))
    assert not chat.isVisible()
    assert mini.x() + mini.width() == area.right() + 1 - 16
    desktop.pair.showChat()
    assert chat.isVisible()
    assert chat.x() + chat.width() <= area.right() + 1 - 16


def test_composer_enter_and_shift_enter_use_real_bridge(desktop):
    field = desktop.chat.findChild(QObject, "commandInput")
    desktop.chat.requestActivate()
    wait_for(lambda: desktop.chat.isActive())
    field.forceActiveFocus()
    wait_for(lambda: field.property("activeFocus"))
    field.setProperty("text", "первая")
    QTest.keyClick(desktop.chat, Qt.Key_Return, Qt.ShiftModifier)
    assert "\n" in field.property("text")
    field.setProperty("text", "загрузка процессора")
    QTest.keyClick(desktop.chat, Qt.Key_Return)
    wait_for(lambda: desktop.bridge.messages.rowCount() == 1 and not desktop.bridge.busy)
    assert field.property("text") == ""
    assert desktop.bridge.messages.snapshot()[0]["verified"] is True


def test_real_close_buttons_and_paired_drag_are_recoverable(desktop):
    from PySide6.QtCore import QPoint
    mini, chat = desktop.mini, desktop.chat
    chat.close()
    assert not chat.isVisible() and mini.isVisible()
    assert not desktop.bridge.isClosed
    desktop.pair.toggleChat()
    cursor = [QPoint(400, 200)]
    desktop.pair._cursor = lambda: cursor[0]
    desktop.pair.beginDrag("chat")
    cursor[0] = QPoint(405, 210)
    desktop.pair.drag()
    desktop.pair.endDrag()
    assert mini.y() == chat.y()
    assert chat.width() == 2 * mini.width()
    assert chat.x() > mini.x() + mini.width()
    desktop.pair._tray_available = lambda: True
    mini.close()
    assert not mini.isVisible() and not chat.isVisible()
    desktop.pair.showWindows()
    assert mini.isVisible() and chat.isVisible()
    assert not desktop.qml_errors


def test_qml_buttons_toggle_send_and_activate(desktop):
    from PySide6.QtCore import QPointF
    def click(window, name):
        button = window.findChild(QObject, name)
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    original = desktop.mini.geometry()
    click(desktop.mini, "miniChatToggle")
    assert not desktop.chat.isVisible()
    click(desktop.mini, "miniChatToggle")
    assert desktop.chat.isVisible() and desktop.mini.geometry() == original
    activations = []
    desktop.bridge.activationRequested.connect(lambda: activations.append(True))
    click(desktop.mini, "faceActivate")
    assert activations == [True]
    desktop.chat.findChild(QObject, "commandInput").setProperty("text", "cpu")
    click(desktop.chat, "sendButton")
    wait_for(lambda: desktop.bridge.messages.rowCount() == 1 and not desktop.bridge.busy)
    click(desktop.chat, "chatClose")
    assert not desktop.chat.isVisible() and desktop.mini.isVisible()


def test_smoke_capture_saves_live_windows_geometry_and_no_fake_rows(desktop, tmp_path):
    assert hasattr(desktop, "capture"), "Live render capture is missing"
    wait_for(lambda: desktop.mini.isExposed() and desktop.chat.isExposed())
    QTest.qWait(100)
    evidence = desktop.capture(tmp_path)
    from PySide6.QtGui import QImage
    for name in ("mini", "chat", "pair"):
        image = QImage(str(tmp_path / evidence["screenshots"][name]))
        assert not image.isNull()
        assert image.width() >= 180 and image.height() >= 284
    assert evidence["geometries"]["chat"]["width"] == 2 * evidence["geometries"]["mini"]["width"]
    assert evidence["qml_errors"] == []
    assert desktop.bridge.messages.rowCount() == 0


def test_artwork_assets_are_real_and_prohibited_qml_controls_absent(desktop):
    root = Path(__file__).parents[1] / "ui"
    assert (root / "assets" / "crystal.png").is_file()
    assert (root / "assets" / "ribbons.png").is_file()
    qml = "\n".join(p.read_text(encoding="utf-8") for p in (root / "qml").rglob("*.qml"))
    for token in ("TabBar", "FileDialog", "showFullScreen", "microphoneButton", "countdown", 'text: "-"'):
        assert token not in qml
    assert 'textFormat: Text.PlainText' in qml
