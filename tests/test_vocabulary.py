"""Every shipped rule/example exercises the real, fullmatch IntentRouter."""
import importlib
import json
from pathlib import Path

import pytest
from core.context import Context
from core.intent_router import IntentRouter, SKILL_IDS

ROOT = Path(__file__).parents[1]
ACTIONS = {
    'volume': {'set', 'adjust', 'mute', 'unmute'},
    'brightness': {'set', 'adjust'},
    'applications': {'open_app', 'close_app', 'focus_app', 'status', 'restart', 'list'},
    'windows': {'minimize', 'maximize', 'restore', 'switch', 'desktop', 'activate'},
    'browser': {'open', 'search', 'new_tab', 'close_tab', 'refresh', 'back', 'forward', 'next_tab', 'previous_tab', 'reopen_tab'},
    'media': {'play_pause', 'pause', 'play', 'next', 'previous', 'stop'},
    'files': {'mkdir', 'touch', 'open', 'rename', 'move', 'trash'},
    'clipboard': {'status', 'copy', 'paste', 'select_all', 'set'},
    'screenshot': {'full', 'window'},
    'power': {'restart', 'shutdown'},
    'system_monitor': {'cpu', 'ram', 'disk', 'battery', 'temperature'},
}


@pytest.mark.parametrize('skill', SKILL_IDS)
def test_every_skill_ships_all_actions_and_unambiguous_examples(skill):
    path = ROOT / 'skills' / skill / 'phrases.json'
    assert path.is_file(), f'{skill} vocabulary is missing'
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['skill'] == skill
    assert {r['action'] for r in data['rules']} == ACTIONS[skill]
    router = IntentRouter(ROOT / 'skills')
    for rule in data['rules']:
        assert rule['patterns'] and rule['examples'], rule
        for pattern in rule['patterns']:
            assert not pattern.startswith('^') and not pattern.endswith('$')
        for phrase in rule['examples']:
            intent = router.parse(phrase, Context())
            assert intent is not None, (skill, rule['action'], phrase, 'ambiguous or unmatched')
            assert (intent.skill, intent.action) == (skill, rule['action']), phrase
            for name, value in rule.get('parameters', {}).items():
                assert intent.parameters[name] == value, phrase


@pytest.mark.parametrize('phrase,skill,action,parameters', [
    ('громче', 'volume', 'adjust', {'delta': 20}),
    ('тише', 'volume', 'adjust', {'delta': -20}),
    ('ЕЩЁ ГРОМЧЕ', 'volume', 'adjust', {'delta': 10}),
    ('еще тише', 'volume', 'adjust', {'delta': -10}),
    ('ярче', 'brightness', 'adjust', {'delta': 20}),
    ('темнее', 'brightness', 'adjust', {'delta': -20}),
    ('ещё ярче', 'brightness', 'adjust', {'delta': 10}),
    ('ещё темнее', 'brightness', 'adjust', {'delta': -10}),
    ('громкость семьдесят', 'volume', 'set', {'value': 70}),
    ('яркость сто двадцать', 'brightness', 'set', {'value': 100}),
    ('громкость -20', 'volume', 'set', {'value': 0}),
    ('закрой его', 'applications', 'close_app', {'app': 'его'}),
    ('установи буфер обмена СекРет Ёж  TWO  ', 'clipboard', 'set', {'text': 'СекРет Ёж  TWO  '}),
    ('создай папку "MiXeD Ёж"', 'files', 'mkdir', {'path': 'MiXeD Ёж'}),
    ('переименуй "My A.txt" в "My B.txt"', 'files', 'rename', {'path': 'My A.txt', 'destination': 'My B.txt'}),
    ('открой сайт https://example.com/Case?Q=Ёж', 'browser', 'open', {'url': 'https://example.com/Case?Q=Ёж'}),
    ('найди в интернете C++: API Ёж', 'browser', 'search', {'query': 'C++: API Ёж'}),
])
def test_production_grammar_preserves_meaning_and_literal_payload(phrase, skill, action, parameters):
    result = IntentRouter(ROOT / 'skills').parse(phrase)
    assert result is not None
    assert (result.skill, result.action, result.parameters) == (skill, action, parameters)


@pytest.mark.parametrize('phrase', ['громкость 1.5', 'яркость семьдесят семьдесят',
    'громче затем тише', 'шшшш', 'это слово громче внутри предложения',
    'переименуй A.txt в B.txt', 'удали всё безвозвратно'])
def test_production_grammar_does_not_match_noise_or_unquoted_paths(phrase):
    assert IntentRouter(ROOT / 'skills').parse(phrase) is None


@pytest.mark.parametrize('skill', SKILL_IDS)
def test_every_production_handler_has_native_default_and_collectable_package(skill):
    assert (ROOT / 'skills' / '__init__.py').is_file()
    assert (ROOT / 'skills' / skill / '__init__.py').is_file()
    module = importlib.import_module(f'skills.{skill}.handler')
    assert module.Handler().adapter is not None
