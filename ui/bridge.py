"""Qt-only bridge. The Engine and its storage live on ONE serial worker."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
import math
import time

from PySide6.QtCore import QObject, Property, Qt, QThread, QTimer, Signal, Slot

from ui.messages import MessageModel
from ui.presence import Presence
from core.activation import split_address

LOG = logging.getLogger(__name__)


def _command(**kwargs):
    from core.models import Command
    return Command(**kwargs)


def _result_dict(result):
    if isinstance(result, dict):
        return dict(result)
    return {key: getattr(result, key, default) for key, default in
            (("status", "failed"), ("message", ""), ("verified", False), ("details", {}))}


class Bridge(QObject):
    readyChanged = Signal()
    busyChanged = Signal()
    visualStateChanged = Signal()
    audioLevelChanged = Signal()
    closedChanged = Signal()
    commandFinished = Signal(object)
    activationRequested = Signal()
    diagnostic = Signal(str)
    historyCleared = Signal()
    chatRequested = Signal(bool, arguments=["isHelp"])
    _eventArrived = Signal(int, object)
    _booted = Signal(object)
    _completed = Signal(int, object)
    _closed = Signal()
    _cleared = Signal(bool)
    _voiceText = Signal(str)
    _voiceState = Signal(str)
    _voiceLevel = Signal(float)
    _activation = Signal()
    _notice = Signal(str)

    def __init__(self, engine_factory, *, command_factory=None, target_provider=None, parent=None):
        super().__init__(parent)
        self._messages = MessageModel(self)
        self._presence = Presence(self)
        self._ready = False
        self._initialized = False
        self._closing = False
        self._is_closed = False
        self._pending = set()
        self._sequence = 0
        self._active_id = 0
        self._engine = None
        self._state = "idle"
        self._voice_state = "idle"
        self._level = 0.0
        self._engine_factory = engine_factory
        self._command_factory = command_factory or _command
        self._target_provider = target_provider
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sirius-engine")
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(1800)
        self._settle.timeout.connect(self._restore_state)
        for signal, slot in ((self._eventArrived, self._on_event), (self._booted, self._on_booted),
                             (self._completed, self._on_completed), (self._closed, self._on_closed),
                             (self._cleared, self._on_cleared), (self._voiceText, self._on_voice_text),
                             (self._voiceState, self._on_voice_state), (self._voiceLevel, self._on_voice_level),
                             (self._activation, self.activate), (self._notice, self._on_notice)):
            signal.connect(slot, Qt.QueuedConnection)
        self._pool.submit(self._bootstrap)

    @Property(QObject, constant=True)
    def messages(self):
        return self._messages

    @Property(QObject, constant=True)
    def presence(self):
        return self._presence

    @Property(bool, notify=readyChanged)
    def ready(self):
        return self._ready and not self._closing

    @Property(bool, notify=readyChanged)
    def initialized(self):
        return self._initialized

    @Property(bool, notify=busyChanged)
    def busy(self):
        return bool(self._pending)

    @Property(str, notify=visualStateChanged)
    def visualState(self):
        return self._state

    @Property(float, notify=audioLevelChanged)
    def audioLevel(self):
        return self._level

    @Property(bool, notify=closedChanged)
    def isClosed(self):
        return self._is_closed

    def _bootstrap(self):
        try:
            self._engine = self._engine_factory(self._receive_engine_event)
            rows = self._engine.history.recent(limit=200)
            self._booted.emit({"ok": True, "history": rows})
        except Exception as exc:
            LOG.error("Engine initialization failed: %s", type(exc).__name__)
            self._booted.emit({"ok": False, "history": []})

    @Slot(object)
    def _on_booted(self, payload):
        if self._closing:
            return
        self._messages.load(payload["history"])
        self._initialized = True
        self._ready = payload["ok"]
        self.readyChanged.emit()
        if not self._ready:
            self._set_state("error")
            self.diagnostic.emit("Не удалось запустить ядро. Подробности в локальном журнале.")

    def _receive_engine_event(self, event):
        # Never pass raw submitted text to the model: core emits redacted events.
        self._eventArrived.emit(self._active_id, dict(event))

    @Slot(str, result=bool)
    def submit(self, text):
        if not self.ready or not isinstance(text, str) or not text.strip() or len(text) > 16000:
            return False
        addressed, command = split_address(text)
        if addressed:
            self.activate()
            if not command:
                # A wake acknowledgement is a UI interaction, not a Windows skill.
                self._sequence += 1
                self._messages.append_event(self._sequence, {
                    "text": text.strip(), "source": "text", "time": datetime.now().astimezone().isoformat(),
                })
                self._messages.finish(self._sequence, {
                    "status": "success", "verified": True, "message": "Я здесь. Слушаю.",
                })
                return True
            text = command
        return self._enqueue(text, "text")

    def _enqueue(self, text, source):
        if not self.ready or not isinstance(text, str) or not text.strip() or len(text) > 16000:
            return False
        if len(self._pending) >= 16:
            self.diagnostic.emit("Очередь команд заполнена. Дождитесь завершения.")
            return False
        self._sequence += 1
        sequence = self._sequence
        self._pending.add(sequence)
        if source == "text" and self._presence.awake:
            self._presence.wake()
        self._presence.set_busy(True)
        self.busyChanged.emit()
        # Snapshot a HWND/PID only; no window titles or document contents.
        target = self._target_provider() if self._target_provider else None
        self._pool.submit(self._execute, sequence, text, source, target)
        return True

    def _execute(self, sequence, text, source, target):
        if self._closing:
            self._completed.emit(sequence, {"status": "cancelled", "message": "", "verified": False})
            return
        self._active_id = sequence
        start = time.monotonic()
        try:
            if target:
                self._engine.set_window_context(hwnd=target["hwnd"], pid=target.get("pid"), session_id="desktop")
            result = _result_dict(self._engine.execute(self._command_factory(text=text, source=source, session_id="desktop")))
        except Exception as exc:
            LOG.error("Command worker failed: %s", type(exc).__name__)
            result = {"status": "failed", "message": "Ошибка исполнения команды. Подробности в локальном журнале.", "verified": False}
        result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
        result["source"] = source
        self._completed.emit(sequence, result)
        self._active_id = 0

    @Slot(int, object)
    def _on_event(self, sequence, event):
        if self._closing:
            return
        kind = event.get("type")
        if kind == "recognized":
            self._messages.append_event(sequence, event)
            self._set_state("processing")
        elif kind == "started":
            self._set_state("executing")
        elif kind in ("completed", "error") and isinstance(event.get("result"), dict):
            self._messages.finish(sequence, event["result"])

    @Slot(int, object)
    def _on_completed(self, sequence, result):
        self._pending.discard(sequence)
        # Refresh an already active conversation before releasing its busy hold.
        if not self._closing and result.get("source") == "text" and self._presence.awake:
            self._presence.wake()
        self._presence.set_busy(bool(self._pending))
        self.busyChanged.emit()
        if self._closing:
            return
        self._messages.finish(sequence, result)
        status = result.get("status")
        if status == "success" and result.get("verified") is True:
            self._set_state("success")
        elif status == "needs_confirmation":
            self._set_state("processing")
        elif status != "not_understood" or result.get("source") != "voice":
            self._set_state("error")
        self._settle.start()
        self.commandFinished.emit(result)
        presentation = result.get("details", {}).get("presentation")
        if presentation in {"help", "question"}:
            self.chatRequested.emit(presentation == "help")

    def _set_state(self, state):
        if self._state != state:
            self._state = state
            self.visualStateChanged.emit()

    @Slot()
    def _restore_state(self):
        self._set_state("executing" if self.busy else self._voice_state)

    # These are the ONLY entry points permitted from voice/hotkey worker threads.
    def recognizes_voice(self, text):
        # A synchronous probe is allowed on the audio worker, never on Qt's GUI.
        if self._closing or not self._ready or QThread.currentThread() == self.thread():
            return False
        try:
            future = self._pool.submit(self._engine.recognizes, text, session_id="desktop")
            return bool(future.result(timeout=2.0))
        except Exception:
            return False

    def offer_voice_text(self, text):
        self._voiceText.emit(text)

    def offer_voice_state(self, state):
        self._voiceState.emit(state)

    def offer_voice_level(self, level):
        self._voiceLevel.emit(float(level))

    def offer_activation(self):
        self._activation.emit()

    def offer_notice(self, text):
        self._notice.emit(text)

    @Slot(str)
    def _on_notice(self, text):
        if not self._closing:
            self.diagnostic.emit(text)

    @Slot(str)
    def _on_voice_text(self, text):
        if not self._enqueue(text, "voice"):
            # Release the voice FSM without persisting the rejected utterance.
            self.commandFinished.emit({"source":"voice","status":"cancelled","verified":False,"message":""})

    @Slot(str)
    def _on_voice_state(self, state):
        if state == "decoding" and not self._closing and not self.busy:
            self._set_state("processing")
            return
        if state == "not_understood" and not self._closing and not self.busy:
            self._voice_state = "listening"
            self._set_state("not_understood")
            self._settle.start(1500)
            return
        if self._closing or state not in {"idle", "listening", "processing", "error"}:
            return
        self._voice_state = state
        self._presence.voice_state(state)
        if not self.busy and not self._settle.isActive():
            self._set_state(state)
        if state != "listening":
            self._on_voice_level(0.0)

    @Slot(float)
    def _on_voice_level(self, level):
        level = max(0.0, min(1.0, level)) if math.isfinite(level) else 0.0
        if self._closing:
            return
        if abs(self._level - level) > .005 or level == 0:
            self._level = level
            self.audioLevelChanged.emit()

    @Slot()
    def activate(self):
        if not self._closing:
            self._presence.wake()
            self.activationRequested.emit()

    @Slot()
    def clearHistory(self):
        if self.ready:
            self._pool.submit(self._clear_history)

    def _clear_history(self):
        try:
            self._engine.history.clear()
            # Read back exact target before clearing displayed local history.
            self._cleared.emit(not self._engine.history.recent(limit=1))
        except Exception as exc:
            LOG.error("History clear failed: %s", type(exc).__name__)
            self._cleared.emit(False)

    @Slot(bool)
    def _on_cleared(self, verified):
        if verified:
            self._messages.clear()
            self.historyCleared.emit()
        else:
            self.diagnostic.emit("Не удалось подтвердить очистку истории.")

    @Slot()
    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._presence.stop()
        self._settle.stop()
        self.readyChanged.emit()
        self._pool.submit(self._close_worker)
        self._pool.shutdown(wait=False)

    def _close_worker(self):
        try:
            if self._engine is not None:
                self._engine.close()
        except Exception as exc:
            LOG.error("Engine shutdown failed: %s", type(exc).__name__)
        finally:
            self._closed.emit()

    @Slot()
    def _on_closed(self):
        # The final task has returned: joining here cannot wait on a skill/audio operation.
        self._pool.shutdown(wait=True)
        self._is_closed = True
        self.closedChanged.emit()
