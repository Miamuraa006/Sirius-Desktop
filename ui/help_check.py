"""Real-window acceptance of onboarding and the text/voice help pipeline. No microphone."""
from pathlib import Path
from core.intent_router import SKILL_IDS
import time
from PySide6.QtCore import QObject, QTimer, QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent


class HelpCheck(QObject):
    def __init__(self, ui, output):
        super().__init__(ui)
        self.ui, self.output = ui, Path(output)
        self.finished = self.started = False
        self.phase = "startup"
        self.report = {"passed": False, "errors": [], "results": [], "checks": {}, "shutdown_clean": False}
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.finish("Help check timed out"))
        self.timeout.start(20000)
        ui.bridge.readyChanged.connect(self._ready)
        ui.bridge.commandFinished.connect(self._completed)
        QTimer.singleShot(0, self._ready)

    def _ready(self):
        if self.started or self.finished or not self.ui.bridge.ready:
            return
        self.started = True
        QTimer.singleShot(500, self._start)

    def _start(self):
        mini, chat = self.ui.mini, self.ui.chat
        original = (mini.x(), mini.y())
        area = mini.screen().availableGeometry()
        self.ui.pair.hideChat()
        self.ui.pair.reflow(anchor=(area.right() + 1000, mini.y()))
        self.report['checks']['hidden_chat_releases_right_edge'] = (
            not chat.isVisible() and mini.x() + mini.width() == area.right() + 1 - 16)
        self.ui.pair.showChat()
        self.report['checks']['reopened_chat_fits_screen'] = (
            chat.isVisible() and chat.x() + chat.width() <= area.right() + 1 - 16)
        self.ui.pair.reflow(anchor=original)
        self.report["welcome"] = self.ui.capture(self.output / "welcome")
        self.orb = self.ui.mini.findChild(QObject, "energyOrb")
        hint = self.ui.chat.findChild(QObject, "activationHint").property("text")
        self.report["checks"].update(
            black_only=self.ui.appearance.mode == "dark" and not self.ui.theme_actions,
            no_filter_button=self.ui.mini.findChild(QObject, "themeSwitch") is None,
            welcome_text="Alt + M" in hint and "help" in hint and "разбуд" not in hint.casefold(),
            starts_asleep=not self.ui.bridge.presence.awake,
        )
        self.phase = "text"
        self.ui.bridge.submit("help")

    def _completed(self, result):
        if self.finished:
            return
        self.report["results"].append(dict(result))
        QTimer.singleShot(400, self._capture)

    def _capture(self):
        rows = self.ui.bridge.messages.snapshot()
        checks = self.report["checks"]
        result = self.report["results"][-1]
        checks[self.phase + "_help"] = (rows[-1]["userText"] == "help" and rows[-1]["skillName"] == "help"
            and result.get("verified") is True and len(result.get("details", {}).get("available_skills", [])) == len(SKILL_IDS))
        self.view = self.ui.chat.findChild(QObject, "messageList")
        checks[self.phase + "_shows_start_of_help"] = not self.view.property("atYEnd")
        self.ui.capture(self.output / (self.phase + "-help"))
        if self.phase == "text":
            checks["text_help_keeps_sphere_asleep"] = not self.ui.bridge.presence.awake
            self.phase = "voice"
            self.ui.pair.hideChat()
            self.ui.bridge.offer_voice_text("хелп")  # Already decoded speech; live decoder is checked separately.
        else:
            checks["voice_help_opens_chat"] = self.ui.chat.isVisible()
            self.view = self.ui.chat.findChild(QObject, "messageList")
            checks["help_scrolls"] = self.view.property("contentHeight") > self.view.height()
            self.scroll_steps = 0
            self._scroll()

    def _scroll(self):
        # Exercise a user scroll: positionViewAtEnd alone does not emit the
        # movementStarted signal that deliberately releases help auto-follow.
        if self.view.property("atYEnd") or self.scroll_steps >= 24:
            QTimer.singleShot(400, self._bottom)
            return
        self.scroll_steps += 1
        scale = self.ui.chat.property("panelScale")
        point = QPointF((self.view.x() + self.view.width() / 2) * scale,
                        (self.view.y() + self.view.height() / 2) * scale)
        event = QWheelEvent(point, QPointF(self.ui.chat.mapToGlobal(point.toPoint())),
                            QPoint(), QPoint(0, -480), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        event.setTimestamp(int(time.monotonic() * 1000))
        QCoreApplication.sendEvent(self.ui.chat, event)
        QTimer.singleShot(100, self._scroll)

    def _bottom(self):
        self.ui.capture(self.output / "help-bottom")
        self.report["scroll"] = {name: self.view.property(name) for name in
            ("contentY", "contentHeight", "originY", "height", "atYEnd", "moving", "followLatest")}
        self.report["scroll"]["steps"] = self.scroll_steps
        self.report["checks"]["scrolled_to_bottom"] = bool(self.view.property("atYEnd"))
        self.report["checks"]["no_qml_errors"] = not self.ui.qml_errors
        self.finish()

    def finish(self, error=None):
        if self.finished:
            return
        self.finished = True
        self.timeout.stop()
        if error:
            self.report["errors"].append(error)
        self.report["errors"].extend(k for k, v in self.report["checks"].items() if not v)
        self.report["qml_errors"] = list(self.ui.qml_errors)
        self.ui.shutdown()
