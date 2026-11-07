from dataclasses import dataclass, field
from typing import Any
import time
from core.models import Intent


@dataclass(frozen=True)
class Question:
    yes: Intent
    expires: float

    def is_active(self) -> bool:
        return time.monotonic() < self.expires

@dataclass
class Context:
    session_id: str = "desktop"
    last_app: str | None = None
    last_window: int | None = None
    last_skill: str | None = None
    last_action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    question: Question | None = None
