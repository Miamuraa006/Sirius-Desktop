"""No live window interaction: fake adapter and fake Win32 boundaries."""
from pathlib import Path
from types import SimpleNamespace
import importlib
import os
import pytest
from core.models import Intent
from core.context import Context


def module():
    assert (Path(__file__).parents[1] / 'skills/windows/handler.py').is_file(), 'windows handler missing'
    return importlib.import_module('skills.windows.handler')


def ref(hwnd=10, pid=20, name='notepad.exe', title='Notes'):
    return SimpleNamespace(hwnd=hwnd, pid=pid, process_name=name, title=title, created=1.0, executable='C:/Windows/System32/'+name)


class Windows:
    def __init__(self):
        self.items = [ref(), ref(11,21,'calc.exe','Calculator')]
        self.active = self.items[0]
        self.states = {10:'normal',11:'normal'}
        self.writes = []
        self.valid = True
        self.accept = True

    def windows(self):
        return list(self.items)

    def foreground(self):
        return self.active

    def window(self, hwnd):
        return next((w for w in self.items if w.hwnd == hwnd), None)

    def validate(self, window):
        return self.valid and self.window(window.hwnd) == window

    def state(self, window):
        return self.states[window.hwnd]

    def show(self, window, action):
        self.writes.append((window.hwnd, action))
        if self.accept:
            self.states[window.hwnd] = {'minimize':'minimized','maximize':'maximized','restore':'normal'}[action]

    def activate(self, window):
        self.writes.append((window.hwnd, 'activate'))
        if self.accept:
            self.active = window


def test_minimize_explicit_hwnd_verifies_state():
    win = Windows()
    ctx = Context()
    result = module().Handler(adapter=win).execute(Intent('windows','minimize',{'target':10}), ctx)
    assert result.verified and win.writes == [(10,'minimize')]
    assert ctx.last_window == 10 and ctx.data['last_window_pid'] == 20


@pytest.mark.parametrize('action,state', [('minimize','minimized'),('maximize','maximized'),('restore','normal')])
def test_geometry_action_is_read_back(action, state):
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows',action), Context())
    assert result.verified and win.states[10] == state and win.writes == [(10,action)]


def test_switch_activates_known_next_window():
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows','switch'), Context())
    assert result.verified and win.active.hwnd == 11


def test_activate_builtin_russian_alias_without_config():
    win = Windows()
    win.active = win.items[1]
    result = module().Handler(adapter=win).execute(Intent('windows', 'activate', {'target': 'блокнот'}), Context())
    assert result.verified and win.active.hwnd == 10


def test_window_handler_accepts_engine_window_pid_context_key():
    win = Windows()
    win.active = None
    context = Context(last_window=10, data={'window_pid': 20})
    result = module().Handler(adapter=win).execute(Intent('windows', 'minimize'), context)
    assert result.verified and win.states[10] == 'minimized'


def test_activate_exact_known_title():
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows','activate',{'target':'Calculator'}), Context())
    assert result.verified and win.active.hwnd == 11


def test_show_desktop_minimizes_and_verifies_all_windows():
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows','desktop'), Context())
    assert result.verified and set(win.states.values()) == {'minimized'}


@pytest.mark.parametrize('target', [True,-1,0,'calc;shutdown','Calcu',{},12])
def test_invalid_or_unknown_target_never_changes_a_window(target):
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows','activate',{'target':target}), Context())
    assert result.status == 'failed' and not win.writes


def test_ambiguous_title_is_not_guessed():
    win = Windows()
    win.items.append(ref(12,22,'notepad.exe','Notes'))
    result = module().Handler(adapter=win).execute(Intent('windows','activate',{'target':'Notes'}), Context())
    assert result.status == 'failed' and not win.writes


def test_own_ui_is_never_targeted():
    win = Windows()
    win.items[0] = ref(pid=os.getpid())
    win.active = win.items[0]
    result = module().Handler(adapter=win).execute(Intent('windows','minimize'), Context())
    assert result.status == 'failed' and not win.writes


