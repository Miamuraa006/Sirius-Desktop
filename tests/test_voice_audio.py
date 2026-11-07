import threading
import time
from importlib import import_module, util


def audio_class():
    assert util.find_spec("voice.audio_input") is not None, "audio input missing"
    return import_module("voice.audio_input").AudioInput


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate(), "condition not reached"


class Stream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.active = False
        self.closed = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *args):
        self.active = False
        self.closed = True


def test_audio_queue_is_bounded_and_discards_old_audio_at_overflow():
    streams = []

    def factory(**kwargs):
        stream = Stream(**kwargs)
        streams.append(stream)
        return stream

    capture = audio_class()(stream_factory=factory, queue_size=2)
    try:
        capture.start()
        wait_for(lambda: streams and streams[0].active)
        stream = streams[0]
        assert stream.kwargs["dtype"] == "int16"
        assert stream.kwargs["channels"] == 1
        for n in range(5):
            stream.callback(bytes([n, 0]) * 800, 800, None, None)
        assert capture.pending <= 2
        assert capture.dropped_blocks > 0
        frame = capture.read(.1)
        assert frame.pcm == bytes([4, 0]) * 800
        assert frame.generation > 1
    finally:
        capture.stop()
    assert streams[0].closed
    assert not capture.running


def test_missing_microphone_retries_and_dropout_reconnects():
    attempts = []
    streams = []
    errors = []

    def factory(**kwargs):
        attempts.append(threading.get_ident())
        if len(attempts) == 1:
            raise OSError("device disconnected")
        stream = Stream(**kwargs)
        streams.append(stream)
        return stream

    capture = audio_class()(stream_factory=factory, on_error=errors.append,
                            retry_initial=.01, retry_max=.05)
    try:
        capture.start()
        wait_for(lambda: streams and streams[0].active)
        streams[0].active = False
        wait_for(lambda: len(streams) >= 2 and streams[1].active)
        assert streams[0].closed
        assert errors and all("микрофон" in e.casefold() for e in errors)
        assert set(attempts) != {threading.get_ident()}
    finally:
        capture.stop()
    assert all(s.closed for s in streams)


def test_stop_interrupts_long_reconnect_backoff():
    failed = threading.Event()

    def factory(**kwargs):
        failed.set()
        raise OSError("no device")

    capture = audio_class()(stream_factory=factory, retry_initial=5, retry_max=5)
    capture.start()
    assert failed.wait(1)
    start = time.monotonic()
    capture.stop()
    assert time.monotonic() - start < .5
    assert not capture.running
