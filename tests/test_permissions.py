from pathlib import Path
import pytest
from core.models import Intent


def policy(tmp_path,clock=lambda:0):
    assert (Path(__file__).parents[1]/'security/permissions.py').exists(), 'Security policy missing'
    from security.permissions import PermissionPolicy
    root=tmp_path/'trusted'; root.mkdir(exist_ok=True)
    return PermissionPolicy({'files':{'root':str(root),'allowed_roots':[str(root)]}},clock=clock)


def test_trash_requires_single_use_session_bound_confirmation(tmp_path):
    p=policy(tmp_path)
    f=tmp_path/'trusted'/'one.txt'; f.write_text('one')
    prepared=p.prepare(Intent('files','trash',{'path':str(f)}),'a')
    assert prepared.status=='needs_confirmation'
    assert p.resolve('b',True)[0] is None
    intent,result=p.resolve('a',True)
    assert intent.action=='trash' and result is None
    assert p.resolve('a',True)[0] is None


def test_outside_root_requires_confirmation_and_expires(tmp_path):
    now=[0.0];p=policy(tmp_path,lambda:now[0])
    out=tmp_path/'outside.txt';out.write_text('x')
    assert p.prepare(Intent('files','open',{'path':str(out)}),'a').status=='needs_confirmation'
    now[0]=61
    assert p.resolve('a',True)[0] is None


def test_changed_file_invalidates_pending_action(tmp_path):
    p=policy(tmp_path);f=tmp_path/'trusted'/'one.txt';f.write_text('one')
    p.prepare(Intent('files','trash',{'path':str(f)}),'a')
    f.write_text('replacement')
    assert p.resolve('a',True)[0] is None

@pytest.mark.parametrize('path',[r'\\server\share\x',r'C:\Windows\win.ini',r'C:\test.txt:stream',r'..\escape.txt',r'\\?\C:\x'])
def test_reject_unsafe_paths(tmp_path,path):
    p=policy(tmp_path)
    assert p.prepare(Intent('files','open',{'path':path}),'a').status=='failed'


def test_no_arbitrary_executable_open(tmp_path):
    p=policy(tmp_path);f=tmp_path/'trusted'/'launch.cmd';f.write_text('noop')
    assert p.prepare(Intent('files','open',{'path':str(f)}),'a').status=='failed'


def test_new_command_cancels_old_confirmation(tmp_path):
    p=policy(tmp_path);f=tmp_path/'trusted'/'one.txt';f.write_text('one')
    p.prepare(Intent('files','trash',{'path':str(f)}),'a')
    p.prepare(Intent('volume','set',{'value':20}),'a')
    assert p.resolve('a',True)[0] is None
