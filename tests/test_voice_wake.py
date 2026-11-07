import json
from importlib import import_module, util

import pytest

from voice.stt import Transcript, Word


def wake_module():
    assert util.find_spec("voice.wake_word") is not None, "narrow wake adapter missing"
    return import_module("voice.wake_word")


def phrase(text="сириус", confidence=.98, duration=.5):
    return Transcript(text, (Word(text, confidence, 0, duration),))


@pytest.mark.parametrize("text,confidence,duration,accepted", [
    ("сириус", .98, .5, True), ("сириус", .5, .5, False),
    ("sirius", .98, .5, True), ("SIRIUS", .98, .5, True),
    ("siriusly", .98, .5, False),
    ("сириус", .99, .05, False), ("сириус", .99, 3, False),
    ("сервис", .99, .6, False), ("серия", .99, .6, False),
    ("[unk]", 1, .5, False), ("открой сириус", 1, .6, False),
])
def test_wake_requires_exact_confident_word_with_acoustic_dwell(text, confidence, duration, accepted):
    m = wake_module()
    assert m.WakeFilter().accepts(phrase(text, confidence, duration)) is accepted


def test_wake_vosk_grammar_has_unknown_escape_and_no_fuzzy_aliases():
    m = wake_module()
    calls = []

    class Recognizer:
        def __init__(self, model, rate, *grammar):
            calls.append(json.loads(grammar[0]) if grammar else None)
        def SetWords(self, value):
            assert value
        def AcceptWaveform(self, pcm):
            return True
        def Result(self):
            return json.dumps({"text": "сириус", "result": [{"word": "сириус", "conf": .95, "start": .1, "end": .7}]})
        def FinalResult(self):
            return "{}"
        def Reset(self):
            pass

    detector = m.VoskWakeWord(object(), recognizer_factory=Recognizer)
    assert calls == [["сириус", "[unk]"]]
    assert detector.feed(b"\0\0") is True
    assert calls == [["сириус", "[unk]"], None]
    detector.reset()


def test_wake_rejects_forced_candidate_when_full_vocabulary_disagrees():
    class Recognizer:
        def __init__(self, model, rate, *grammar):
            self.word = "сириус" if grammar else "сервис"
        def SetWords(self, value):
            pass
        def AcceptWaveform(self, pcm):
            return True
        def Result(self):
            return json.dumps({"text": self.word, "result": [
                {"word": self.word, "conf": 1, "start": .09, "end": .75}]})
        def FinalResult(self):
            return "{}"
        def Reset(self):
            pass

    detector = wake_module().VoskWakeWord(object(), recognizer_factory=Recognizer)
    assert detector.feed(b"\0\0" * 800) is False
    assert detector.last_result.text == "сириус"
    assert detector.last_verification.text == "сервис"


@pytest.mark.parametrize('confidence,word,accepted', [
    (.84204, 'сириус', True), (.59, 'сириус', False), (1, 'сервис', False),
])
def test_independent_confirmation_accepts_clear_name_without_relaxing_vocabulary(confidence, word, accepted):
    class Recognizer:
        def __init__(self, model, rate, *grammar):
            self.primary = bool(grammar)
        def SetWords(self, value): pass
        def AcceptWaveform(self, pcm): return False
        def FinalResult(self):
            return json.dumps({'text': word, 'result': [
                {'word': word, 'conf': confidence, 'start': .2, 'end': .7}]})
        def Reset(self): pass
    detector = wake_module().VoskWakeWord(object(), recognizer_factory=Recognizer)
    detector.stt.feed = lambda pcm: phrase()
    assert detector.feed(b'\0\0' * 16000) is accepted


def test_confirmation_uses_candidate_segment_after_long_idle_and_resets_offsets():
    from types import SimpleNamespace
    detector = wake_module().VoskWakeWord(object(), recognizer_factory=lambda *args: SimpleNamespace(SetWords=lambda value: None))
    # Simulate a ten-second idle stream: Vosk timestamps remain absolute to reset.
    detector.stt = SimpleNamespace(feed=lambda pcm: None, reset=lambda: None)
    for _ in range(10):
        detector.feed(b'\0\0' * 16000)
    audio = bytearray()
    detector._verifier = SimpleNamespace(
        feed=lambda pcm: audio.extend(pcm), reset=lambda: None,
        finish=lambda: phrase(confidence=.84204))
    detector.stt.feed = lambda pcm: Transcript('сириус', (Word('сириус', 1, 10.1, 10.6),))
    assert detector.feed(b'\1\0' * 16000)
    # 9.9 .. 10.9 seconds; earlier silence is excluded from the second pass.
    assert len(audio) == 16000 * 2
    assert audio[:3200] == b'\0\0' * 1600
    assert audio[3200:] == b'\1\0' * 14400
    detector.reset()
    assert detector._samples_seen == 0 and not detector._buffer
