"""Full command STT with bounded second passes for help and short spoken replies."""
from core.replies import CHOICES, parse_reply
from voice.normalization import CS2_TRANSCRIPTS, normalize_command
from voice.stt import Transcript, VoskSTT, Word

_PHONETIC_HELP = frozenset({"help", "хелп", "хэлп", "хел", "хэл", "хилл"})
_GAME_PHRASES = CS2_TRANSCRIPTS | {'игровой режим', 'режим игры', 'включи игровой режим'}
_GAME_KEYS = {normalize_command(text) for text in _GAME_PHRASES} | {'открой CS2'}


class HelpAwareSTT:
    def __init__(self, model, sample_rate=16000, *, stt_factory=VoskSTT, expects_reply=None):
        self.model, self.rate, self.factory = model, sample_rate, stt_factory
        self.full = stt_factory(model, sample_rate)
        # Two alternate spellings in the same grammar split acoustic confidence.
        self.short = stt_factory(model, sample_rate, grammar=["хелп", "[unk]"])
        self.verifier = None
        self.expects_reply = expects_reply
        self.reply_verifier = None
        self.game_verifier = None
        self.buffer = bytearray()
        self.limit = sample_rate * 2 * 4

    def _verified_help(self, candidate):
        if (candidate is None or candidate.text != "хелп" or len(candidate.words) != 1
                or candidate.confidence < .9 or not .18 <= candidate.words[0].duration <= 1.5):
            return None
        if self.verifier is None:
            self.verifier = self.factory(self.model, self.rate)
        else:
            self.verifier.reset()
        words = self._replay(self.verifier)
        if (len(words) != 1 or words[0].text.casefold() not in _PHONETIC_HELP
                or words[0].confidence < .4 or not .18 <= words[0].duration <= 1.5):
            return None
        word = candidate.words[0]
        return Transcript("help", (Word("help", word.confidence, word.start, word.end),))

    def _replay(self, decoder):
        words = []
        for start in range(0, len(self.buffer), self.rate // 10):
            result = decoder.feed(bytes(self.buffer[start:start + self.rate // 10]))
            if result:
                words.extend(result.words)
        tail = decoder.finish()
        if tail:
            words.extend(tail.words)
        return words

    def _check_reply(self, full):
        if (not full or len(full.words) != 1 or full.confidence < .30
                or (full.text != "год" and (parse_reply(full.text) is None or full.confidence >= .65))
                or self.expects_reply is None or not self.expects_reply()):
            return full
        if full.text == "год" and full.confidence >= .65:
            # Reset the language context for this utterance. A clear "год" remains unrelated to consent.
            isolated = self._replay(self.factory(self.model, self.rate))
            if (len(isolated) != 1 or isolated[0].text not in {"го", "год"}
                    or (isolated[0].text == "год" and not .30 <= isolated[0].confidence < .65)):
                return full
        if self.reply_verifier is None:
            grammar = [w for w in CHOICES if w != "go"] + ["год", "гол", "код", "не", "[unk]"]
            self.reply_verifier = self.factory(self.model, self.rate, grammar=grammar)
        else:
            self.reply_verifier.reset()
        words = self._replay(self.reply_verifier)
        if len(words) != 1 or words[0].confidence < .80 or not .12 <= words[0].duration <= 1.5:
            return full
        word = words[0]
        # Never turn an uncertain negative into an approval. The observed
        # acoustic confusion год/го needs a second pass that can also choose год.
        if word.text != full.text and not (full.text == "год" and word.text == "го"):
            return full
        if parse_reply(word.text) is None:
            return full
        return Transcript(word.text, (word,))

    def _check_game(self, full):
        if not full or not .20 <= full.confidence < .65:
            return full
        key = normalize_command(full.text)
        if key not in _GAME_KEYS:
            return full
        if self.game_verifier is None:
            phrases = sorted(_GAME_PHRASES | {'открой кэс два', 'запусти кэс два', 'закрой',
                                               'нет', 'отмена', 'стоп', '[unk]'})
            self.game_verifier = self.factory(self.model, self.rate, grammar=phrases)
        else:
            self.game_verifier.reset()
        words = tuple(self._replay(self.game_verifier))
        verified = Transcript(' '.join(word.text for word in words), words)
        if verified.confidence >= .85 and normalize_command(verified.text) == key:
            return verified
        return full

    def feed(self, pcm):
        if not pcm or len(pcm) % 2:
            return None
        self.buffer.extend(pcm[-self.limit:])
        if len(self.buffer) > self.limit:
            del self.buffer[:-self.limit]
        result = self.full.feed(pcm)
        help_result = self._verified_help(self.short.feed(pcm))
        if help_result:
            self.reset()
            return help_result
        if result:
            result = self._check_game(self._check_reply(result))
            self.buffer.clear()
            self.short.reset()
        return result

    def finish(self):
        result = self.full.finish()
        help_result = self._verified_help(self.short.finish())
        result = help_result or self._check_game(self._check_reply(result))
        self.reset()
        return result

    def reset(self):
        self.full.reset()
        self.short.reset()
        self.buffer.clear()
        if self.verifier is not None:
            self.verifier.reset()
