import json
from pathlib import Path
import pytest
from core.engine import Engine
from core.models import Command, Result

SECRET='SECRET_AUDIT_MARKER'
@pytest.mark.parametrize('text',[
    'открой сайт https://demo:'+SECRET+'@example.com',
    'открой сайт https://example.com/?token='+SECRET,
    'найди в интернете '+SECRET,
    'буфер '+SECRET,
    'буфер '+SECRET+'\x00',
    'установить буфер '+SECRET+'\x00',
    'неизвестная фраза '+SECRET,
])
def test_sensitive_payload_not_persisted_even_when_parse_rejected(tmp_path,caplog,text):
    class Handler:
        def execute(self,intent,context):return Result.fail('Операция отклонена.')
    root=Path(__file__).resolve().parents[1]
    events=[]
    engine=Engine({'_resource_root':str(root),'history':{'enabled':True}},tmp_path,events.append,
                  registry={'clipboard':Handler(),'browser':Handler()})
    try:
        result=engine.execute(Command(text))
        assert not result.verified
        assert SECRET not in json.dumps(events,ensure_ascii=False)
        assert SECRET not in json.dumps(engine.history.recent(),ensure_ascii=False)
        for file in tmp_path.glob('history.sqlite3*'):
            assert SECRET.encode() not in file.read_bytes()
        assert SECRET not in caplog.text
    finally:engine.close()
    assert SECRET.encode() not in (tmp_path/'history.sqlite3').read_bytes()
