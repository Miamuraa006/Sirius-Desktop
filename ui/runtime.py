"""Own voice/hotkey lifecycle off Qt, and join every owned executor on exit."""
from concurrent.futures import ThreadPoolExecutor
import logging

from PySide6.QtCore import QObject, Qt, Signal, Slot

LOG = logging.getLogger(__name__)


class ApplicationRuntime(QObject):
    finished = Signal()
    _servicesStopped = Signal(object)

    def __init__(self, ui, config, *, no_voice=False, voice_factory=None, hotkey_factory=None):
        super().__init__(ui)
        self.ui, self.bridge, self.config = ui, ui.bridge, config
        self.no_voice = bool(no_voice)
        self._voice_factory, self._hotkey_factory = voice_factory, hotkey_factory
        self._voice = self._hotkey = None
        self._started = self._closing = self._services_closed = False
        self.is_closed = False
        self.shutdown_errors = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sirius-services")
        self._servicesStopped.connect(self._on_stopped, Qt.QueuedConnection)
        ui.shutdownRequested.connect(self.shutdown)
        self.bridge.closedChanged.connect(self._finish_if_closed)
        self.bridge.readyChanged.connect(self._on_ready)
        self.bridge.activationRequested.connect(self.activate)
        self.bridge.commandFinished.connect(self._command_finished)
        ui.microphoneRequested.connect(self.set_enabled)
        ui.set_microphone_enabled(not self.no_voice and config.get("voice", {}).get("enabled", True))
        if self.no_voice:
            for name in ("microphone", "activate"):
                if name in ui.actions:
                    ui.actions[name].setEnabled(False)
        self._on_ready()

    @Slot()
    def _on_ready(self):
        if self.bridge.ready and not self._started and not self._closing and not self.no_voice:
            self._started = True
            self._pool.submit(self._start_services)

    def _start_services(self):
        try:
            from voice.service import VoiceService
            from voice.hotkey import GlobalHotkey
            # Construct the hotkey first: validation must fail before a microphone
            # stream is opened when config contains an unusable registration.
            hotkey = self.config.get("hotkey", {})
            self._hotkey = (self._hotkey_factory or GlobalHotkey)(
                self.bridge.offer_activation, modifiers=hotkey.get("modifiers", 1),
                key=hotkey.get("key", 77), on_error=self.bridge.offer_notice)
            self._voice = (self._voice_factory or VoiceService)(
                self.config, self.bridge.offer_voice_text, self.bridge.offer_voice_state,
                self.bridge.offer_voice_level, self.bridge.recognizes_voice,
                on_error=self.bridge.offer_notice)
            self._voice.start()
            self._hotkey.start()
        except Exception as exc:
            LOG.error("Voice/hotkey startup failed: %s", type(exc).__name__)
            voice = getattr(self, "_voice", None)
            hotkey_instance = getattr(self, "_hotkey", None)
            if voice is not None:
                try:
                    voice.stop()
                except Exception:
                    pass
            if hotkey_instance is not None and hotkey_instance.running:
                try:
                    hotkey_instance.stop()
                except Exception:
                    pass
            self.bridge.offer_voice_state("error")
            self.bridge.offer_notice("Голос или глобальная клавиша недоступны. Текстовые команды работают.")

    def _voice_call(self, method, *args):
        if self._voice is None:
            return
        try:
            getattr(self._voice, method)(*args)
        except Exception as exc:
            LOG.error("Voice control failed: %s", type(exc).__name__)
            self.bridge.offer_voice_state("error")
            self.bridge.offer_notice("Не удалось изменить состояние голоса.")

    @Slot()
    def activate(self):
        if self._closing:
            return
        if self.no_voice:
            self.bridge.offer_notice("Голос отключён параметром --no-voice.")
        elif self._started:
            self._pool.submit(self._voice_call, "activate")

    @Slot(bool)
    def set_enabled(self, enabled):
        if not self._closing and self._started and not self.no_voice:
            self._pool.submit(self._voice_call, "set_enabled", bool(enabled))

    @Slot(object)
    def _command_finished(self, result):
        if self._closing or not self._started:
            return
        if result.get("source") == "voice":
            recognized = result.get("status") not in {"not_understood", "cancelled"}
            prompt = result.get("details", {}).get("spoken_question")
            self._pool.submit(self._finish_voice_command, recognized, prompt)
        elif result.get("status") == "needs_confirmation" or result.get("details", {}).get("presentation") == "question":
            self._pool.submit(self._voice_call, "activate")

    def _finish_voice_command(self, recognized, prompt):
        try:
            if prompt and not self._closing:
                from voice.questions import speak_question
                speak_question(prompt)
        finally:
            self._voice_call("command_completed", recognized)

    @Slot()
    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._pool.submit(self._stop_services)
        self._pool.shutdown(wait=False)

    def _stop_services(self):
        errors = []
        for name, service in (("hotkey", self._hotkey), ("voice", self._voice)):
            if service is None:
                continue
            try:
                service.stop()
                if service.running:
                    errors.append(f"{name} worker did not stop")
            except Exception as exc:
                errors.append(f"{name} stop: {type(exc).__name__}")
        self._servicesStopped.emit(errors)

    @Slot(object)
    def _on_stopped(self, errors):
        self._pool.shutdown(wait=True)
        self.shutdown_errors.extend(errors)
        self._services_closed = True
        self._finish_if_closed()

    @Slot()
    def _finish_if_closed(self):
        if self._closing and self._services_closed and self.bridge.isClosed and not self.is_closed:
            self.is_closed = True
            self.finished.emit()
