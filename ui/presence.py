"""Visual presence follows real voice state, with a 60 s fallback for text-only interaction."""
import time
from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot


class Presence(QObject):
    awakeChanged = Signal()

    def __init__(self, parent=None, *, clock=time.monotonic, active_seconds=60.0):
        super().__init__(parent)
        self.clock = clock
        self.active_seconds = active_seconds
        self._deadline = None
        self._voice_active = False
        self._busy = False
        self._awake = False
        self._engaged = False
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.tick)

    @Property(bool, notify=awakeChanged)
    def awake(self):
        return self._awake

    @Slot()
    def wake(self):
        self._engaged = True
        self._deadline = self.clock() + self.active_seconds
        self._timer.start()
        self.tick()

    def voice_state(self, state):
        was_active = self._voice_active
        if state in ("listening", "processing"):
            self._engaged = True
            self._voice_active = True
            # The voice FSM is authoritative once it has acknowledged activation.
            self._deadline = None
        else:
            self._voice_active = False
            if state == "idle" and was_active:
                self._deadline = None
        self.tick()

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.tick()

    @Slot()
    def tick(self):
        if self._deadline is not None and self.clock() >= self._deadline:
            self._deadline = None
        awake = self._engaged and (self._busy or self._voice_active or self._deadline is not None)
        if not awake:
            self._engaged = False
        if awake != self._awake:
            self._awake = awake
            self.awakeChanged.emit()
        if self._deadline is None:
            self._timer.stop()

    def stop(self):
        self._deadline = None
        self._voice_active = self._busy = False
        self._engaged = False
        self._timer.stop()
        self.tick()
