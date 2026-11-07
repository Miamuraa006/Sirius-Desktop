from pathlib import Path
from core.models import Command,Result


def test_history_roundtrip_redaction_disable_clear(tmp_path):
    assert (Path(__file__).parents[1]/'storage/history.py').exists(), 'History store missing'
    from storage.history import History
    p=tmp_path/'history.sqlite3'
    h=History(p,enabled=True,retention_days=30)
    h.append(Command('CPU'),'system_monitor',Result.ok('CPU: 4%'), '2026-10-26T12:00:00+00:00')
    assert h.recent()[0]['text']=='CPU'
    h.clear();assert h.recent()==[]
    h.close()
    disabled=History(tmp_path/'disabled.sqlite3',enabled=False)
    disabled.append(Command('CPU'),'system_monitor',Result.ok('CPU: 5%'))
    assert not (tmp_path/'disabled.sqlite3').exists()
    disabled.close()
