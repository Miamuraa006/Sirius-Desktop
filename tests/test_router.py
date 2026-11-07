from pathlib import Path
import json
import pytest
from core.context import Context


def router(tmp_path):
    assert (Path(__file__).parents[1] / 'core/intent_router.py').exists(), 'Router not implemented'
    from core.intent_router import IntentRouter
    path = tmp_path / 'volume'
    path.mkdir()
    (path / 'phrases.json').write_text(json.dumps({'skill':'volume','rules':[
        {'action':'adjust','patterns':['громче'], 'parameters':{'delta':20}},
        {'action':'adjust','patterns':['ещё громче'], 'parameters':{'delta':10}},
        {'action':'set','patterns':[r'громкость(?: на)? (?P<value>-?\d+)(?: ?%| процентов?)?']}
    ]},ensure_ascii=False),encoding='utf8')
    return IntentRouter(tmp_path)

@pytest.mark.parametrize('phrase,action,value', [
    ('громче','adjust',20),('ещё громче','adjust',10),('ЕЩЕ ГРОМЧЕ','adjust',10),
    ('громкость на 70%','set',70),('громкость 70 процентов','set',70),
    ('громкость семьдесят','set',70),('громкость сто двадцать','set',100),
    ('громкость -20','set',0)])
def test_fullmatch_number_normalization_and_clamp(tmp_path,phrase,action,value):
    intent=router(tmp_path).parse(phrase,Context())
    assert intent.action==action
    assert intent.parameters.get('value',intent.parameters.get('delta'))==value

@pytest.mark.parametrize('phrase',['пожалуйста запусти cmd громче','громкость 1.5','громкость семьдесят семьдесят','громче потом тише','шшш'])
def test_no_substring_or_invalid_numbers(tmp_path,phrase):
    assert router(tmp_path).parse(phrase,Context()) is None
