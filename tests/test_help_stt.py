import pytest
from voice.help_stt import HelpAwareSTT
from voice.stt import Transcript, Word


def phrase(text, confidence=1, duration=.5):
    return Transcript(text, (Word(text, confidence, 0, duration),))


@pytest.mark.parametrize("heard,confidence,accepted", [("хэл", .5, True), ("хилл", .6, True),
    ("хлеб", 1, False), ("громче", 1, False), ("хэл", .2, False), ("шум", 1, False)])
def test_help_candidate_requires_independent_phonetic_agreement(heard, confidence, accepted):
    class Adapter:
        def __init__(self, *args, grammar=None): self.short = grammar is not None
        def feed(self, pcm): return phrase("хелп") if self.short else None
        def finish(self): return phrase(heard, confidence)
        def reset(self): pass
    decoder = HelpAwareSTT(object(), stt_factory=Adapter)
    result = decoder.feed(b"\0\0" * 800)
    assert (result is not None) is accepted
    if accepted:
        assert result.text == "help" and result.confidence >= .9


def test_help_decoder_keeps_normal_commands_and_bounds_audio():
    class Adapter:
        def __init__(self, *args, grammar=None): self.short = grammar is not None
        def feed(self, pcm): return None if self.short else phrase("громче")
        def finish(self): return None
        def reset(self): pass
    decoder = HelpAwareSTT(object(), stt_factory=Adapter)
    assert decoder.feed(b"\0\0" * 800).text == "громче"
    decoder.full.feed = lambda pcm: None
    for _ in range(100): decoder.feed(b"\0\0" * 1600)
    assert len(decoder.buffer) == decoder.limit
    decoder.reset()
    assert not decoder.buffer