def test_context_target_rejects_recycled_hwnd_pid():
    win = Windows()
    win.active = None
    ctx = Context(last_window=10, data={'last_window_pid':999})
    result = module().Handler(adapter=win).execute(Intent('windows','minimize'), ctx)
    assert result.status == 'failed' and not win.writes


def test_stale_native_identity_never_receives_write():
    win = Windows()
    win.valid = False
    result = module().Handler(adapter=win).execute(Intent('windows','minimize',{'target':10}), Context())
    assert result.status == 'failed' and not win.writes


def test_unacknowledged_native_write_is_failed(monkeypatch):
    win = Windows()
    win.accept = False
    result = module().Handler(adapter=win).execute(Intent('windows','maximize',{'target':10}), Context())
    assert result.status == 'failed' and not result.verified


def test_native_exception_is_converted_to_result():
    win = Windows()
    win.show = lambda *args: (_ for _ in ()).throw(OSError('private title'))
    result = module().Handler(adapter=win).execute(Intent('windows','minimize',{'target':10}), Context())
    assert result.status == 'failed' and 'private' not in result.message


def test_unknown_action_never_changes_windows():
    win = Windows()
    result = module().Handler(adapter=win).execute(Intent('windows','kill',{'target':10}), Context())
    assert result.status == 'failed' and not win.writes


class NativeAPI:
    def __init__(self):
        self.pid = 20
        self.calls = []
        self.state = 1
        self.gui = SimpleNamespace(
            IsWindow=lambda h: h == 10,
            IsWindowVisible=lambda h: True,
            GetWindowText=lambda h: 'Notes',
            GetClassName=lambda h: 'Notepad',
            GetForegroundWindow=lambda: 10,
            EnumWindows=lambda cb, arg: cb(10, arg),
            GetWindowPlacement=lambda h: (0,self.state,(0,0),(0,0),(0,0,100,100)),
            IsIconic=lambda h: self.state == 2,
            ShowWindow=lambda h, mode: self.calls.append(('show',h,mode)),
            SetForegroundWindow=lambda h: self.calls.append(('activate',h)),
            PostMessage=lambda *args: self.calls.append(('post',)+args),
        )
        self.process = SimpleNamespace(GetWindowThreadProcessId=lambda h: (1,self.pid))
        self.psutil = SimpleNamespace(Process=lambda pid: SimpleNamespace(
            name=lambda: 'notepad.exe', exe=lambda: 'C:/Windows/System32/notepad.exe', create_time=lambda: 1.0))


def native():
    assert (Path(__file__).parents[1] / 'skills/windows/native.py').is_file(), 'native window adapter missing'
    return importlib.import_module('skills.windows.native')


def test_real_window_adapter_checks_pid_before_show():
    api = NativeAPI()
    adapter = native().WindowsAdapter(api=(api.gui,api.process,api.psutil))
    window = adapter.window(10)
    assert window.pid == 20 and adapter.validate(window)
    adapter.show(window,'maximize')
    assert api.calls == [('show',10,3)]
    api.pid = 21
    with pytest.raises(ValueError):
        adapter.show(window,'minimize')
    assert len(api.calls) == 1


def test_native_close_is_wm_close_not_terminate():
    api = NativeAPI()
    adapter = native().WindowsAdapter(api=(api.gui,api.process,api.psutil))
    adapter.close(adapter.window(10))
    assert api.calls == [('post',10,0x10,0,0)]


def test_native_enumeration_and_state_readback():
    api = NativeAPI()
    adapter = native().WindowsAdapter(api=(api.gui,api.process,api.psutil))
    assert [w.hwnd for w in adapter.windows()] == [10]
    assert adapter.foreground().hwnd == 10
    assert adapter.state(adapter.window(10)) == 'normal'
    api.state = 2
    assert adapter.state(adapter.window(10)) == 'minimized'
    api.state = 3
    assert adapter.state(adapter.window(10)) == 'maximized'


def test_native_own_process_is_excluded():
    api = NativeAPI()
    api.pid = os.getpid()
    adapter = native().WindowsAdapter(api=(api.gui,api.process,api.psutil))
    assert adapter.windows() == [] and adapter.foreground() is None
