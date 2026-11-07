import json
from importlib import import_module, util

import pytest


def stt_module():
    assert util.find_spec("voice.stt") is not None, "Vosk adapter missing"
    return import_module("voice.stt")


class NativeRecognizer:
    def __init__(self, model, rate, *grammar):
        self.args = (model, rate, grammar)
        self.words = False
        self.resets = 0
        self.completed = True
        self.payload = {"text": "громче", "result": [{"word": "громче", "conf": .9, "start": .1, "end": .6}]}

    def SetWords(self, value):
        self.words = value

    def AcceptWaveform(self, pcm):
        self.pcm = pcm
        return self.completed

    def Result(self):
        return json.dumps(self.payload, ensure_ascii=False)

    def FinalResult(self):
        return self.Result()

    def Reset(self):
        self.resets += 1


def test_stt_returns_only_complete_confidence_bearing_transcripts():
    m = stt_module()
    recognizer = m.VoskSTT(object(), 16000, recognizer_factory=NativeRecognizer)
    assert recognizer.native.words is True
    result = recognizer.feed(b"\0\0" * 800)
    assert result.text == "громче"
    assert result.confidence == .9
    assert result.words[0].duration == .5
    recognizer.native.completed = False
    assert recognizer.feed(b"\0\0") is None
    assert recognizer.finish().text == "громче"
    recognizer.reset()
    assert recognizer.native.resets == 1


@pytest.mark.parametrize("payload", [
    {}, {"text": ""}, {"text": "noise"},
    {"text": "громче", "result": [{"word": "громче", "conf": float("nan"), "start": 0, "end": .5}]},
    {"text": "громче", "result": [{"word": "громче", "conf": .9, "start": 1, "end": .5}]},
])
def test_stt_rejects_empty_or_unscored_or_invalid_result(payload):
    m = stt_module()
    recognizer = m.VoskSTT(object(), recognizer_factory=NativeRecognizer)
    recognizer.native.payload = payload
    assert recognizer.feed(b"\0\0") is None


def test_model_missing_is_actionable_and_does_not_call_loader(tmp_path):
    m = stt_module()
    assert hasattr(m, "VoskModel"), "model validation missing"
    calls = []
    model = m.VoskModel(tmp_path / "absent", model_factory=lambda path: calls.append(path))
    with pytest.raises(m.ModelUnavailable, match="модел"):
        model.load()
    assert calls == []


def test_model_loads_once_and_requires_real_layout(tmp_path):
    m = stt_module()
    assert hasattr(m, "VoskModel"), "model cache missing"
    (tmp_path / "am").mkdir()
    (tmp_path / "conf").mkdir()
    (tmp_path / "am/final.mdl").write_bytes(b"fixture")
    (tmp_path / "conf/model.conf").write_bytes(b"fixture")
    calls = []
    sentinel = object()

    def load(path):
        calls.append(path)
        return sentinel

    model = m.VoskModel(tmp_path, model_factory=load)
    assert model.load() is sentinel
    assert model.load() is sentinel
    assert len(calls) == 1


@pytest.mark.parametrize("path", [r"\\server\share\model", "//server/share/model"])
def test_model_rejects_network_paths_before_filesystem_access(path):
    m = stt_module()
    assert hasattr(m, "VoskModel"), "local-only model gate missing"
    with pytest.raises(m.ModelUnavailable):
        m.VoskModel(path).load()
