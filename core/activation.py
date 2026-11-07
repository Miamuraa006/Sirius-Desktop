"""Exact bilingual addressing; words inside unrelated text are not wake requests."""
import re

WAKE_WORDS = frozenset({"сириус", "sirius"})
_ADDRESS = re.compile(r"^\s*(?:сириус|sirius)(?=$|[\s,!:;?.—–-])[\s,!:;?.—–-]*", re.IGNORECASE)


def split_address(text: str) -> tuple[bool, str]:
    match = _ADDRESS.match(text)
    return (True, text[match.end():].strip()) if match else (False, text)
