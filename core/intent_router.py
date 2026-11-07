"""Deterministic full-match grammar; literal captures are never casefolded."""
from __future__ import annotations
import json
import re
from pathlib import Path
from core.models import Intent
from core.context import Context

from core.capabilities import SKILL_IDS

ONES = dict(zip('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split(), range(20)))
TENS = dict(zip('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(), range(20, 100, 10)))
NUMBERS = ONES | TENS | {'сто': 100}
NUMBER_RE = re.compile(r'\b(?:' + '|'.join(NUMBERS) + r')(?:\s+(?:' + '|'.join(NUMBERS) + r'))*\b', re.I)


def normalize(text: str) -> str:
    return text.replace('ё', 'е').replace('Ё', 'Е')


def number_words(text: str) -> str:
    def convert(match):
        words = match.group().lower().split()
        values = [NUMBERS[w] for w in words]
        # Canonical hundreds + tens + ones, never sum malformed repeated numbers.
        remaining = list(values)
        total = 0
        if remaining and remaining[0] == 100:
            total = remaining.pop(0)
        if remaining and remaining[0] >= 20 and remaining[0] < 100:
            total += remaining.pop(0)
            if remaining and 1 <= remaining[0] <= 9:
                total += remaining.pop(0)
        elif remaining:
            total += remaining.pop(0)
        return str(total) if not remaining else match.group()
    return NUMBER_RE.sub(convert, text)


class IntentRouter:
    def __init__(self, skills_root: Path, config: dict | None = None):
        self.rules = []
        self.config = config or {}
        for skill in SKILL_IDS:
            path = Path(skills_root) / skill / 'phrases.json'
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('skill') != skill:
                raise ValueError(f'Неверный словарь навыка {skill}')
            for rule in data['rules']:
                for pattern in rule['patterns']:
                    self.rules.append((skill, rule['action'], dict(rule.get('parameters', {})),
                                       re.compile(normalize(pattern), re.I | re.S)))

    def parse(self, text: str, context: Context | None = None) -> Intent | None:
        if not isinstance(text, str) or not text.strip() or len(text) > 16384 or '\x00' in text:
            return None
        # lstrip removes command indentation only; payload trailing whitespace remains.
        raw = text.lstrip()
        normalized = normalize(raw)
        candidates = []
        for skill, action, fixed, pattern in self.rules:
            used = raw
            match = pattern.fullmatch(normalized)
            if match is None and not ('text' in pattern.groupindex):
                used = raw.strip()
                match = pattern.fullmatch(normalize(used))
            if match is None and skill in ('volume', 'brightness'):
                used = number_words(normalize(raw.strip()))
                match = pattern.fullmatch(used)
            if match is None:
                continue
            parameters = dict(fixed)
            for name, value in match.groupdict().items():
                if value is None:
                    continue
                # Same-length normalization permits slicing exact original payload/path.
                value = used[match.start(name):match.end(name)]
                if name in ('value', 'delta', 'step'):
                    try:
                        value = int(value)
                    except (ValueError, OverflowError):
                        return None
                    if name == 'value':
                        value = max(0, min(100, value))
                parameters[name] = value
            candidate = Intent(skill, action, parameters)
            if candidate not in candidates:
                candidates.append(candidate)
        if not candidates:
            return None
        # A generic app name must not swallow more specific file/browser grammar.
        specific = [c for c in candidates if c.skill != 'applications']
        if len(specific) == 1:
            return specific[0]
        if len(candidates) != 1:
            return None
        return candidates[0]
