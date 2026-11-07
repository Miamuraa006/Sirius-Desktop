"""Real Qt host lifecycle, injectable native voice/hotkey boundaries only."""
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from test_ui_bridge import FakeEngine, wait_for


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_voice_hotkey_and_tray_exit_stop_cleanly_off_gui(app, monkeypatch):
    from ui import app as host
    assert hasattr(host, "ApplicationRuntime"), "Voice/core lifecycle is missing"
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QSystemTrayIcon
    class TrayBoundary(QObject):
        activated = Signal(object)
        Trigger, DoubleClick, Warning = QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Warning
        def __init__(self, icon, parent):
            super().__init__(parent)
            self.visible = False
        @staticmethod
        def isSystemTrayAvailable(): return True
        def setToolTip(self, text): pass
        def setContextMenu(self, menu): self.menu = menu
        def show(self): self.visible = True
        def hide(self): self.visible = False
        def isVisible(self): return self.visible
        def showMessage(self, *args): pass
    monkeypatch.setattr(host, "QSystemTrayIcon", TrayBoundary)
    from ui.bridge import Bridge
    trace = []
    created = {}
    class Voice:
        def __init__(self, config, on_text, on_state, on_level, is_recognized, on_error):
            self.callbacks = (on_text, on_state, on_level, is_recognized)
            self.running = False
            created["voice"] = self
        def start(self):
            trace.append(("voice-start", threading.get_ident()))
            self.running = True
        def activate(self):
            trace.append(("activate", threading.get_ident()))
            self.callbacks[1]("listening")
        def set_enabled(self, value):
            trace.append((f"enabled-{value}", threading.get_ident()))
        def command_completed(self, recognized=True):
            trace.append((f"completed-{recognized}", threading.get_ident()))
        def stop(self):
            trace.append(("voice-stop", threading.get_ident()))
            self.running = False
    class Hotkey:
        def __init__(self, callback, modifiers=1, key=77, on_error=None):
            assert (modifiers, key) == (1, 77)
            self.callback = callback
            self.running = False
            created["hotkey"] = self
        def start(self):
            trace.append(("hotkey-start", threading.get_ident()))
            self.running = True
        def stop(self):
            trace.append(("hotkey-stop", threading.get_ident()))
            self.running = False
    bridge = Bridge(FakeEngine, command_factory=lambda **kw: SimpleNamespace(**kw))
    ui = host.DesktopUi(app, bridge, enable_tray=True)
    runtime = host.ApplicationRuntime(ui, {"voice": {"enabled": True}},
                                      voice_factory=Voice, hotkey_factory=Hotkey)
    try:
        wait_for(lambda: any(name == "hotkey-start" for name, _ in trace))
        assert set(ui.actions) == {"show", "activate", "microphone", "clear", "exit"}
        thread = threading.Thread(target=created["hotkey"].callback)
        thread.start(); thread.join()
        wait_for(lambda: any(name == "activate" for name, _ in trace))
        wait_for(lambda: bridge.visualState == "listening")
        ui.actions["microphone"].trigger()
        wait_for(lambda: any(name == "enabled-False" for name, _ in trace))
        created["voice"].callbacks[0]("cpu")
        wait_for(lambda: any(name == "completed-True" for name, _ in trace))
        ui.actions["exit"].trigger()
        wait_for(lambda: runtime.is_closed)
        assert bridge.isClosed
        assert not ui.tray.isVisible()
        assert not created["voice"].running and not created["hotkey"].running
        assert all(thread != threading.get_ident() for _, thread in trace)
        assert len({thread for _, thread in trace}) == 1
    finally:
        ui.shutdown()
        wait_for(lambda: runtime.is_closed)
        ui.dispose()


def test_run_smoke_writes_report_real_scenegraph_and_waits_for_shutdown(app, monkeypatch, tmp_path):
    from ui import app as host
    from core import engine
    import json
    engines = []
    def factory(config, data_dir, event_callback):
        instance = FakeEngine(event_callback)
        engines.append(instance)
        return instance
    monkeypatch.setattr(engine, "Engine", factory)
    assert callable(getattr(host, "run", None))
    result = host.run({"ui": {"chat_visible": False}}, tmp_path / "profile",
                      smoke_output=tmp_path / "smoke", no_voice=True)
    assert result == 0
    report = json.loads((tmp_path / "smoke" / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["shutdown_clean"] is True
    assert report["remaining_workers"] == []
    assert report["qml_errors"] == []
    assert len(report["results"]) == 1
    assert report["results"][0]["verified"] is True
    assert engines[0].calls[0].text == "загрузка процессора"
    assert engines[0].closed
    assert (tmp_path / "smoke" / report["screenshots"]["pair"]).is_file()


def test_engine_boot_failure_is_reported_without_waiting_for_smoke_timeout(app, monkeypatch, tmp_path):
    from ui import app as host
    from core import engine
    import json
    import time
    def factory(*args, **kwargs):
        raise ImportError("unit test missing dependency")
    monkeypatch.setattr(engine, "Engine", factory)
    started = time.monotonic()
    assert host.run({}, tmp_path / "profile", smoke_output=tmp_path / "smoke", no_voice=True) == 1
    assert time.monotonic() - started < 10
    report = json.loads((tmp_path / "smoke" / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["shutdown_clean"] is True
    assert report["results"] == []
    assert "Engine initialization failed" in report["errors"]


def test_run_entry_point_exists_with_contract_signature():
    from ui import app as host
    import inspect
    assert callable(getattr(host, "run", None)), "Production run entry point is missing"
    parameters = inspect.signature(host.run).parameters
    assert list(parameters) == ["config", "data_dir", "smoke_output", "no_voice"]
    assert parameters["smoke_output"].default is None
    assert parameters["no_voice"].default is False
