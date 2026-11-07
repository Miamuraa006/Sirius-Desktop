"""UI-neutral offline voice service; every native/audio/model call is off the UI.

Callbacks must be quick and thread-safe (the Qt bridge emits queued signals).
Only final, confident, router-recognized commands reach on_text. The core owns
execution/history; it calls command_completed after the accepted command ends.
"""
from __future__ import annotations

import math
import logging
import threading
import time
from pathlib import Path

from voice.activation_state import ActivationState
from voice.audio_input import AudioInput, CAPTURE, DIAGNOSTIC, SpeechMarker, speech_marker_set
from voice.normalization import normalize_command
from core.activation import split_address
from voice.stt import ModelUnavailable, VoskModel
from voice.help_stt import HelpAwareSTT
from voice.wake_word import VoskWakeWord

LOG = logging.getLogger(__name__)


class VoiceService:
    def __init__(self, config, on_text, on_state, on_level, is_recognized, *, on_error=None,
                 clock=time.monotonic, adapters_factory=None, audio_factory=None):
        settings = config.get("voice", config)
        self._settings = dict(settings)
        self._on_text = on_text
        self._on_state = on_state
        self._on_level = on_level
        self._on_error = on_error
        self._recognizes = is_recognized
        self._lock = threading.RLock()
        # One reentrant lock: callbacks may request enable/stop synchronously.
        # Separate lifecycle/state locks allow lock-order inversion on errors.
        self._lifecycle = self._lock
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._thread = None
        self._started = False
        self._fsm = ActivationState(float(settings.get("active_seconds", 60)), clock=clock)
        self._enabled = settings.get("enabled", True) is True
        self._fsm.set_enabled(self._enabled)
        self._confidence = float(settings.get("min_confidence", .65))
        if not math.isfinite(self._confidence) or not 0 <= self._confidence <= 1:
            raise ValueError("voice.min_confidence must be in [0, 1]")
        self._sample_rate = int(settings.get("sample_rate", 16000))
        if not 8000 <= self._sample_rate <= 48000:
            raise ValueError("voice.sample_rate must be between 8000 and 48000")
        if settings.get('command_decoder', 'auto') != 'vosk':
            self._sample_rate = 16000
        root = Path(config.get("_resource_root", Path(__file__).resolve().parents[1]))
        model_path = Path(settings.get("model_path", "models/ru_vosk"))
        self._config = config
        self._root = root
        self._model = VoskModel(model_path if model_path.is_absolute() else root / model_path)
        self._adapters_factory = adapters_factory or self._make_adapters
        self._audio_factory = audio_factory or AudioInput
        self._audio = None
        self._coordinate = audio_factory is None
        self._capture_after = 0.
        self._epoch = 0
        self._last_published = None
        self._speech_seen = False
        self._quiet_blocks = 0
        self._fault = False
        self._last_error = None
        self._last_level = 0.0
        self._exiting = False
        self._restart_requested = False

    def _make_adapters(self):
        model = self._model.load()
        return (VoskWakeWord(model, self._sample_rate),
                HelpAwareSTT(model, self._sample_rate, expects_reply=lambda: self._recognizes('да')))

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        with self._lock:
            return "error" if self._fault and self._enabled else self._fsm.state

    @property
    def deadline(self) -> float | None:
        with self._lock:
            return self._fsm.deadline

    def _notify(self, callback, value) -> None:
        if callback is not None:
            with self._lock:
                try:
                    callback(value)
                except Exception:
                    pass

    def _publish(self) -> None:
        state = self.state
        if state != self._last_published:
            self._last_published = state
            LOG.info("Voice state: %s", state)
            self._notify(self._on_state, state)

    def _error(self, message: str) -> None:
        with self._lock:
            if self._stop.is_set() or not self._enabled:
                return
            self._fault = True
            self._publish()
            if message != self._last_error:
                self._last_error = message
                self._notify(self._on_error, message)

    def _connection(self, connected: bool) -> None:
        with self._lock:
            if self._stop.is_set() or not self._enabled:
                return
            self._fault = not connected
            if connected:
                self._last_error = None
            self._epoch += 1
            self._publish()

    def start(self):
        with self._lifecycle:
            if self.running:
                return self
            self._started = True
            with self._lock:
                self._stop.clear()
                self._exiting = False
                self._restart_requested = False
                self._fsm.set_enabled(self._enabled)
                self._fault = False
                self._last_error = None
                self._epoch += 1
                self._publish()
            self._thread = threading.Thread(target=self._run, name="SiriusVoice", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        with self._lifecycle:
            with self._lock:
                self._stop.set()
                self._restart_requested = False
                self._changed.set()
                self._fsm.set_enabled(False)
                self._fault = False
                self._epoch += 1
                self._publish()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.5)
        self._notify(self._on_level, 0.0)
        if self.running and thread is not threading.current_thread():
            self._notify(self._on_error, "Голосовой поток ещё завершает локальную операцию.")

    def activate(self, *, after=None) -> None:
        with self._lock:
            if self._stop.is_set() or not self._enabled:
                return
            if self._fsm.activate():
                self._capture_after = time.monotonic() - .48 if after is None else after
                self._epoch += 1
                self._publish()
                self._changed.set()

    def command_completed(self, recognized: bool = True) -> None:
        with self._lock:
            if self._stop.is_set() or self._fsm.state != "processing":
                return
            self._capture_after = time.monotonic()
            self._fsm.command_completed(recognized is True)
            self._epoch += 1
            self._publish()
            self._changed.set()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled is True
            self._fsm.set_enabled(self._enabled)
            self._fault = False
            self._epoch += 1
            self._publish()
            self._changed.set()
            # Never open capture before first start or after explicit shutdown.
            # A retry received during failed-worker teardown must not be lost.
            if self._enabled and self._started and not self._stop.is_set():
                if self._exiting and self.running:
                    self._restart_requested = True
                else:
                    self.start()

    def _wait(self, timeout=.1) -> None:
        self._changed.wait(timeout)
        self._changed.clear()

    def _ensure_audio(self):
        if self._audio is None:
            self._audio = self._audio_factory(device=self._settings.get("device"),
                sample_rate=self._sample_rate, blocksize=self._sample_rate // 20,
                on_error=self._error, on_connection=self._connection)
        if not self._audio.running:
            self._audio.start()

    def _run(self) -> None:
        adapters = None
        epoch = -1
        generation = None
        retry = 1.0
        capture_marker = None
        previous_mode = None
        try:
            while not self._stop.is_set():
                with self._lock:
                    enabled = self._enabled
                if not enabled or (self._coordinate and speech_marker_set(DIAGNOSTIC)):
                    if self._audio is not None and self._audio.running:
                        self._audio.stop()
                        with self._lock:
                            self._capture_after = time.monotonic()
                            self._epoch += 1
                    if capture_marker is not None:
                        capture_marker.close()
                        capture_marker = None
                    self._wait()
                    continue
                if self._coordinate and capture_marker is None:
                    capture_marker = SpeechMarker(CAPTURE)
                    if speech_marker_set(DIAGNOSTIC):
                        continue
                if self._coordinate:
                    self._ensure_audio()  # Capture while the selected CPU model warms up.
                if adapters is None:
                    try:
                        adapters = self._adapters_factory()
                        retry = 1.0
                    except Exception as exc:
                        self._error(str(exc) if isinstance(exc, ModelUnavailable) else
                                    "Не удалось запустить выбранный локальный распознаватель.")
                        self._wait(retry)
                        retry = min(retry * 2, 30.0)
                        continue
                if self._stop.is_set():
                    break
                with self._lock:
                    if not self._enabled:
                        continue
                self._ensure_audio()
                wake, stt = adapters
                with self._lock:
                    previous = self._fsm.state
                    mode = self._fsm.tick()
                    if mode != previous:
                        self._epoch += 1
                        self._publish()
                    current_epoch = self._epoch
                if current_epoch != epoch:
                    if not isinstance(self._audio, AudioInput):
                        self._audio.clear()
                    # Keep a shared Silero pre-roll across hotkey activation; a new connection
                    # or completion of an action always starts a fresh recognition epoch.
                    if wake is not stt or (previous_mode, mode) != ('idle', 'listening'):
                        wake.reset()
                        if wake is not stt:
                            stt.reset()
                    self._speech_seen = False
                    self._quiet_blocks = 0
                    epoch = current_epoch
                    previous_mode = mode
                frame = self._audio.read(.05)
                if frame is None or not frame.pcm:
                    continue
                with self._lock:
                    if self._stop.is_set() or not self._enabled or self._epoch != epoch:
                        continue
                if self._coordinate and frame.captured_at < self._capture_after:
                    continue
                if frame.generation != generation:
                    if generation is not None and wake is stt:
                        stt.interrupted()
                    else:
                        wake.reset()
                        if wake is not stt:
                            stt.reset()
                    generation = frame.generation
                if mode == "idle":
                    candidate = wake.feed(frame.pcm, wake=True) if wake is stt else wake.feed(frame.pcm)
                    if wake is stt:
                        if candidate is None or candidate.confidence < self._confidence:
                            continue
                        addressed, tail = split_address(candidate.text.strip())
                        if not addressed:
                            continue
                    elif not candidate:
                        continue
                    else:
                        tail = ''
                    with self._lock:
                        if self._epoch != epoch:
                            continue
                        self.activate(after=frame.captured_at)
                        activated_epoch = self._epoch
                    if not tail:
                        continue
                    epoch = activated_epoch
                    result = type(candidate)(normalize_command(tail), candidate.words)
                elif mode == "listening":
                    self._meter(frame.pcm)
                    if self._coordinate:
                        samples = memoryview(frame.pcm).cast('h')[::8]
                        rms = math.sqrt(sum(int(v)**2 for v in samples) / max(1, len(samples)))
                        if rms >= 100:
                            if self._quiet_blocks >= 4:
                                self._notify(self._on_state, 'listening')
                            self._speech_seen = True
                            self._quiet_blocks = 0
                        elif self._speech_seen:
                            self._quiet_blocks += 1
                            if self._quiet_blocks == 4:
                                self._notify(self._on_state, 'decoding')
                            elif self._quiet_blocks >= 30:
                                self._notify(self._on_state, 'not_understood')
                                self._speech_seen = False
                    result = stt.feed(frame.pcm)
                    if result is not None:
                        result = type(result)(normalize_command(result.text), result.words)
                else:
                    continue
                if result is not None:
                    self._speech_seen = False
                    # On the owner's recording Vosk confidently hears the launch verb
                    # but gives the Steam name 0.61. This exception can only open Steam.
                    steam_launch = (result.text.casefold() == 'открой steam' and len(result.words) == 2
                                    and result.words[0].confidence >= .90 and result.confidence >= .60)
                    if not result.text or (result.confidence < self._confidence and not steam_launch) or "[unk]" in result.text:
                        self._notify(self._on_state, "not_understood")
                        continue
                    self._notify(self._on_state, "processing")
                    if not self._recognizes(result.text):
                        self._notify(self._on_state, "not_understood")
                        continue
                    with self._lock:
                        if (self._stop.is_set() or self._epoch != epoch or
                                self._coordinate and speech_marker_set(DIAGNOSTIC) or
                                not self._fsm.command_accepted()):
                            continue
                        self._epoch += 1
                        self._publish()
                        try:
                            self._on_text(result.text)
                        except Exception:
                            self._fsm.command_completed(False)
                            self._error("Не удалось передать распознанную команду ядру.")
        except Exception:
            with self._lock:
                self._exiting = True
                self._restart_requested = False
                self._fsm.set_enabled(False)
            self._error("Ошибка голосового потока; выключите и снова включите микрофон.")
        finally:
            try:
                if self._audio is not None:
                    self._audio.stop()
            finally:
                if capture_marker is not None:
                    capture_marker.close()
                self._notify(self._on_level, 0.0)
                with self._lifecycle:
                    if self._thread is threading.current_thread():
                        self._thread = None
                    if (self._restart_requested and self._enabled and not self._stop.is_set()
                            and (self._audio is None or not self._audio.running)):
                        # Native cleanup has completed; no old capture survives.
                        self.start()

    def _meter(self, pcm: bytes) -> None:
        now = time.monotonic()
        if now - self._last_level < .1 or len(pcm) % 2:
            return
        self._last_level = now
        samples = memoryview(pcm).cast("h")[::8]
        rms = math.sqrt(sum(int(x) ** 2 for x in samples) / max(1, len(samples)))
        self._notify(self._on_level, min(1.0, rms / 9000.0))
