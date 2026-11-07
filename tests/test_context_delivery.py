from pathlib import Path
from core.engine import Engine

def test_external_window_identity_snapshot_reaches_native_context(tmp_path):
    e=Engine({'_resource_root':str(tmp_path),'history':{'enabled':False}},tmp_path,registry={})
    try:
        e.set_window_context(321,654)
        ctx=e._context('desktop')
        assert ctx.last_window==321
        assert ctx.data['last_window_pid']==654
        e.set_window_context(456,987)
        ctx=e._context('desktop')
        assert ctx.last_window==456 and ctx.data['last_window_pid']==987
        assert ctx.data.get('last_window_created') is None
    finally:e.close()
