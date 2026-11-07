"""Bounded in-memory PCM capture with interruptible microphone reconnection.

The PortAudio callback only copies into a bounded queue: no logging, disk, STT,
Qt or user callbacks. Unit tests inject a stream factory and never open devices.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class AudioFrame:
    pcm: bytes
    captured_at: float
    generation: int
    rate: int = 16000
    channels: int = 1


def enumerate_inputs() -> list[dict]:
    """Read-only device inventory; does not construct/start an audio stream."""
    import sounddevice as sd
    return [{"index": index, "name": d["name"], "channels": d["max_input_channels"],
             "default_sample_rate": d["default_samplerate"]}
            for index, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


# Object lifetime is owned by Windows; a crashed diagnostic cannot leave a stale flag.
DIAGNOSTIC = r'Local\Sirius.SpeechDiagnostic.v1'
CAPTURE = r'Local\Sirius.AssistantMic.v1'


@lru_cache(maxsize=1)
def _mutex_api():
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    api.CreateMutexW.restype = wintypes.HANDLE
    api.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    api.OpenMutexW.restype = wintypes.HANDLE
    return api


class SpeechMarker:
    def __init__(self, name):
        import ctypes
        self.handle = _mutex_api().CreateMutexW(None, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.existed = ctypes.get_last_error() == 183

    def close(self):
        import _winapi
        if self.handle:
            _winapi.CloseHandle(self.handle)
            self.handle = None


def speech_marker_set(name):
    import _winapi
    handle = _mutex_api().OpenMutexW(0x00100000, False, name)
    if handle:
        _winapi.CloseHandle(handle)
    return bool(handle)


class PCM16Converter:
    """Stateful anti-aliasing resampler; channel averaging happens before resampling."""
    def __init__(self, rate, channels, output_rate=16000):
        self.channels = channels
        self.stream = None
        if rate != output_rate:
            import soxr
            self.stream = soxr.ResampleStream(rate, output_rate, 1, dtype='float32')

    def convert(self, pcm, final=False):
        if self.channels == 1 and self.stream is None:
            return pcm
        import numpy as np
        values = np.frombuffer(pcm, '<i2').reshape(-1, self.channels).mean(axis=1, dtype=np.float32)
        if self.stream is not None:
            values = self.stream.resample_chunk(values, last=final)
        return np.rint(values).clip(-32768, 32767).astype('<i2').tobytes()


class AudioInput:
    def __init__(self, *, device=None, sample_rate: int = 16000, blocksize: int = 800,
                 queue_size: int = 400, on_error=None, on_connection=None,
                 stream_factory=None, retry_initial: float = .25, retry_max: float = 8.0,
                 stall_seconds: float = 2.0):
        if queue_size < 1 or not 0 < retry_initial <= retry_max or stall_seconds <= 0:
            raise ValueError("Invalid audio buffering/retry configuration")
        self.device = device
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.on_error = on_error
        self.on_connection = on_connection
        self._factory = stream_factory
        self._queue: queue.Queue[AudioFrame] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle = threading.Lock()
        self._retry_initial = retry_initial
        self._retry_max = retry_max
        self._stall_seconds = stall_seconds
        self._last_callback = 0.0
        self._generation = 0
        self.dropped_blocks = 0
        self.status_events = 0
        self.device_info = {}
        self.native_rate, self.channels = sample_rate, 1
        self._converted_generation = None
        self._converter = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @staticmethod
    def _notify(callback, value) -> None:
        if callback is not None:
            try:
                callback(value)
            except Exception:
                pass  # Renderer teardown cannot kill capture cleanup.

    def start(self):
        with self._lifecycle:
            if self.running:
                return self
            self._stop.clear()
            self.clear()
            self._thread = threading.Thread(target=self._run, name="SiriusAudio", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        with self._lifecycle:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.clear()
        if self.running and thread is not threading.current_thread():
            self._notify(self.on_error, "Микрофон ещё завершает работу драйвера.")

    def read_raw(self, timeout: float = .1) -> AudioFrame | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def read(self, timeout: float = .1) -> AudioFrame | None:
        frame = self.read_raw(timeout)
        if frame is None:
            return None
        if frame.generation != self._converted_generation:
            self._converter = PCM16Converter(frame.rate, frame.channels, self.sample_rate)
            self._converted_generation = frame.generation
        pcm = self._converter.convert(frame.pcm)
        return AudioFrame(pcm, frame.captured_at, frame.generation, self.sample_rate, 1)

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _callback(self, indata, frames, time_info, status) -> None:
        if self._stop.is_set():
            return
        self._last_callback = time.monotonic()
        if status:
            self.status_events += 1
        if status or self._queue.full():
            self._generation += 1
            self.dropped_blocks += max(1, self._queue.qsize())
            self.clear()
        frame = AudioFrame(bytes(indata), self._last_callback, self._generation, self.native_rate, self.channels)
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            self.dropped_blocks += 1
            self._generation += 1

    def _run(self) -> None:
        backoff = self._retry_initial
        notified_error = False
        while not self._stop.is_set():
            try:
                factory = self._factory
                if factory is None:
                    import sounddevice as sd
                    info = sd.query_devices(self.device, 'input')
                    self.native_rate = int(round(info['default_samplerate']))
                    self.channels = min(2, int(info['max_input_channels']))
                    factory = sd.RawInputStream
                self.clear()
                self._generation += 1
                self._last_callback = time.monotonic()
                with factory(device=self.device, samplerate=self.native_rate,
                             blocksize=round(self.blocksize * self.native_rate / self.sample_rate),
                             dtype="int16", channels=self.channels,
                             callback=self._callback) as stream:
                    if self._factory is None:
                        index = stream.device
                        info = sd.query_devices(index)
                        self.device_info = dict(index=int(index), name=info['name'],
                                                host_api=sd.query_hostapis(info['hostapi'])['name'])
                    self._notify(self.on_connection, True)
                    notified_error = False
                    opened_at = time.monotonic()
                    while not self._stop.wait(.05):
                        now = time.monotonic()
                        if not stream.active or now - self._last_callback > self._stall_seconds:
                            raise OSError("input stream stopped producing blocks")
                        if now - opened_at >= 1:
                            backoff = self._retry_initial
            except Exception:
                if not self._stop.is_set():
                    self._notify(self.on_connection, False)
                    if not notified_error:
                        self._notify(self.on_error, "Микрофон недоступен; повторное подключение автоматически.")
                        notified_error = True
                    if self._stop.wait(backoff):
                        break
                    backoff = min(self._retry_max, backoff * 2)
            finally:
                self.clear()
        self._notify(self.on_connection, False)
