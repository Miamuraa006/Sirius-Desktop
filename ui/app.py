"""Native two-window Qt Quick host. No sample data or simulated skills."""
from __future__ import annotations

import logging
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # Register the correct QML root wrapper before loading.
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ui.geometry import fit_pair
from ui.runtime import ApplicationRuntime
from ui.theme import Appearance
from ui.backdrop import apply_backdrop

LOG = logging.getLogger(__name__)


class DesktopController(QObject):
    """Paired geometry that reserves only the currently visible panels."""
    def __init__(self, app, *, chat_visible=True, tray_available=None, cursor_provider=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.mini = self.chat = None
        self.chat_visible = bool(chat_visible)
        self._tray_available = tray_available or (lambda: False)
        self._cursor = cursor_provider or QCursor.pos
        self._drag_origin = None
        self._screen = None
        self._applying = False
        self._hidden = False
        self.zoom = 1.0
        app.screenAdded.connect(self._screens_changed)
        app.screenRemoved.connect(self._screens_changed)

    def attach(self, mini, chat):
        self.mini, self.chat = mini, chat
        mini.screenChanged.connect(self._screens_changed)
        chat.screenChanged.connect(self._screens_changed)
        self.reflow(center=True)
        self.showWindows()

    def _watch_screen(self, screen):
        if screen is self._screen:
            return
        if self._screen is not None:
            for signal in (self._screen.availableGeometryChanged, self._screen.logicalDotsPerInchChanged):
                try:
                    signal.disconnect(self._screens_changed)
                except (RuntimeError, TypeError):
                    pass
        self._screen = screen
        for signal in (screen.availableGeometryChanged, screen.logicalDotsPerInchChanged):
            signal.connect(self._screens_changed)

    def _screens_changed(self, *_):
        if self.mini is not None and not self._applying:
            self.reflow()

    def reflow(self, *, anchor=None, screen=None, center=False):
        if self.mini is None:
            return
        screen = screen or self.app.screenAt(self.mini.position()) or self.app.primaryScreen()
        if screen is None:
            raise RuntimeError("No screen available")
        self._watch_screen(screen)
        area = screen.availableGeometry()
        if anchor is None and not center:
            anchor = (self.mini.x(), self.mini.y())
        layout = fit_pair((area.x(), area.y(), area.width(), area.height()), anchor, self.zoom,
                          chat_visible=self.chat_visible)
        self._applying = True
        try:
            for window, rect in ((self.mini, layout.mini), (self.chat, layout.chat)):
                window.setScreen(screen)
                window.setProperty("panelScale", layout.scale)
                window.setGeometry(QRect(*rect))
        finally:
            self._applying = False
        return layout

    def set_zoom(self, zoom):
        self.zoom = zoom
        self.reflow()

    @Slot()
    def hideChat(self):
        self.chat_visible = False
        self.chat.hide()
        self.reflow()

    @Slot()
    def showChat(self):
        self.chat_visible = True
        self.showWindows()

    @Slot()
    def toggleChat(self):
        if self.chat_visible:
            self.hideChat()
        else:
            self.chat_visible = True
            self.reflow()
            self.chat.showNormal()
            self.chat.raise_()

    @Slot()
    def hideMini(self):
        self.chat.hide()
        if self._tray_available():
            self._hidden = True
            self.mini.hide()
        else:
            # Keep a taskbar recovery path if the system tray is unavailable.
            self.mini.showMinimized()

    @Slot()
    def showWindows(self):
        if self.mini is None:
            return
        self._hidden = False
        self.reflow()
        self.mini.showNormal()
        self.mini.raise_()
        if self.chat_visible:
            self.chat.showNormal()
            self.chat.raise_()
        self.mini.requestActivate()

    @Slot(str)
    def beginDrag(self, panel):
        if panel not in ("mini", "chat"):
            return
        self._drag_origin = (self._cursor(), self.mini.position())

    @Slot()
    def drag(self):
        if self._drag_origin is None:
            return
        pointer = self._cursor()
        start, anchor = self._drag_origin
        target = anchor + pointer - start
        self.reflow(anchor=(target.x(), target.y()), screen=self.app.screenAt(pointer))

    @Slot()
    def endDrag(self):
        self._drag_origin = None

    def dispose(self):
        self.app.screenAdded.disconnect(self._screens_changed)
        self.app.screenRemoved.disconnect(self._screens_changed)
        if self._screen is not None:
            for signal in (self._screen.availableGeometryChanged, self._screen.logicalDotsPerInchChanged):
                try:
                    signal.disconnect(self._screens_changed)
                except (RuntimeError, TypeError):
                    pass
        self.mini = self.chat = None


class DesktopUi(QObject):
    microphoneRequested = Signal(bool)
    shutdownRequested = Signal()
    gameModeFinished = Signal()
    fullyClosed = Signal()

    def __init__(self, app, bridge, *, chat_visible=True, enable_tray=True, resource_root=None,
                 theme="dark", persist_theme=None):
        super().__init__()
        self.app, self.bridge = app, bridge
        self.root = Path(resource_root) / "ui" if resource_root else Path(__file__).resolve().parent
        self.qml_errors = []
        self._closing = False
        self._disposed = False
        self.tray = None
        self.menu = None
        self.actions = {}
        self.theme_actions = {}
        self.backdrops = {}
        self.appearance = Appearance(theme, persist_theme, self)
        self.appearance.changed.connect(self._appearance_changed)
        self.appearance.saveFailed.connect(self._diagnostic)
        app.setQuitOnLastWindowClosed(False)
        self.pair = DesktopController(app, chat_visible=chat_visible, tray_available=self._has_tray, parent=self)
        bridge.chatRequested.connect(self.pair.showChat)
        self.qml = QQmlApplicationEngine(self)
        self.qml.warnings.connect(self._qml_warning)
        self.qml.rootContext().setContextProperty("bridge", bridge)
        self.qml.rootContext().setContextProperty("pair", self.pair)
        self.qml.rootContext().setContextProperty("appearance", self.appearance)
        for name in ("MiniWindow.qml", "ChatWindow.qml"):
            self.qml.load(QUrl.fromLocalFile(str(self.root / "qml" / name)))
        roots = {window.objectName(): window for window in self.qml.rootObjects()}
        if not {"miniWindow", "chatWindow"} <= roots.keys():
            self.dispose()
            raise RuntimeError("Cannot load Sirius QML: " + "; ".join(self.qml_errors))
        self.mini, self.chat = roots["miniWindow"], roots["chatWindow"]
        icon = QIcon(str(self.root / "assets" / "sirius.ico"))
        self.mini.setIcon(icon)
        self.chat.setIcon(icon)
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self._make_tray(icon)
        self.pair.attach(self.mini, self.chat)
        self._appearance_changed()
        bridge.closedChanged.connect(self._bridge_closed)
        bridge.diagnostic.connect(self._diagnostic)

    def _appearance_changed(self):
        if hasattr(self, "mini"):
            self.backdrops = {name: apply_backdrop(window, self.appearance.mode)
                              for name, window in (("mini", self.mini), ("chat", self.chat))}
        for mode, action in self.theme_actions.items():
            action.setChecked(mode == self.appearance.mode)

    def _qml_warning(self, warnings):
        for warning in warnings:
            text = warning.toString()
            self.qml_errors.append(text)
            LOG.error("QML: %s", text)

    def _has_tray(self):
        return bool(self.tray and self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable())

    def _make_tray(self, icon):
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("SIRIUS")
        self.menu = QMenu()
        sizes = self.menu.addMenu("Размер окна")
        self.size_group = QActionGroup(self.menu)
        self.size_group.setExclusive(True)
        for label, zoom in (("Компактный · 100%", 1.0), ("Средний · 125%", 1.25), ("Крупный · 150%", 1.5)):
            action = sizes.addAction(label)
            action.setCheckable(True)
            action.setChecked(zoom == 1.0)
            self.size_group.addAction(action)
            action.triggered.connect(lambda checked=False, z=zoom: self.pair.set_zoom(z))
        self.menu.addSeparator()
        definitions = (("show", "Показать SIRIUS", self.pair.showWindows),
                       ("activate", "Активировать голос", self.bridge.activate),
                       ("microphone", "Микрофон включён", None),
                       ("clear", "Очистить историю", self.bridge.clearHistory),
                       ("exit", "Выход", self.shutdown))
        for name, label, callback in definitions:
            if name == "exit":
                self.menu.addSeparator()
            action = QAction(label, self.menu)
            self.actions[name] = action
            if name == "microphone":
                action.setCheckable(True)
                action.setChecked(True)
                action.toggled.connect(self.microphoneRequested)
            else:
                action.triggered.connect(callback)
            self.menu.addAction(action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def set_microphone_enabled(self, enabled):
        action = self.actions.get("microphone")
        if action is not None:
            old = action.blockSignals(True)
            action.setChecked(bool(enabled))
            action.blockSignals(old)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.pair.showWindows()

    @Slot(str)
    def _diagnostic(self, text):
        LOG.warning("%s", text)
        if self._has_tray() and not self._closing:
            self.tray.showMessage("SIRIUS", text, QSystemTrayIcon.Warning, 5000)

    @Slot()
    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self.mini.hide()
        self.chat.hide()
        if self.tray:
            self.tray.hide()
        self.shutdownRequested.emit()
        self.bridge.shutdown()
        self._bridge_closed()

    def _bridge_closed(self):
        if self._closing and self.bridge.isClosed:
            self.fullyClosed.emit()

    def capture(self, output):
        """Grab actual scenegraph windows, plus an exact-position pair composite."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        geometries, screenshots, images = {}, {}, {}
        for name, window in (("mini", self.mini), ("chat", self.chat)):
            if not window.isVisible() or not window.isExposed():
                raise RuntimeError(f"{name} window is not exposed")
            image = window.grabWindow()
            if image.isNull():
                raise RuntimeError(f"Could not capture {name}")
            filename = f"{name}.png"
            if not image.save(str(output / filename)):
                raise OSError(f"Could not save {filename}")
            screen = window.screen()
            area = screen.availableGeometry()
            geometries[name] = dict(x=window.x(), y=window.y(), width=window.width(),
                height=window.height(), scale=window.property("panelScale"),
                device_pixel_ratio=window.devicePixelRatio(), screen=screen.name(),
                available=[area.x(), area.y(), area.width(), area.height()],
                image_width=image.width(), image_height=image.height())
            screenshots[name], images[name] = filename, image
        bounds = self.mini.geometry().united(self.chat.geometry())
        ratio = max(self.mini.devicePixelRatio(), self.chat.devicePixelRatio())
        composite = QImage(round(bounds.width() * ratio), round(bounds.height() * ratio), QImage.Format_ARGB32)
        composite.setDevicePixelRatio(ratio)
        composite.fill(Qt.transparent)
        painter = QPainter(composite)
        try:
            for name, window in (("mini", self.mini), ("chat", self.chat)):
                rect = window.geometry().translated(-bounds.x(), -bounds.y())
                painter.drawImage(QRectF(rect), images[name], QRectF(images[name].rect()))
        finally:
            painter.end()
        if not composite.save(str(output / "pair.png")):
            raise OSError("Could not save pair.png")
        screenshots["pair"] = "pair.png"
        return dict(geometries=geometries, screenshots=screenshots, qml_errors=list(self.qml_errors),
                    theme=self.appearance.mode, backdrops=self.backdrops)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        if self.tray:
            self.tray.hide()
        self.pair.dispose()
        # Destroy QML before its Python context properties. No null-binding spam.
        import shiboken6
        shiboken6.delete(self.qml)
        if self.menu:
            self.menu.deleteLater()


def run(config: dict, data_dir: Path, *, smoke_output: Path | None = None, no_voice: bool = False) -> int:
    """Production entry point used by main.py and the frozen Windows executable."""
    import json
    from PySide6.QtCore import QEventLoop, QTimer
    from core.engine import Engine
    from ui.bridge import Bridge
    from ui.smoke import RenderSmoke
    from ui.target import ExternalTarget

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("SIRIUS")
    app.setOrganizationName("SIRIUS")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    target = ExternalTarget()
    target.snapshot()  # Take the initial external HWND before our panels take focus.
    bridge = Bridge(lambda callback: Engine(config, data_dir, event_callback=callback),
                    target_provider=target.snapshot)
    def persist_theme(mode):
        from copy import deepcopy
        from core.config import save_config
        updated = deepcopy(config)
        updated.setdefault("ui", {})["theme"] = mode
        save_config(data_dir, updated)
        config.setdefault("ui", {})["theme"] = mode
    try:
        ui = DesktopUi(app, bridge, chat_visible=config.get("ui", {}).get("chat_visible", True),
                       resource_root=config.get("_resource_root"),
                       theme=config.get("ui", {}).get("theme", "dark"), persist_theme=persist_theme)
    except Exception as exc:
        bridge.shutdown()
        if not bridge.isClosed:
            drain = QEventLoop()
            bridge.closedChanged.connect(drain.quit)
            drain.exec()
        LOG.error("Desktop startup failed: %s", exc)
        if smoke_output is not None:
            output = Path(smoke_output)
            output.mkdir(parents=True, exist_ok=True)
            (output / "report.json").write_text(json.dumps(dict(passed=False,
                errors=[str(exc)], qml_errors=[str(exc)], geometries={}, results=[],
                screenshots={}, shutdown_clean=bridge.isClosed), ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    runtime = ApplicationRuntime(ui, config, no_voice=no_voice)
    game_watcher = None
    if sys.platform == "win32" and smoke_output is None:
        from skills.applications.game_mode import watch_game
        game_stop = threading.Event()
        ui.shutdownRequested.connect(game_stop.set)
        ui.gameModeFinished.connect(ui.shutdown, Qt.QueuedConnection)
        game_watcher = threading.Thread(target=watch_game, args=(config, game_stop, ui.gameModeFinished.emit),
                                       name="SiriusGameMode", daemon=True)
        game_watcher.start()
    focus_timer = QTimer(ui)
    focus_timer.setInterval(100)
    focus_timer.timeout.connect(target.snapshot)
    focus_timer.start()
    runtime.finished.connect(app.quit)
    if smoke_output is not None and config.get("_help_check", False):
        from ui.help_check import HelpCheck
        smoke = HelpCheck(ui, smoke_output)
    elif smoke_output is not None and config.get("_face_check", False):
        from ui.face_check import FaceCheck
        smoke = FaceCheck(ui, smoke_output)
    else:
        smoke = RenderSmoke(ui, smoke_output) if smoke_output is not None else None
    try:
        exit_code = app.exec()
    finally:
        focus_timer.stop()
        ui.shutdown()
        if game_watcher is not None:
            game_stop.set()
            game_watcher.join()
        if not runtime.is_closed:
            # OS/app quit may precede worker completion. Drain Qt callbacks before deletion.
            drain = QEventLoop()
            runtime.finished.connect(drain.quit)
            drain.exec()
        ui.dispose()
    remaining = [thread.name for thread in threading.enumerate()
                 if thread.name.startswith(("sirius-engine", "sirius-services", "SiriusVoice", "SiriusHotkey", "SiriusAudio"))]
    clean = runtime.is_closed and bridge.isClosed and not runtime.shutdown_errors and not remaining
    if smoke is not None:
        report = smoke.report
        if not smoke.finished:
            report["errors"].append("Application exited before render smoke completed")
        report["errors"].extend(runtime.shutdown_errors)
        if remaining:
            report["errors"].append("Owned workers remain after shutdown")
        report["remaining_workers"] = remaining
        report["shutdown_clean"] = clean
        report["qml_errors"] = list(ui.qml_errors)
        report["passed"] = bool(smoke.finished and not report["errors"] and not report["qml_errors"] and clean)
        output = Path(smoke_output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if report["passed"] else 1
    return int(exit_code) if clean else 1
