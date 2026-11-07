"""Map only whole app commands to registered names. Preserve the raw transcript for diagnostics."""
import re

from core.replies import parse_reply

APPS = {
    'steam': 'Steam', 'стим': 'Steam', 'стьим': 'Steam', 'стиим': 'Steam',
    'telegram': 'Telegram', 'телеграм': 'Telegram', 'телеграмм': 'Telegram', 'телеграмму': 'Telegram',
    'youtube': 'YouTube', 'you tube': 'YouTube', 'ютуб': 'YouTube', 'ютюб': 'YouTube', 'ютьюб': 'YouTube', 'ютубе': 'YouTube',
}
VERBS = {'open': 'открой', 'launch': 'запусти', 'close': 'закрой'}
# Whole targets observed in local Russian Vosk audio replays.
CS2_TRANSCRIPTS = {'кэс два', 'ка из два', 'кэрри с два', 'контэр страйк',
                   'режим ри градации', 'режим ри градаций'}


def normalize_command(raw):
    text = raw.strip()
    candidate = text.rstrip('.!?').strip()
    if '?' in text and parse_reply(candidate) is not None:
        return text  # A question must never become a power confirmation.
    if candidate.casefold() in CS2_TRANSCRIPTS:
        return 'CS2'
    opening, _, target = candidate.casefold().partition(' ')
    if (opening in {'открой', 'открывай', 'открыть', 'запусти', 'запустить', 'запускай', 'включи', 'включить', 'open', 'launch'}
            and target.strip() in CS2_TRANSCRIPTS):
        return 'открой CS2'
    match = re.fullmatch(r'(open|launch|close|открой|открывай|запусти|закрой)\s+(.+)', candidate, re.I)
    if match:
        verb, target = match.groups()
        if verb.casefold() in {'открой', 'открывай', 'запусти'} and target.casefold() in {'тим', 'системе'}:
            return f'{verb.casefold()} Steam'
        name = APPS.get(target.strip('«»"').casefold())
        if name:
            return f'{VERBS.get(verb.casefold(), verb.casefold())} {name}'
    # Keep spelling, letter case and punctuation inside literal file/clipboard payloads.
    if re.match(r'^(?:создай|установи буфер|запиши в буфер|найди|поищи|переименуй|перемести|скопируй текст)\b', text, re.I):
        return text
    return candidate
