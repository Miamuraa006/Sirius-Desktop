"""Vosk streaming STT. No downloads, network clients, audio files or Qt imports."""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Protocol


class ModelUnavailable(RuntimeError):
    """The preinstalled local Vosk model is absent or cannot be loaded."""


class VoskModel:
    """One model per service lifetime, shared by wake and command recognizers."""

    def __init__(self, path: str | Path, *, model_factory=None):
        self.path = Path(path).expanduser()
        self._factory = model_factory
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            path = self.path.absolute()
            if str(path).startswith(("\\\\", "//")):
                raise ModelUnavailable("Для модели Vosk требуется локальная папка, не сетевой путь.")
            try:
                for item in (path, *path.parents):
                    if item.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(item)):
                        raise ModelUnavailable("Ссылки в пути модели Vosk не поддерживаются.")
                for relative in ("am/final.mdl", "conf/model.conf"):
                    target = path / relative
                    if (target.is_symlink() or target.parent.is_symlink() or
                            (hasattr(os.path, "isjunction") and os.path.isjunction(target.parent)) or
                            not target.is_file() or target.stat().st_size == 0):
                        raise ModelUnavailable("Нет полной модели Vosk. Проверьте voice.model_path; автозагрузка отключена.")
                factory = self._factory
                if factory is None:
                    from vosk import Model, SetLogLevel
                    SetLogLevel(-1)
                    factory = Model
                self._model = factory(str(path))
            except ModelUnavailable:
                raise
            except (ImportError, OSError, RuntimeError, ValueError, Exception) as exc:
                raise ModelUnavailable("Не удалось загрузить локальную модель Vosk; проверьте модель и зависимости.") from exc
            return self._model


@dataclass(frozen=True)
class Word:
    text: str
    confidence: float
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Transcript:
    text: str
    words: tuple[Word, ...]

    @property
    def confidence(self) -> float:
        # A single uncertain word can change a destructive command's meaning.
        return min((word.confidence for word in self.words), default=0.0)


class STTAdapter(Protocol):
    def feed(self, pcm: bytes) -> Transcript | None: ...
    def finish(self) -> Transcript | None: ...
    def reset(self) -> None: ...


def _transcript(payload: str) -> Transcript | None:
    try:
        data = json.loads(payload)
        text = data.get("text", "").strip()
        rows = data.get("result", [])
        if not text or not rows or len(text) > 8192 or len(rows) > 1024:
            return None
        words = tuple(Word(row["word"], float(row["conf"]), float(row["start"]), float(row["end"])) for row in rows)
        if any(not isinstance(w.text, str) or not w.text or
               not all(math.isfinite(v) for v in (w.confidence, w.start, w.end)) or
               not 0 <= w.confidence <= 1 or not 0 <= w.start < w.end for w in words):
            return None
        if text != " ".join(w.text for w in words):
            return None
        return Transcript(text, words)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


class VoskSTT:
    """Single-consumer adapter; create/feed/reset on the voice worker thread."""

    def __init__(self, model, sample_rate: int = 16000, *, grammar: list[str] | None = None,
                 recognizer_factory=None):
        if recognizer_factory is None:
            from vosk import KaldiRecognizer
            recognizer_factory = KaldiRecognizer
        args = (model, sample_rate)
        if grammar is not None:
            args += (json.dumps(grammar, ensure_ascii=False),)
        self.native = recognizer_factory(*args)
        self.ended = False
        self.native.SetWords(True)
        # Recent Vosk builds support tuning; 0.3.45 uses its model defaults.
        if hasattr(self.native, "SetEndpointerDelays"):
            self.native.SetEndpointerDelays(4.0, .55, 12.0)

    def feed(self, pcm: bytes) -> Transcript | None:
        if not pcm or len(pcm) % 2:
            return None
        self.ended = bool(self.native.AcceptWaveform(pcm))
        if self.ended:
            return _transcript(self.native.Result())
        return None

    def finish(self) -> Transcript | None:
        return _transcript(self.native.FinalResult())

    def reset(self) -> None:
        self.ended = False
        self.native.Reset()
