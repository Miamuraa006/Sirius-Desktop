import importlib.util
from pathlib import Path
import json

def test_command_table_covers_every_declared_rule():
    assert importlib.util.find_spec('scripts.command_reference') is not None
    from scripts.command_reference import render
    root=Path(__file__).resolve().parents[1]
    text,counts=render(root)
    from core.intent_router import SKILL_IDS
    assert counts['skills']==len(SKILL_IDS)
    actual=[json.loads(p.read_text(encoding='utf8')) for p in (root/'skills').glob('*/phrases.json')]
    assert counts['rules']==sum(len(x['rules']) for x in actual)
    for data in actual:
        for rule in data['rules']:
            for example in rule['examples']:
                assert example.replace('|','&#124;') in text
