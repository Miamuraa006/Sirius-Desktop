"""Opt-in acceptance of the real renderer and real 60-second fallback lease. No audio capture."""
import time
from PySide6.QtCore import QTimer
from ui.smoke import RenderSmoke


class FaceCheck(RenderSmoke):
    def __init__(self, ui, output):
        super().__init__(ui, output)
        self.timeout.setInterval(95000)
        self.timeout.start()
        self.original_theme = ui.appearance.mode
        self.themes = iter(("dark",))
        self.report["face"] = {"themes": {}, "frames": {}}
        self.sequence_timer = QTimer(self)
        self.sequence_timer.setInterval(50)
        self.sequence_timer.timeout.connect(self._sequence_frame)
        self.lease_timer = QTimer(self)
        self.lease_timer.setInterval(50)
        self.lease_timer.timeout.connect(self._wait_for_sleep)
        self.phase = ""
        self.sequence_count = 0
        self.sequence_done = None
        self.waiting_idle = False

    def _ready(self):
        if self.started or self.finished or getattr(self, "waiting_idle", False):
            return
        if not self.ui.bridge.ready:
            return super()._ready()
        self.waiting_idle = True
        from PySide6.QtCore import QObject
        self.orb = self.ui.mini.findChild(QObject, "energyOrb")
        self.idle_time = self.orb.property("time")
        self.ui.pair.toggleChat()
        self.ui.pair.toggleChat()
        QTimer.singleShot(1000, self._check_dormant)

    def _check_dormant(self):
        if self.finished:
            return
        self.report["face"]["startup_and_chat_still"] = (
            not self.ui.bridge.presence.awake and self.orb.property("time") == self.idle_time)
        self.ui.capture(self.output / "startup")
        super()._ready()

    def _begin_motion(self):
        self.report["face"]["ordinary_text_does_not_wake"] = (
            not self.ui.bridge.presence.awake and self.orb.property("time") == self.idle_time)
        self.ui.bridge.submit("Sirius")
        self.report["face"]["english_wake"] = self.ui.bridge.presence.awake
        QTimer.singleShot(1200, super()._begin_motion)

    def _check_hidden(self):
        if self.finished:
            return
        self.report["motion"]["paused_when_hidden"] = self.orb.property("time") == self.hidden_time
        self.ui.pair.showWindows()
        self._next_theme()

    def _next_theme(self):
        if self.finished:
            return
        try:
            self.current_theme = next(self.themes)
        except StopIteration:
            self.ui.appearance.select(self.original_theme)
            self.ui.bridge.presence.stop()
            self._sequence("sleep", self._wake)
            return
        if not self.ui.appearance.select(self.current_theme):
            self.finish("Theme selection failed")
            return
        QTimer.singleShot(500, self._capture_theme)

    def _capture_theme(self):
        if self.finished:
            return
        folder = self.output / ("theme-" + self.current_theme)
        self.report["face"]["themes"][self.current_theme] = self.ui.capture(folder)
        self._next_theme()

    def _sequence(self, name, callback):
        self.phase, self.sequence_count, self.sequence_done = name, 0, callback
        (self.output / name).mkdir(parents=True, exist_ok=True)
        self.sequence_timer.start()

    def _sequence_frame(self):
        if self.finished:
            self.sequence_timer.stop()
            return
        image = self.ui.mini.grabWindow()
        if image.isNull() or not image.save(str(self.output / self.phase / f"{self.sequence_count:03}.png")):
            self.finish("Face transition capture failed")
            return
        self.sequence_count += 1
        if self.sequence_count >= 32:
            self.sequence_timer.stop()
            self.report["face"]["frames"][self.phase] = self.sequence_count
            if self.phase in ("sleep", "timeout"):
                self.report["face"][self.phase + "_reveal"] = self.orb.property("reveal")
            self.sequence_done()

    def _wake(self):
        self.ui.bridge.submit("Сириус")
        self.lease_started = time.monotonic()
        self.report["face"]["awake_after_click_signal"] = self.ui.bridge.presence.awake
        self._sequence("wake", self._begin_wait)

    def _begin_wait(self):
        self.report["face"]["wake_reveal"] = self.orb.property("reveal")
        self.report["face"]["gpu_available"] = self.orb.property("gpuAvailable")
        self.report["face"]["observed_awake_at_59_seconds"] = False
        self.lease_timer.start()

    def _wait_for_sleep(self):
        elapsed = time.monotonic() - self.lease_started
        if 59 <= elapsed < 60 and self.ui.bridge.presence.awake:
            self.report["face"]["observed_awake_at_59_seconds"] = True
        if not self.ui.bridge.presence.awake:
            self.lease_timer.stop()
            self.report["face"]["timeout_seconds"] = round(elapsed, 3)
            self._sequence("timeout", self._done)
        elif elapsed > 62:
            self.finish("Presence did not expire")

    def _done(self):
        self.sleep_time = self.orb.property("time")
        QTimer.singleShot(400, self._finish_sleep_check)

    def _finish_sleep_check(self):
        face = self.report["face"]
        checks = {
            "black_glass_only": set(face["themes"]) == {"dark"},
            "startup_and_chat_still": face["startup_and_chat_still"],
            "ordinary_text_does_not_wake": face["ordinary_text_does_not_wake"],
            "english_wake": face["english_wake"],
            "frozen_after_sleep": self.orb.property("time") == self.sleep_time,
            "woke": face["awake_after_click_signal"] and face["wake_reveal"] > 0.99,
            "sleep_transition": face["sleep_reveal"] < 0.01,
            "real_60_seconds": face["observed_awake_at_59_seconds"] and 59.8 <= face["timeout_seconds"] <= 60.5,
            "timeout_transition": face["timeout_reveal"] < 0.01,
        }
        face["checks"] = checks
        self.report["errors"].extend(name for name, passed in checks.items() if not passed)
        self.finish()

    def finish(self, error=None):
        if hasattr(self, "sequence_timer"):
            self.sequence_timer.stop()
            self.lease_timer.stop()
        super().finish(error)
