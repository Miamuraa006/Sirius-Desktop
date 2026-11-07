"""An executable render smoke: real harmless CPU command, actual window images."""
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer


class RenderSmoke(QObject):
    def __init__(self, ui, output):
        super().__init__(ui)
        self.ui = ui
        self.output = Path(output)
        self.started = self.finished = False
        self.report = dict(passed=False, command="загрузка процессора", results=[],
                           qml_errors=[], geometries={}, screenshots={}, errors=[], shutdown_clean=False)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(30000)
        self.timeout.timeout.connect(lambda: self.finish("Render smoke timed out"))
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.setInterval(350)
        self.capture_timer.timeout.connect(self._begin_motion)
        self.motion_timer = QTimer(self)
        self.motion_timer.setInterval(80)
        self.motion_timer.timeout.connect(self._sample_motion)
        self.samples = []
        ui.bridge.readyChanged.connect(self._ready)
        ui.bridge.commandFinished.connect(self._completed)
        self.timeout.start()
        QTimer.singleShot(0, self._ready)

    def _ready(self):
        if self.started or self.finished:
            return
        if not self.ui.bridge.ready:
            if self.ui.bridge.initialized:
                # Capture after the first frame even when bootstrap failed.
                QTimer.singleShot(350, lambda: self.finish("Engine initialization failed"))
            return
        self.started = True
        if not self.ui.pair.chat_visible:
            self.ui.pair.toggleChat()
        self.ui.pair.showWindows()
        if not self.ui.bridge.submit(self.report["command"]):
            self.finish("CPU command was not accepted")

    def _completed(self, result):
        if not self.started or self.finished or result.get("source") != "text":
            return
        self.report["results"].append(dict(result))
        self.capture_timer.start()

    def _begin_motion(self):
        import psutil
        if not self.ui.bridge.presence.awake:
            self.ui.bridge.activate()
        self.orb = self.ui.mini.findChild(QObject, "energyOrb")
        if self.orb is None:
            self.finish("Energy orb not found")
            return
        self.process = psutil.Process()
        self.process.cpu_percent()
        self.motion_start = time.perf_counter()
        self.frame_start = self.orb.property("frameCount")
        QTimer.singleShot(3000, self._measure_motion)

    def _measure_motion(self):
        if self.finished:
            return
        elapsed = time.perf_counter() - self.motion_start
        frames = self.orb.property("frameCount") - self.frame_start
        self.report["motion"] = dict(
            elapsed_seconds=round(elapsed, 3), frames=frames,
            frame_updates_per_second=round(frames / elapsed, 1),
            process_cpu_percent_one_core=self.process.cpu_percent(),
            memory_mb=round(self.process.memory_info().rss / 1024**2, 1),
            gpu=self.orb.property("gpuAvailable"),
        )
        (self.output / "frames").mkdir(parents=True, exist_ok=True)
        self.motion_timer.start()

    def _sample_motion(self):
        image = self.ui.mini.grabWindow()
        filename = self.output / "frames" / f"{len(self.samples):03}.png"
        if image.isNull() or not image.save(str(filename)):
            self.finish("Motion frame capture failed")
            return
        self.samples.append(float(self.orb.property("time")))
        if len(self.samples) == 40:
            self.motion_timer.stop()
            self.report["motion"]["sample_times"] = self.samples
            self.report["motion"]["continuous"] = all(b > a for a, b in zip(self.samples, self.samples[1:]))
            self.ui.mini.hide()
            QTimer.singleShot(100, self._hidden_baseline)

    def _hidden_baseline(self):
        if self.finished:
            return
        self.hidden_time = self.orb.property("time")
        QTimer.singleShot(350, self._check_hidden)

    def _check_hidden(self):
        if self.finished:
            return
        self.report["motion"]["paused_when_hidden"] = self.orb.property("time") == self.hidden_time
        self.ui.pair.showWindows()
        QTimer.singleShot(350, self.finish)

    def finish(self, error=None):
        if self.finished:
            return
        self.finished = True
        self.timeout.stop()
        self.capture_timer.stop()
        self.motion_timer.stop()
        if error:
            self.report["errors"].append(str(error))
        try:
            self.report.update(self.ui.capture(self.output))
            mini = self.report["geometries"]["mini"]
            chat = self.report["geometries"]["chat"]
            checks = {
                "motion_continuous": self.report.get("motion", {}).get("continuous", False),
                "hidden_animation_paused": self.report.get("motion", {}).get("paused_when_hidden", False),
                "shared_height": mini["height"] == chat["height"],
                "shared_top": mini["y"] == chat["y"],
                "exact_width_ratio": chat["width"] == 2 * mini["width"],
                "shared_scale": mini["scale"] == chat["scale"],
                "docked": chat["x"] > mini["x"] + mini["width"],
                "no_qml_errors": not self.ui.qml_errors,
                "cpu_verified": len(self.report["results"]) == 1 and
                    self.report["results"][0].get("status") == "success" and
                    self.report["results"][0].get("verified") is True,
                "result_visible": any(row["userText"] == self.report["command"] and
                    row["verified"] for row in self.ui.bridge.messages.snapshot()),
            }
            for name, geometry in (("mini", mini), ("chat", chat)):
                x, y, width, height = geometry["available"]
                checks[f"{name}_on_screen"] = (x <= geometry["x"] and y <= geometry["y"] and
                    geometry["x"] + geometry["width"] <= x + width and
                    geometry["y"] + geometry["height"] <= y + height)
            self.report["checks"] = checks
            self.report["errors"].extend(name for name, passed in checks.items() if not passed)
        except Exception as exc:
            self.report["errors"].append(f"Capture failed: {type(exc).__name__}: {exc}")
        self.report["qml_errors"] = list(self.ui.qml_errors)
        self.ui.shutdown()
