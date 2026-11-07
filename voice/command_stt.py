"""One multilingual Faster-Whisper Small CPU decoder, gated by streaming Silero VAD."""
from collections import deque
import math
import os
from pathlib import Path
import time

import numpy as np

from voice.stt import ModelUnavailable, Transcript, Word

RATE = 16000
BLOCK = 512
PRE = 15       # 480 ms before the first positive window
POST = 25      # 800 ms of quiet after the last voiced window


def model_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Sirius/Speech/faster-whisper-small'


class SileroEndpoint:
    def __init__(self, session=None):
        if session is None:
            from faster_whisper.vad import get_vad_model
            session = get_vad_model().session
        self.session = session
        self.reset()

    def reset(self, *, interrupted=False):
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = self.h.copy()
        self.context = np.zeros(64, np.float32)
        self.pending = bytearray()
        self.samples = 0
        self.bounds = (0, 0)
        self.before = deque(maxlen=PRE)
        self.active = []
        self.quiet = self.positive = 0
        self.discard = interrupted

    def feed(self, pcm):
        self.pending.extend(pcm)
        results = []
        while len(self.pending) >= BLOCK * 2:
            frame = bytes(self.pending[:BLOCK * 2])
            del self.pending[:BLOCK * 2]
            signal = np.frombuffer(frame, '<i2').astype(np.float32) / 32768
            samples = np.concatenate((self.context, signal))[None, :]
            scores, self.h, self.c = self.session.run(None, {'input': samples, 'h': self.h, 'c': self.c})
            self.context = signal[-64:]
            self.samples += BLOCK
            probability = float(scores.flat[0])
            if self.discard:
                self.quiet = self.quiet + 1 if probability < .35 else 0
                if self.quiet >= POST:
                    self.discard = False
                    self.quiet = 0
                continue
            if not self.active:
                if probability < .50:
                    self.before.append(frame)
                    continue
                self.active = list(self.before)
                self.before.clear()
            self.active.append(frame)
            self.positive += int(probability >= .50)
            self.quiet = self.quiet + 1 if probability < .35 else 0
            if self.quiet >= POST:
                if self.positive >= 2:
                    self.bounds = (self.samples - BLOCK * len(self.active), self.samples)
                    results.append(b''.join(self.active))
                self.before.extend(self.active[-PRE:])
                self.active = []
                self.positive = self.quiet = 0
            elif len(self.active) >= 625:  # A command over 20 seconds is never executed as a fragment.
                self.active = []
                self.discard = True
                self.quiet = self.positive = 0
        return results

    def finish(self):
        # Flush just the incomplete VAD frame. Do not append invented audio to a recording.
        length = len(self.pending)
        completed = self.feed(bytes(BLOCK * 2 - length)) if length else []
        if self.active and self.positive >= 2:
            tail = b''.join(self.active)
            if length:
                tail = tail[:len(tail) - (BLOCK * 2 - length)]
            self.bounds = (self.samples - BLOCK * len(self.active), self.samples - (BLOCK - length // 2 if length else 0))
            completed.append(tail)
        bounds = self.bounds
        self.reset()
        self.bounds = bounds
        return completed


class SmallRecognizer:
    def __init__(self, directory=None, *, beam_size=5):
        from faster_whisper import WhisperModel
        directory = directory or model_directory()
        if not (directory / 'model.bin').is_file():
            raise ModelUnavailable('Нет локальной модели Faster-Whisper Small. Запустите scripts/setup_whisper.py.')
        self.model = WhisperModel(str(directory), device='cpu', compute_type='int8',
                                  cpu_threads=4, num_workers=1, local_files_only=True)
        self.beam_size = beam_size
        self.vad = SileroEndpoint()
        self.last = {}

    def reset(self):
        self.vad.reset()

    def interrupted(self):
        self.vad.reset(interrupted=True)

    def decode(self, pcm, *, wake=False):
        started = time.perf_counter()
        audio = np.frombuffer(pcm, '<i2').astype(np.float32) / 32768
        options = dict(task='transcribe', beam_size=self.beam_size, temperature=0, condition_on_previous_text=False,
                       vad_filter=False, hotwords='Сириус' if wake else 'Steam, Telegram, YouTube', word_timestamps=False)
        segments, info = self.model.transcribe(audio, language='ru' if wake else None, **options)
        language = info.language
        if language not in ('ru', 'en'):
            language = max(((l, p) for l, p in info.all_language_probs if l in ('ru', 'en')),
                           key=lambda pair: pair[1])[0]
            segments, info = self.model.transcribe(audio, language=language, **options)
        segments = list(segments)
        raw = ''.join(seg.text for seg in segments).strip()
        confidence = min((min(1., math.exp(seg.avg_logprob)) for seg in segments), default=0.)
        self.last = dict(text=raw, language=language, confidence=round(confidence, 3),
                         decode_ms=round(1000 * (time.perf_counter() - started), 1),
                         segment_seconds=round(len(audio) / RATE, 3))
        return Transcript(raw, (Word(raw, confidence, 0., len(audio) / RATE),)) if raw else None

    def feed(self, pcm, *, wake=False):
        segments = self.vad.feed(pcm)
        return self.decode(segments[0], wake=wake) if segments else None
