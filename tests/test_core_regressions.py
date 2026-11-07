from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from core.engine import Engine
from core.models import Command,Result
from core.context import Context
from core.intent_router import IntentRouter
from storage.history import History
from datetime import datetime,timedelta,timezone


def test_serial_pipeline_preserves_order_and_no_parallel_handler(tmp_path):
    p=tmp_path/'skills'/'volume';p.mkdir(parents=True)
    (p/'phrases.json').write_text(json.dumps({'skill':'volume','rules':[{'action':'set','patterns':[r'громкость (?P<value>\d+)']}]}),encoding='utf8')
    class Handler:
        active=0
        overlap=False
        def execute(self,intent,ctx):
            self.active+=1
            if self.active>1:self.overlap=True
            time.sleep(.01)
            self.active-=1
            return Result.ok('Проверено')
    h=Handler();e=Engine({'_resource_root':str(tmp_path),'history':{'enabled':False}},tmp_path,lambda event: (_ for _ in ()).throw(RuntimeError('subscriber')),registry={'volume':h})
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(lambda n:e.execute(Command('громкость '+str(n))),range(10)))
        assert all(r.verified for r in results) and not h.overlap
        assert len(e.history.recent())==10
    finally:e.close()


def test_literal_captures_preserve_case_yo_spaces_and_punctuation(tmp_path):
    p=tmp_path/'clipboard';p.mkdir()
    (p/'phrases.json').write_text(json.dumps({'skill':'clipboard','rules':[{'action':'set','patterns':[r'буфер (?P<text>.+)']}]}),encoding='utf8')
    r=IntentRouter(tmp_path)
    payload=' ЁЖ C++\n  Key:Case  '
    assert r.parse('буфер '+payload).parameters['text']==payload


def test_history_retention_is_applied_during_long_running_session(tmp_path):
    h=History(tmp_path/'history.db',retention_days=1)
    try:
        old=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        h.append(Command('старое'),'system_monitor',Result.ok('ok'),old)
        h.append(Command('новое'),'system_monitor',Result.ok('ok'))
        assert [x['text'] for x in h.recent()]==['новое']
    finally:h.close()
