"""Narrow Vosk wake grammar, NOT a trained or speaker-personalized wake model.

Only a final isolated «сириус» with confidence and acoustic dwell is accepted.
The narrow grammar proposes candidates; a full-vocabulary second pass must
agree. [unk] alone does NOT prevent forced high-confidence matches on this
Russian model. Verification only decodes bounded RAM audio on candidates.
Common legacy aliases such as «сервис»/«серия» are deliberately not wake words.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from voice.stt import Transcript, VoskSTT
from core.activation import WAKE_WORDS


class WakeWordAdapter(Protocol):
    def feed(self, pcm: bytes) -> bool: ...
    def reset(self) -> None: ...


@dataclass(frozen=True)
class WakeFilter:
    min_confidence: float = .85
    min_duration: float = .18
    max_duration: float = 1.8

    def accepts(self, result: Transcript | None) -> bool:
        if result is None or result.text.casefold() not in WAKE_WORDS or len(result.words) != 1:
            return False
        word = result.words[0]
        return (word.text.casefold() in WAKE_WORDS and word.confidence >= self.min_confidence and
                self.min_duration <= word.duration <= self.max_duration)


class VoskWakeWord:
    def __init__(self, model, sample_rate: int = 16000, *, recognizer_factory=None,
                 wake_filter: WakeFilter | None = None):
        self.stt = VoskSTT(model, sample_rate, grammar=["сириус", "[unk]"],
                           recognizer_factory=recognizer_factory)
        self.filter = wake_filter or WakeFilter()
        # Independent confirmation still requires the exact name. Its confidence
        # is calibrated separately: the full lexicon competes with many words.
        self.confirmation_filter = WakeFilter(min_confidence=.60)
        self.last_result: Transcript | None = None
        self.last_verification: Transcript | None = None
        self.verification_wall_seconds = 0.0
        self._model = model
        self._sample_rate = sample_rate
        self._recognizer_factory = recognizer_factory
        self._verifier = None
        self._buffer = bytearray()
        self._buffer_limit = sample_rate * 2 * 6
        self._samples_seen = 0

    def feed(self, pcm: bytes) -> bool:
        self.last_verification = None
        self.verification_wall_seconds = 0.0
        if pcm and len(pcm) % 2 == 0:
            self._samples_seen += len(pcm) // 2
            self._buffer.extend(pcm[-self._buffer_limit:])
            if len(self._buffer) > self._buffer_limit:
                del self._buffer[:-self._buffer_limit]
        self.last_result = self.stt.feed(pcm)
        if self.last_result is None:
            return False
        try:
            if not self.filter.accepts(self.last_result):
                return False
            before = time.perf_counter()
            if self._verifier is None:
                self._verifier = VoskSTT(self._model, self._sample_rate,
                                       recognizer_factory=self._recognizer_factory)
            else:
                self._verifier.reset()
            results = []
            step = self._sample_rate // 20 * 2
            # Vosk timestamps are relative to its last reset, not this ring buffer.
            # Isolate the actual name; unrelated preceding sound must not veto it.
            first = self.last_result.words[0]
            buffer_start = self._samples_seen - len(self._buffer) // 2
            begin = max(0, int((first.start - .20) * self._sample_rate) - buffer_start) * 2
            end = min(len(self._buffer), max(0, int((first.end + .30) * self._sample_rate) - buffer_start) * 2)
            segment = self._buffer[begin:end]
            # Injected adapters may return synthetic timestamps beyond their PCM.
            if not segment:
                segment = self._buffer
            for start in range(0, len(segment), step):
                result = self._verifier.feed(bytes(segment[start:start + step]))
                if result is not None:
                    results.append(result)
            final = self._verifier.finish()
            if final is not None:
                results.append(final)
            if results:
                self.last_verification = Transcript(" ".join(result.text for result in results),
                                                   tuple(word for result in results for word in result.words))
            self.verification_wall_seconds = time.perf_counter() - before
            return self.confirmation_filter.accepts(self.last_verification)
        finally:
            self._buffer.clear()

    def reset(self) -> None:
        self.stt.reset()
        self.last_result = None
        self.last_verification = None
        self.verification_wall_seconds = 0.0
        self._buffer.clear()
        self._samples_seen = 0
        if self._verifier is not None:
            self._verifier.reset()
