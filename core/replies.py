"""Whole-utterance replies shared by every pending yes/no request."""
YES = ('да', 'да да', 'да-да', 'да, да', 'давай', 'го', 'go', 'гоу', 'ага', 'подтверждаю')
NO = ('нет', 'не надо', 'отмена', 'отмени')
CHOICES = {**dict.fromkeys(YES, True), **dict.fromkeys(NO, False)}


def parse_reply(text: str) -> bool | None:
    key = ' '.join(text.casefold().strip().rstrip('.!').split())
    return CHOICES.get(key)
