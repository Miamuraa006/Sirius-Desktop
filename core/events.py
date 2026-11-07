from enum import StrEnum

class EventType(StrEnum):
    RECOGNIZED = "recognized"
    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"
