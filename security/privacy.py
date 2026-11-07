"""Privacy projection is independent of parsing/validation and never executes text."""
from __future__ import annotations
import re
from core.models import Intent
from core.replies import parse_reply

_URL = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s]+')


def display_command(text: str, intent: Intent | None) -> str:
    """Keep execution payload in memory, but never persist rejected arbitrary text.

    URLs (including paths/query/fragment), search strings and clipboard payloads
    are sensitive by default. No attempt to guess whether a token is a password.
    """
    if parse_reply(text) is not None:
        return text.strip().casefold()
    if intent is None:
        return 'Нераспознанная команда: [содержимое скрыто]'
    if intent.skill == 'clipboard' and intent.action == 'set':
        return 'Установить буфер обмена: [содержимое скрыто]'
    if intent.skill == 'browser' and intent.action in {'open','search'}:
        return ('Открыть URL' if intent.action == 'open' else 'Поиск в браузере') + ': [содержимое скрыто]'
    return _URL.sub('[URL скрыт]',text)
