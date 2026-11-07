from pathlib import Path
import json
from core.models import Command,Result

class Counter:
    def __init__(self): self.calls=[]
    def execute(self,intent,ctx):
        self.calls.append((intent,ctx.session_id))
        return Result.ok('Реально проверено')

def make(tmp_path):
    assert (Path(__file__).parents[1]/'core/engine.py').exists(), 'Engine missing'
    from core.engine import Engine
    for skill,rules in {
        'volume':[{'action':'adjust','patterns':['громче'],'parameters':{'delta':20}}],
        'applications':[{'action':'close','patterns':['закрой (?P<app>.+)']}],
        'clipboard':[{'action':'set','patterns':['буфер (?P<text>.+)']}]
    }.items():
        d=tmp_path/'skills'/skill;d.mkdir(parents=True)
        (d/'phrases.json').write_text(json.dumps({'skill':skill,'rules':rules},ensure_ascii=False),encoding='utf8')
    calls=Counter(); events=[]
    e=Engine({'_resource_root':str(tmp_path),'history':{'enabled':True}},tmp_path/'data',events.append,
             registry={s:calls for s in ['volume','applications','clipboard']})
    return e,calls,events


def test_text_voice_same_pipeline_unknown_audio_silent(tmp_path):
    e,c,events=make(tmp_path)
    try:
        assert e.execute(Command('громче')).verified
        assert e.execute(Command('громче','voice')).verified
        assert len(c.calls)==2
        assert [r['type'] for r in events]==['recognized','started','completed']*2
        assert e.execute(Command('шшш','voice')).status=='not_understood'
        assert len(events)==6 and len(e.history.recent())==2
    finally:e.close()


def test_confirmation_not_invented_by_caller_and_session_bound(tmp_path):
    e,c,events=make(tmp_path)
    try:
        assert e.execute(Command('закрой блокнот',session_id='a')).status=='needs_confirmation'
        assert not c.calls
        assert not e.execute(Command('подтверждаю',session_id='b')).verified
        assert e.execute(Command('подтверждаю',session_id='a')).verified
        assert len(c.calls)==1
        assert not e.execute(Command('подтверждаю',session_id='a')).verified
    finally:e.close()


def test_clipboard_payload_never_in_events_or_database(tmp_path):
    e,c,events=make(tmp_path)
    try:
        secret=' ПарОль Ёж\n  Spaces  '
        e.execute(Command('буфер '+secret))
        assert c.calls[0][0].parameters['text']==secret
        assert secret not in json.dumps(events,ensure_ascii=False)
        assert secret not in json.dumps(e.history.recent(),ensure_ascii=False)
        assert 'ПарОль' not in (tmp_path/'data'/'history.sqlite3').read_bytes().decode('utf8',errors='ignore')
    finally:e.close()


def test_unresolved_context_cannot_close_random_app(tmp_path):
    e,c,_=make(tmp_path)
    try:
        assert e.execute(Command('закрой его')).status=='failed'
        assert not c.calls
    finally:e.close()
