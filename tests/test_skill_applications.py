"""Registered application lifecycle; native processes/windows are always fake."""
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest
from core.models import Intent
from core.context import Context


def module():
    assert (Path(__file__).parents[1] / 'skills/applications/handler.py').is_file(), 'applications handler missing'
    return importlib.import_module('skills.applications.handler')


class Apps:
    def __init__(self):
        self.items = []
        self.actions = []
        self.accept_open = True
        self.accept_close = True
        self.valid = True
        self.next_hwnd = 10

    def prepare(self, spec):
        return spec

    def focus(self, window):
        self.actions.append(('focus', window.hwnd))
        return self.validate(window)

    def find_windows(self, spec):
        return [window for window in self.items if window.app == spec.name]

    def launch(self, spec):
        self.actions.append(('launch',spec.name,spec.command))
        if self.accept_open:
            self.next_hwnd += 1
            self.items.append(SimpleNamespace(app=spec.name,hwnd=self.next_hwnd,pid=20,created=1.0,process_name='notepad.exe',executable='C:/Windows/System32/notepad.exe'))

    def validate(self, window):
        return self.valid and window in self.items

    def close(self, window):
        self.actions.append(('close',window.hwnd))
        if self.accept_close:
            self.items.remove(window)


def test_open_registered_alias_verifies_window_and_saves_context():
    apps, ctx = Apps(), Context()
    result = module().Handler(adapter=apps).execute(Intent('applications','open',{'app':'блокнот'}), ctx)
    assert result.verified and result.details['app'] == 'notepad'
    assert ctx.last_app == 'notepad' and ctx.last_window == 11 and ctx.data['last_window_pid'] == 20
    assert apps.actions[0][0:2] == ('launch','notepad')


@pytest.mark.parametrize('name,canonical', [('калькулятор','calculator'),('проводник','explorer'),('браузер','browser')])
def test_builtin_allowlist(name, canonical):
    apps = Apps()
    result = module().Handler(adapter=apps).execute(Intent('applications','open',{'app':name}), Context())
    assert result.verified and result.details['app'] == canonical


@pytest.mark.parametrize('app', ['cmd.exe','powershell','notepad.exe & calc.exe','C:/tool.exe','unknown',None,True])
def test_speech_is_not_a_command_line(app):
    apps = Apps()
    result = module().Handler(adapter=apps).execute(Intent('applications','open',{'app':app}), Context())
    assert result.status == 'failed' and not apps.actions


@pytest.mark.parametrize('action', ['close','restart'])
def test_close_and_restart_require_engine_confirmation(action):
    apps = Apps()
    result = module().Handler(adapter=apps).execute(Intent('applications',action,{'app':'блокнот','confirmed':True}), Context())
    assert result.status == 'needs_confirmation' and not apps.actions


def test_confirmed_close_verifies_window_disappearance():
    apps = Apps()
    handler = module().Handler(adapter=apps)
    ctx = Context(data={'confirmed':True})
    handler.execute(Intent('applications','open',{'app':'блокнот'}), ctx)
    result = handler.execute(Intent('applications','close',{'app':'блокнот'}), ctx)
    assert result.verified and not apps.items
    assert [a[0] for a in apps.actions] == ['launch','close']


def test_unsaved_document_dialog_prevents_success_and_restart(monkeypatch):
    apps = Apps()
    apps.accept_close = False
    handler = module().Handler(adapter=apps)
    ctx = Context(data={'confirmed':True})
    handler.execute(Intent('applications','open',{'app':'блокнот'}), ctx)
    result = handler.execute(Intent('applications','restart',{'app':'блокнот'}), ctx)
    assert result.status == 'failed' and [a[0] for a in apps.actions].count('launch') == 1


def test_restart_waits_for_old_window_before_launch():
    apps = Apps()
    handler = module().Handler(adapter=apps)
    ctx = Context(data={'confirmed':True})
    handler.execute(Intent('applications','open',{'app':'блокнот'}), ctx)
    result = handler.execute(Intent('applications','restart',{'app':'блокнот'}), ctx)
    assert result.verified and [a[0] for a in apps.actions] == ['launch','close','launch']
    assert ctx.last_window == 12


@pytest.mark.parametrize('running', [True,False])
def test_status_reports_observed_state_without_launch(running):
    apps = Apps()
    handler = module().Handler(adapter=apps)
    if running:
        handler.execute(Intent('applications','open',{'app':'блокнот'}), Context())
    apps.actions.clear()
    result = handler.execute(Intent('applications','status',{'app':'блокнот'}), Context())
    assert result.verified and result.details['running'] is running and not apps.actions


