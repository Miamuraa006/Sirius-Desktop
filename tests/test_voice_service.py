import queue
import threading
import time
from importlib import import_module, util

from voice.audio_input import AudioFrame
from voice.stt import Transcript, Word


def service_class():
    assert util.find_spec("voice.service") is not None, "VoiceService missing"
    return import_module("voice.service").VoiceService


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate(), "condition not reached"


class Clock:
    def __init__(self):
        self.now = 100.0
    def __call__(self):
        return self.now


class Audio:
    def __init__(self, **kwargs):
        self.frames = queue.Queue()
        self.running = False
        self.kwargs = kwargs
        self.starts = 0
        self.clears = 0

    def start(self):
        self.running = True
        self.starts += 1
        return self

    def stop(self):
        self.running = False
        self.clear()

    def clear(self):
        self.clears += 1
        while not self.frames.empty():
            self.frames.get_nowait()

    def read(self, timeout=.05):
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def push(self, text, generation=1):
        self.frames.put(AudioFrame(text.encode(), time.monotonic(), generation))


class STT:
    def __init__(self):
        self.seen = []
        self.resets = 0
    def feed(self, pcm):
        text = pcm.decode()
        self.seen.append(text)
        if not text:
            return None
        conf = .2 if text == "тише" else .99
        return Transcript(text, (Word(text, conf, 0, .5),))
    def reset(self):
        self.resets += 1


class Wake:
    def __init__(self):
        self.seen = []
        self.resets = 0
    def feed(self, pcm):
        self.seen.append(pcm.decode())
        return pcm.decode() == "сириус"
    def reset(self):
        self.resets += 1


def harness(**extra):
    texts, states, errors = [], [], []
    audio, stt, wake, clock = Audio(), STT(), Wake(), Clock()
    service = service_class()({"voice": {"enabled": True}}, texts.append, states.append,
                              lambda level: None, lambda text: text in {"громче", "тише"},
                              on_error=errors.append, clock=clock,
                              adapters_factory=lambda: (wake, stt),
                              audio_factory=lambda **kwargs: audio, **extra)
    return service, audio, stt, wake, clock, texts, states, errors


def test_service_routes_only_confident_known_commands_after_wake():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    try:
        service.start()
        wait_for(lambda: audio.running and audio.clears)
        audio.push("громче")
        wait_for(lambda: "громче" in wake.seen)
        assert texts == []
        audio.push("сириус")
        wait_for(lambda: service.state == "listening" and audio.clears >= 2)
        before = list(states)
        deadline = service.deadline
        audio.push("шум")
        audio.push("")
        audio.push("тише")
        wait_for(lambda: "тише" in stt.seen)
        assert texts == []
        assert 'not_understood' in states[len(before):]
        assert service.deadline == deadline
        audio.push("громче")
        wait_for(lambda: texts == ["громче"])
        assert service.state == "processing"
        assert service.deadline == deadline
        clock.now = 170.0
        service.command_completed()
        assert service.deadline == 230.0
        assert service.state == "listening"
        clock.now = 230.0
        wait_for(lambda: service.state == "idle")
        assert errors == []
    finally:
        service.stop()
    assert not audio.running
    assert not service.running


def test_activate_is_ignored_when_microphone_explicitly_disabled():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    try:
        service.set_enabled(False)
        service.start()
        service.activate()
        assert service.state == "idle"
        assert not audio.running
        service.set_enabled(True)
        wait_for(lambda: audio.running)
        service.activate()
        wait_for(lambda: service.state == "listening")
        service.set_enabled(False)
        wait_for(lambda: not audio.running)
        service.command_completed()
        assert service.state == "idle"
        assert service.deadline is None
    finally:
        service.stop()


def test_enable_restarts_worker_after_unexpected_audio_failure():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    original_read = audio.read
    failures = [True]

    def read(timeout=.05):
        if failures:
            failures.pop()
            raise RuntimeError("private driver details")
        return original_read(timeout)

    audio.read = read
    try:
        service.start()
        wait_for(lambda: errors and not service.running)
        assert service.state == "error"
        assert not audio.running
        assert "private" not in errors[0]
        service.set_enabled(True)
        wait_for(lambda: service.running and audio.running and audio.starts == 2 and audio.clears >= 3)
        cleared = audio.clears
        service.activate()
        wait_for(lambda: service.state == "listening" and audio.clears > cleared)
        audio.push("громче")
        wait_for(lambda: texts == ["громче"])
    finally:
        service.stop()
    assert not service.running
    assert not audio.running


