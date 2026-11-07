"""Monotonic activation window; deliberately independent of Qt and audio."""
from __future__ import annotations

import math
import time
from collections.abc import Callable


class ActivationState:
    """Caller serializes mutations; elapsed wall-clock time is never used."""

    def __init__(self, active_seconds: float = 60.0, *, clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(active_seconds) or active_seconds <= 0:
            raise ValueError("active_seconds must be finite and positive")
        self.active_seconds = float(active_seconds)
        self.clock = clock
        self.state = "idle"
        self.deadline: float | None = None
        self.enabled = True

    def activate(self) -> bool:
        if not self.enabled or self.state == "processing":
            return False
        self.state = "listening"
        self.deadline = self.clock() + self.active_seconds
        return True

    def command_accepted(self) -> bool:
        if not self.enabled or self.tick() != "listening":
            return False
        self.state = "processing"
        return True

    def command_completed(self, recognized: bool = True) -> None:
        if not self.enabled or self.state != "processing":
            return
        self.state = "listening"
        if recognized:
            self.deadline = self.clock() + self.active_seconds
        self.tick()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if not self.enabled:
            self.state = "idle"
            self.deadline = None

    def tick(self) -> str:
        if self.state == "listening" and self.deadline is not None and self.clock() >= self.deadline:
            self.state = "idle"
            self.deadline = None
        return self.state