def test_launch_without_window_readback_is_failed():
    apps = Apps()
    apps.accept_open = False
    result = module().Handler(adapter=apps).execute(Intent('applications','open',{'app':'блокнот'}), Context())
    assert result.status == 'failed' and not result.verified


def test_custom_alias_only_uses_explicit_configured_arguments(tmp_path):
    exe = tmp_path/'editor.exe'
    exe.write_bytes(b'fake fixture; never executed')
    config = {'applications': {'editor': {'command':[str(exe),'--safe-mode'], 'process_names':['editor.exe'], 'aliases':['редактор']}}}
    apps = Apps()
    result = module().Handler(adapter=apps,config=config).execute(Intent('applications','open',{'app':'редактор'}), Context())
    assert result.verified and apps.actions[0][2] == (str(exe),'--safe-mode')
    assert not module().Handler(adapter=apps,config=config).execute(Intent('applications','open',{'app':'редактор --eval evil'}), Context()).verified


@pytest.mark.parametrize('command,process', [(['cmd.exe','/c','calc'],'cmd.exe'),(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'],'powershell.exe'),(['relative/editor.exe'],'editor.exe'),(['calc.exe'],'svchost.exe'),('notepad.exe','notepad.exe')])
def test_unsafe_configuration_is_rejected(command, process):
    config = {'applications':{'unsafe':{'command':command,'process_names':[process],'aliases':['опасное']}}}
    apps = Apps()
    result = module().Handler(adapter=apps,config=config).execute(Intent('applications','open',{'app':'опасное'}), Context())
    assert result.status == 'failed' and not apps.actions


def test_production_default_is_real_native_adapter():
    native = module().Handler().adapter
    assert native is not None, 'Production applications adapter is missing'
    assert isinstance(native, module().WindowsApplicationAdapter)


def test_native_adapter_launches_only_explicit_allowlist(monkeypatch):
    calls = []
    monkeypatch.setattr(module().subprocess, 'Popen', lambda argv, **kw: calls.append((argv, kw)))
    adapter = module().WindowsApplicationAdapter()
    adapter.launch(module().DEFAULT_APPS[0])
    argv, options = calls.pop()
    assert Path(argv[0]).name.casefold() == 'notepad.exe'
    assert Path(argv[0]).is_absolute() and options['shell'] is False
    assert len(argv) == 1
    with pytest.raises(ValueError):
        adapter.launch(module().AppSpec('bad', ('cmd.exe', '/c', 'calc'), ('cmd.exe',)))
    assert calls == []


def test_native_adapter_matches_configured_executable_not_just_name(tmp_path):
    from skills.windows.native import WindowRef
    executable = tmp_path / 'editor.exe'
    executable.write_bytes(b'never executed')
    wanted = WindowRef(10, 20, 'editor.exe', 'Editor', 1, str(executable))
    impostor = WindowRef(11, 21, 'editor.exe', 'Editor', 2, 'C:/Other/editor.exe')
    windows = SimpleNamespace(windows=lambda: [wanted, impostor], validate=lambda w: True)
    adapter = module().WindowsApplicationAdapter(windows=windows)
    spec = module().AppSpec('editor', (str(executable),), ('editor.exe',))
    assert adapter.find_windows(spec) == [wanted]


def test_uwp_calculator_frame_requires_content_process_identity():
    from skills.windows.native import WindowRef
    host = WindowRef(100, 20, 'applicationframehost.exe', 'Calculator', 1, 'C:/Windows/System32/ApplicationFrameHost.exe')
    content = WindowRef(101, 21, 'calculator.exe', '', 2, 'C:/Program Files/WindowsApps/Calculator.exe')
    children = [content]
    closed = []
    windows = SimpleNamespace(windows=lambda: [host], validate=lambda w: True,
                              children=lambda w: list(children), close=lambda w: closed.append(w.hwnd))
    adapter = module().WindowsApplicationAdapter(windows=windows)
    matches = adapter.find_windows(module().DEFAULT_APPS[1])
    assert len(matches) == 1 and matches[0].hwnd == 100
    assert adapter.validate(matches[0])
    children.clear()
    assert not adapter.validate(matches[0])
    with pytest.raises(ValueError):
        adapter.close(matches[0])
    assert not closed


def test_stale_identity_is_never_closed():
    apps = Apps()
    handler = module().Handler(adapter=apps)
    handler.execute(Intent('applications','open',{'app':'блокнот'}), Context())
    apps.valid = False
    apps.actions.clear()
    result = handler.execute(Intent('applications','close',{'app':'блокнот'}), Context(data={'confirmed':True}))
    assert result.status == 'failed' and not apps.actions
