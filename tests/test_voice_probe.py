"""Probe contract tests use fake native boundaries; never microphones/speakers."""
import json
import wave
from importlib import import_module, util

from voice.stt import Transcript, Word


def probe_module():
    assert util.find_spec("voice.probe") is not None, "production voice diagnostics missing"
    return import_module("voice.probe")


def test_generated_wav_probe_records_observed_text_not_expected(tmp_path):
    module = probe_module()
    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * 16000)

    class STT:
        def __init__(self):
            self.frames = 0
        def feed(self, pcm):
            self.frames += len(pcm) // 2
            if self.frames == 24000:
                return Transcript("другой текст", (Word("другой", .8, .1, .5), Word("текст", .7, .5, .9)))
            return None
        def finish(self):
            return None

    observed = module.recognize_wav(path, STT(), expected_text="один два три")
    assert observed["expected_text"] == "один два три"
    assert observed["observed_text"] == "другой текст"
    assert observed["passed"] is False
    assert observed["min_confidence"] == .7
    assert observed["wav"]["duration_seconds"] == 1.0
    assert observed["events"][0]["stream_offset_seconds"] == 1.5
    assert observed["events"][0]["endpoint_audio_seconds"] == .6
    assert observed["events"][0]["result_kind"] == "stream_endpoint"
    assert observed["decoder_wall_seconds"] >= 0
    assert observed["events"][0]["words"][0]["duration_seconds"] == .4
    assert json.loads(json.dumps(observed, allow_nan=False)) == observed


def test_probe_missing_model_writes_failure_without_fabricated_recognition(tmp_path, monkeypatch):
    module = probe_module()
    assert hasattr(module, "run_probe"), "source/frozen callable probe missing"
    monkeypatch.setattr(module, "probe_hotkey", lambda: {"status": "unsupported", "passed": False})
    monkeypatch.setattr(module, "enumerate_inputs", lambda: [])
    output = tmp_path / "output"
    report = module.run_probe({"_resource_root": str(tmp_path), "voice": {"model_path": "missing"}}, output)
    assert report["passed"] is False
    assert report["speech"]["model"]["status"] == "failed"
    assert report["speech"]["cases"] == []
    assert report["privacy"]["microphone_opened"] is False
    assert report["privacy"]["audio_played"] is False
    assert report["hardware"]["microphone_capture"] == "untested"
    assert report["speech_worker"]["terminated"] is False
    assert report["speech_worker"]["released"] is True
    assert json.loads((output / "VOICE_TESTS.json").read_text(encoding="utf-8")) == report


def test_wake_probe_separates_candidate_and_verification_latency(tmp_path):
    module = probe_module()
    path = tmp_path / "candidate.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 800)

    class Detector:
        def __init__(self):
            self.last_result = self.last_verification = None
            self.verification_wall_seconds = 0.0
            self.stt = self
            self.once = True
        def feed(self, pcm):
            self.last_result = self.last_verification = None
            self.verification_wall_seconds = 0.0
            if self.once:
                self.once = False
                self.last_result = Transcript("сириус", (Word("сириус", 1, 0, .5),))
                self.last_verification = Transcript("сервис", (Word("сервис", .9, 0, .5),))
                self.verification_wall_seconds = .001
            return False
        def finish(self):
            return None

    report = module.recognize_wav(path, Detector(), expected_wake=False)
    assert report["passed"] is True
    assert report["observed_text"] == "сириус"
    assert report["events"][0]["verification"]["text"] == "сервис"
    assert report["events"][0]["verification"]["confidence"] == .9
    assert report["wake_confirmation_wall_seconds"] == .001


def test_sapi_synthesis_routes_output_to_file_before_speak(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pythoncom
    import win32com.client.dynamic as dynamic

    module = probe_module()
    calls = []
    streams = []

    class Token:
        def GetDescription(self):
            return "Test Russian voice"
        def GetAttribute(self, name):
            return "409;0419"

    class Speaker:
        def GetVoices(self):
            return SimpleNamespace(Count=1, Item=lambda index: Token())
        def Speak(self, text, flags):
            assert self.AudioOutputStream is streams[-1]
            assert streams[-1].opened
            assert streams[-1].Format.Type == 18
            calls.append(("speak", text, flags))

    class Stream:
        def Open(self, path, mode, events):
            assert mode == 3 and events is False
            self.opened = True
        def Close(self):
            self.opened = False
            calls.append("close")

    def dispatch(progid):
        if progid == "SAPI.SpVoice":
            return Speaker()
        if progid == "SAPI.SpFileStream":
            stream = Stream()
            streams.append(stream)
            return stream
        assert progid == "SAPI.SpAudioFormat"
        return SimpleNamespace()

    monkeypatch.setattr(dynamic, "Dispatch", dispatch)
    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: calls.append("init"))
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: calls.append("uninit"))
    monkeypatch.setattr(module, "_SPEECH_CASES", (("test", "Сириус", "wake", True),))
    metadata, files = module._sapi_files(tmp_path)
    assert metadata["language"] == "409;0419"
    assert files["test"]["source_text"] == "Сириус"
    assert calls == ["init", ("speak", "Сириус", 0), "close", "uninit"]


def test_sapi_without_russian_voice_never_speaks(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pythoncom
    import win32com.client.dynamic as dynamic

    module = probe_module()
    calls = []
    token = SimpleNamespace(GetDescription=lambda: "English", GetAttribute=lambda name: "409")
    speaker = SimpleNamespace(GetVoices=lambda: SimpleNamespace(Count=1, Item=lambda index: token))
    monkeypatch.setattr(dynamic, "Dispatch", lambda name: speaker)
    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: calls.append("init"))
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: calls.append("uninit"))
    metadata, files = module._sapi_files(tmp_path)
    assert metadata["status"] == "unsupported"
    assert files == {}
    assert calls == ["init", "uninit"]


def test_source_probe_cli_is_runnable_from_an_unrelated_directory(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "voice_probe.py"
    completed = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_path,
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "--output" in completed.stdout
    assert "--report" in completed.stdout