def test_configuration_cannot_start_capture_before_start_or_after_stop():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    service.set_enabled(True)
    assert not service.running and audio.starts == 0
    service.start()
    wait_for(lambda: audio.running)
    service.stop()
    service.set_enabled(True)
    service.activate()
    assert not service.running and not audio.running
    assert service.state == "idle"


def test_model_load_is_lazy_off_caller_and_cached_across_restart(tmp_path, monkeypatch):
    module = import_module("voice.service")
    from voice.stt import VoskModel

    for relative in ("am/final.mdl", "conf/model.conf"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test model layout")
    native_loads = []
    monkeypatch.setattr(module, "VoskWakeWord", lambda model, rate: Wake())
    monkeypatch.setattr(module, "HelpAwareSTT", lambda model, rate, **kwargs: STT())
    audio = Audio()
    service = module.VoiceService({"voice": {"enabled": True, "command_decoder": "vosk", "model_path": str(tmp_path)}},
                                 lambda text: None, lambda state: None, lambda level: None,
                                 lambda text: True, audio_factory=lambda **kwargs: audio)
    service._model = VoskModel(tmp_path, model_factory=lambda path: native_loads.append(threading.get_ident()) or object())
    assert native_loads == []
    try:
        service.start()
        wait_for(lambda: audio.running)
        service.stop()
        service.start()
        wait_for(lambda: audio.starts == 2)
        assert len(native_loads) == 1
        assert native_loads[0] != threading.get_ident()
    finally:
        service.stop()


def test_stop_during_model_load_never_opens_capture():
    entered = threading.Event()
    release = threading.Event()
    created = []

    def load():
        entered.set()
        assert release.wait(2)
        return Wake(), STT()

    service = service_class()({"voice": {"enabled": True}}, lambda text: None,
                              lambda state: None, lambda level: None, lambda text: True,
                              adapters_factory=load, audio_factory=lambda **kwargs: created.append(kwargs))
    service.start()
    assert entered.wait(1)
    stopper = threading.Thread(target=service.stop)
    try:
        stopper.start()
        wait_for(lambda: service._stop.is_set())
    finally:
        release.set()
        stopper.join(2)
        service.stop()
    assert not stopper.is_alive() and not service.running
    assert created == []


def test_disable_discards_inflight_recognition_before_text_callback():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    entered = threading.Event()
    release = threading.Event()

    def recognizes(text):
        entered.set()
        assert release.wait(2)
        return True

    service._recognizes = recognizes
    try:
        service.start()
        wait_for(lambda: audio.clears > 0)
        cleared = audio.clears
        service.activate()
        wait_for(lambda: audio.clears > cleared)
        audio.push("громче")
        assert entered.wait(1)
        service.set_enabled(False)
        release.set()
        wait_for(lambda: not audio.running)
        assert texts == []
        assert service.deadline is None
    finally:
        release.set()
        service.stop()


def test_service_notifications_never_overlap_across_threads():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    entered = threading.Event()
    release = threading.Event()
    second = threading.Event()
    overlapped = []

    def level(value):
        entered.set()
        assert release.wait(2)

    def state(value):
        overlapped.append(not release.is_set())
        second.set()

    service._on_level = level
    service._on_state = state
    meter = threading.Thread(target=lambda: service._notify(service._on_level, .1))
    change = threading.Thread(target=lambda: service.set_enabled(False))
    try:
        meter.start()
        assert entered.wait(1)
        change.start()
        second.wait(.1)
    finally:
        release.set()
        meter.join(1)
        change.join(1)
    assert not meter.is_alive() and not change.is_alive()
    assert overlapped == [False]


def test_enable_from_error_callback_waits_for_cleanup_then_restarts():
    service, audio, stt, wake, clock, texts, states, errors = harness()
    original_read = audio.read
    failed = threading.Event()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    original_stop = audio.stop

    def read(timeout=.05):
        if not failed.is_set():
            failed.set()
            raise RuntimeError("decoder failure")
        return original_read(timeout)

    def stop():
        if audio.starts == 1:
            cleanup_entered.set()
            assert release_cleanup.wait(2)
        original_stop()

    def on_error(message):
        errors.append(message)
        service.set_enabled(True)  # Re-enable while the failed worker still lives.

    audio.read, audio.stop = read, stop
    service._on_error = on_error
    try:
        service.start()
        assert cleanup_entered.wait(1)
        assert audio.starts == 1  # Never overlap old and new capture.
        release_cleanup.set()
        wait_for(lambda: audio.starts == 2 and service.running)
        assert service.state == "idle"
    finally:
        release_cleanup.set()
        service.stop()
    assert not service.running
    assert not audio.running
