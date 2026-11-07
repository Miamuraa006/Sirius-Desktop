import numpy as np
import pytest

from voice.audio_input import PCM16Converter
from voice.command_stt import BLOCK, POST, PRE, SileroEndpoint
from voice.normalization import normalize_command


class FrameScores:
    """Emit deterministic speech probabilities while testing the real frame assembler."""
    def run(self, _names, inputs):
        score = float(np.max(inputs['input'][0, -BLOCK:]) > .1)
        return np.array([score]), inputs['h'], inputs['c']


def test_vad_keeps_pre_and_post_roll_across_uneven_callbacks():
    vad = SileroEndpoint(FrameScores())
    silence = bytes(BLOCK * 2)
    word = (np.ones(BLOCK, dtype='<i2') * 9000).tobytes()
    sentence = word * 3 + silence * 7 + word * 5
    data = silence * 32 + sentence + silence * POST
    clips = []
    for i in range(0, len(data), 1102):
        clips.extend(vad.feed(data[i:i+1102]))
    assert clips == [silence * PRE + sentence + silence * POST]


def test_interrupted_sentence_does_not_execute_its_tail():
    vad = SileroEndpoint(FrameScores())
    word = (np.ones(BLOCK, dtype='<i2') * 9000).tobytes()
    vad.feed(word * 4)
    vad.reset(interrupted=True)
    assert not vad.feed(word * 3 + bytes(BLOCK * 2 * POST))
    assert len(vad.feed(word * 4 + bytes(BLOCK * 2 * POST))) == 1


@pytest.mark.parametrize('rate', [16000, 44100, 48000])
def test_streaming_stereo_resample_matches_whole_file(rate):
    signal = np.sin(2*np.pi*440*np.arange(rate)/rate)
    raw = np.column_stack((signal*12000, signal*6000)).astype('<i2').tobytes()
    whole = PCM16Converter(rate, 2).convert(raw, final=True)
    chunked = PCM16Converter(rate, 2)
    split = b''.join(chunked.convert(raw[i:i+1600]) for i in range(0, len(raw), 1600))
    split += chunked.convert(b'', final=True)
    assert len(whole) == 32000
    assert np.max(np.abs(np.frombuffer(whole,'<i2').astype(int) - np.frombuffer(split,'<i2'))) <= 1


@pytest.mark.parametrize('text,expected',[('Open Steam.', 'открой Steam'), ('Да?', 'Да?'), ('Close Telegram.', 'закрой Telegram'),
    ('Открой ютуб!', 'открой YouTube'), ('закрой не Telegram', 'закрой не Telegram'),
    ('установи буфер обмена Steam!', 'установи буфер обмена Steam!')])
def test_app_normalization_is_separate_and_whole_command_only(text, expected):
    assert normalize_command(text) == expected
