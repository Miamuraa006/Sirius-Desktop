"""Typed public contracts. Success is impossible without explicit readback."""
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Status = Literal["success", "failed", "unsupported", "needs_confirmation", "not_understood"]

@dataclass(frozen=True)
class Command:
    text: str
    source: str = "text"
    session_id: str = "desktop"

    def __post_init__(self):
        if not isinstance(self.text, str) or len(self.text) > 16384:
            raise ValueError("Недопустимая длина команды")
        if self.source not in ("voice", "text"):
            raise ValueError("Недопустимый источник команды")
        if not isinstance(self.session_id, str) or not 0 < len(self.session_id) <= 128:
            raise ValueError("Недопустимая сессия")

@dataclass(frozen=True)
class Intent:
    skill: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    context_reference: str | None = None

@dataclass(frozen=True)
class Result:
    status: Status
    message: str
    verified: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ("success", "failed", "unsupported", "needs_confirmation", "not_understood"):
            raise ValueError("Invalid status")
        if self.status == "success" and self.verified is not True:
            raise ValueError("success requires verified readback")
        if self.verified and self.status != "success":
            raise ValueError("Only success may be verified")

    @classmethod
    def ok(cls, message: str, **details):
        return cls("success", message, True, details)

    @classmethod
    def fail(cls, message: str, **details):
        return cls("failed", message, False, details)

    @classmethod
    def unsupported(cls, message: str, **details):
        return cls("unsupported", message, False, details)

    def to_dict(self):
        return asdict(self)
