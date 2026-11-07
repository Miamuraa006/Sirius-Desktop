import os
import pytest

from core.models import Command
from test_engine import make
from voice.help_stt import HelpAwareSTT
from voice.stt import Transcript, Word


@pytest.mark.parametrize('source', ['voice', 'text'])
@pytest.mark.parametrize('answer,approve', [
    ('да', True), ('Давай!', True), ('Go', True), ('го', True), ('гоу', True), ('ага', True),
    ('подтверждаю', True), ('нет', False), ('не   надо', False), ('Отмена.', False), ('отмени', False),
])
def test_closing_requires_one_reply_in_requesting_session(tmp_path, source, answer, approve):
    engine, handler, _ = make(tmp_path)
    try:
        assert not engine.recognizes(answer)
        assert engine.execute(Command('закрой блокнот', source)).status == 'needs_confirmation'
        assert engine.recognizes(answer) and not engine.recognizes(answer, 'other')
        assert not engine.execute(Command(answer, source, 'other')).verified
        assert engine.execute(Command(answer, source)).verified
        assert len(handler.calls) == int(approve)
        assert not engine.recognizes(answer)
        assert not engine.execute(Command(answer, source)).verified
    finally:
        engine.close()


@pytest.mark.parametrize('text', ['не давай', 'год', 'давай открой', 'нет, да', 'да?'])
def test_substrings_do_not_confirm(tmp_path, text):
    engine, handler, _ = make(tmp_path)
    try:
        assert engine.execute(Command('закрой блокнот')).status == 'needs_confirmation'
        assert not engine.recognizes(text)
        assert not engine.execute(Command(text, 'voice')).verified and not handler.calls
    finally:
        engine.close()


def test_short_approval_expires(tmp_path):
    engine, handler, _ = make(tmp_path)
    try:
        engine.policy.clock = lambda: 1
        engine.execute(Command('закрой блокнот'))
        engine.policy.clock = lambda: 61
        assert not engine.recognizes('го')
        assert not engine.execute(Command('го')).verified and not handler.calls
    finally:
        engine.close()


@pytest.mark.parametrize('pending,heard,confidence,second,expected', [
    (True, 'год', .4, 'го', 'го'), (False, 'год', .4, 'го', 'год'),
    (True, 'год', 1, 'го', 'год'), (True, 'год', .4, 'год', 'год'),
    (True, 'нет', .4, 'го', 'нет'), (True, 'год', .2, 'го', 'год'),
])
def test_spoken_go_requires_a_question_and_acoustic_agreement(pending, heard, confidence, second, expected):
    def word(text, score):
        return Transcript(text, (Word(text, score, 0, .3),))

    class Decoder:
        def __init__(self, *args, grammar=None):
            self.grammar = grammar
        def reset(self):
            pass
        def feed(self, pcm):
            return None if self.grammar else word(heard, confidence)
        def finish(self):
            return word(second, .92) if self.grammar else word(heard, confidence)

    stt = HelpAwareSTT(None, stt_factory=Decoder, expects_reply=lambda: pending)
    assert stt.feed(bytes(1600)).text == expected


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('SIRIUS_TEST_GENERATED_VOICE') != '1',
                    reason='Opt-in Russian SAPI/Vosk integration')
def test_spoken_replies_after_previous_commands(tmp_path, monkeypatch):
    import queue
    import time
    import wave
    from voice import probe
    from voice.audio_input import AudioFrame
    from voice.service import VoiceService
    from test_voice_service import Audio, wait_for

    words = ['да', 'нет', 'давай', 'го', 'не надо', 'отмена']
    monkeypatch.setattr(probe, '_SPEECH_CASES', [(w, w, 'stt', w) for w in words])
    _, samples = probe._sapi_files(tmp_path)
    engine, handler, _ = make(tmp_path)
    audio, received = Audio(), queue.Queue()
    service = VoiceService({}, received.put, lambda state: None, lambda level: None, engine.recognizes,
                           audio_factory=lambda **kw: audio)
    try:
        service.start()
        wait_for(lambda: audio.running and audio.clears, timeout=15)
        for word in words:
            assert engine.execute(Command('закрой блокнот')).status == 'needs_confirmation'
            clears = audio.clears
            service.activate()
            wait_for(lambda: audio.clears > clears)
            with wave.open(str(samples[word]['path']), 'rb') as wav:
                pcm = wav.readframes(wav.getnframes()) + bytes(64000)
            for offset in range(0, len(pcm), 1600):
                audio.frames.put(AudioFrame(pcm[offset:offset + 1600], time.monotonic(), 1))
            heard = received.get(timeout=6)
            assert heard == word and engine.execute(Command(heard, 'voice')).verified
            service.command_completed()
            assert bool(handler.calls) == (word in {'да', 'давай', 'го'})
            handler.calls.clear()
    finally:
        service.stop()
        engine.close()

