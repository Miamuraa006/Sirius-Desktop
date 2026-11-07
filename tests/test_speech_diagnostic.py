import json
import time
import wave
from queue import Queue, Empty

from PySide6.QtWidgets import QApplication
from voice.audio_input import AudioFrame
from voice import diagnostic


def test_button_saves_untouched_driver_frames_without_an_engine(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    frames = Queue()
    class Input:
        dropped_blocks = status_events = 0
        device_info = dict(index=4, name="Fixture", host_api="WASAPI")
        def __init__(self, device=None):
            pass
        def start(self):
            pass
        def stop(self):
            pass
        def read_raw(self, timeout):
            try:
                return frames.get_nowait()
            except Empty:
                return None

    class Quiet:
        def __init__(self):
            self.vad = self
        def reset(self):
            pass
        def feed(self, pcm):
            return []
        def finish(self):
            return []

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(diagnostic, 'AudioInput', Input)
    monkeypatch.setattr(diagnostic, 'diagnostic_vosk', lambda cfg: Quiet())
    window = diagnostic.Diagnostic({'voice': {}})
    def tick_until(check):
        until = time.monotonic() + 4
        while time.monotonic() < until:
            window.tick()
            app.processEvents()
            if check():
                return
            time.sleep(.01)
        raise AssertionError('diagnostic timed out')
    try:
        frames.put(AudioFrame(bytes(8820), time.monotonic(), 1, 44100, 2))
        tick_until(window.button.isEnabled)
        assert 'Fixture' in window.input_name.text() and 'WASAPI' in window.input_name.text()
        window.button.click()
        raw = bytes([0, 1, 0, 2]) * 2205
        frames.put(AudioFrame(raw, time.monotonic(), 1, 44100, 2))
        window.button.click()
        tick_until(lambda: window.path is not None and window.path.with_suffix('.json').exists())
        with wave.open(str(window.path), 'rb') as recorded:
            assert (recorded.getframerate(), recorded.getnchannels()) == (44100, 2)
            assert recorded.readframes(recorded.getnframes()) == raw
        result = json.loads(window.path.with_suffix('.json').read_text('utf-8'))
        assert result['input_rate'] == 44100 and result['stt_rate'] == 16000
        assert result['device']['index'] == 4 and result['input_frames'] == 2205
        assert result['dropped_blocks_during_recording'] == 0
        assert result['duration_s'] == .05 and not result['segments']
    finally:
        window.close()
