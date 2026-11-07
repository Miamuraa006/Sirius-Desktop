"""No real Windows commands, audio capture, hotkeys or stored history in units."""
import importlib.util
import os
import threading
import time
from types import SimpleNamespace

import pytest

# Units must not steal the user's keyboard focus. Live rendering is opt-in and
# production smoke always runs in a separate native Windows process.
if os.environ.get("SIRIUS_UI_LIVE") != "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(predicate, timeout=3000):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    assert predicate(), "Qt condition did not settle"


class FakeEngine:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.threads = [threading.get_ident()]
        self.history = SimpleNamespace(recent=lambda limit=200: [], clear=lambda: None)
        self.closed = False

    def set_window_context(self, hwnd, pid=None, session_id="desktop"):
        self.target = (hwnd, pid, session_id)

    def execute(self, command):
        self.threads.append(threading.get_ident())
        self.calls.append(command)
        if command.source == "voice" and command.text == "noise":
            return SimpleNamespace(status="not_understood", message="", verified=False, details={})
        text = "[скрыто]" if command.text.startswith("буфер ") else command.text
        base = dict(text=text, source=command.source, time="2026-01-01T12:30:00+04:00", skill="system_monitor")
        self.callback(dict(base, type="recognized"))
        self.callback(dict(base, type="started"))
        time.sleep(.04)
        result = dict(status="success", message="CPU: 12% (тест)", verified=True, details={})
        self.callback(dict(base, type="completed", result=result))
        return SimpleNamespace(**result)

    def close(self):
        self.threads.append(threading.get_ident())
        self.closed = True


def make_bridge():
    assert importlib.util.find_spec("ui.bridge") is not None, "Production bridge is missing"
    from ui.bridge import Bridge
    engines = []
    def factory(callback):
        engine = FakeEngine(callback)
        engines.append(engine)
        return engine
    return Bridge(factory, command_factory=lambda **kw: SimpleNamespace(**kw)), engines


def test_commands_are_serialized_off_gui_and_events_return_on_gui(app):
    bridge, engines = make_bridge()
    gui_thread = threading.get_ident()
    delivered_on = []
    bridge.commandFinished.connect(lambda *_: delivered_on.append(threading.get_ident()))
    try:
        wait_for(lambda: bridge.ready)
        assert bridge.submit("загрузка процессора")
        assert bridge.submit("подтверждаю")
        assert not bridge.submit("  ")
        ticks = []
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        wait_for(lambda: len(delivered_on) == 2)
        timer.stop()
        assert len(ticks) >= 2, "GUI must remain responsive while native executor waits"
        assert [c.text for c in engines[0].calls] == ["загрузка процессора", "подтверждаю"]
        assert {c.source for c in engines[0].calls} == {"text"}
        assert set(engines[0].threads).isdisjoint({gui_thread})
        assert len(set(engines[0].threads)) == 1
        assert delivered_on == [gui_thread, gui_thread]
        assert bridge.messages.rowCount() == 2
        assert bridge.messages.snapshot()[0]["verified"] is True
        assert bridge.messages.thread() == QThread.currentThread()
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)
    assert engines[0].closed


def test_voice_callbacks_are_queued_noise_not_logged_and_secrets_redacted(app):
    bridge, engines = make_bridge()
    try:
        wait_for(lambda: bridge.ready)
        thread = threading.Thread(target=lambda: (bridge.offer_voice_text("noise"),
                                                  bridge.offer_voice_state("listening"),
                                                  bridge.offer_voice_level(.63)))
        thread.start()
        thread.join()
        wait_for(lambda: len(engines[0].calls) == 1 and not bridge.busy)
        assert bridge.messages.rowCount() == 0
        assert bridge.audioLevel == pytest.approx(.63)
        secret = "буфер <private payload>"
        assert bridge.submit(secret)
        wait_for(lambda: not bridge.busy)
        assert engines[0].calls[-1].text == secret
        assert "<private payload>" not in str(bridge.messages.snapshot())
        assert bridge.messages.snapshot()[0]["userText"] == "[скрыто]"
        bridge.offer_voice_level(float("nan"))
        wait_for(lambda: bridge.audioLevel == 0)
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)


def test_external_target_uses_contract_api_before_execute_on_worker(app):
    from ui.bridge import Bridge
    calls = []
    class TargetEngine(FakeEngine):
        def set_window_context(self, hwnd, pid=None, session_id="desktop"):
            calls.append((hwnd, pid, session_id, threading.get_ident()))
        def execute(self, command):
            assert calls, "Context must precede execution"
            return super().execute(command)
    bridge = Bridge(TargetEngine, command_factory=lambda **kw: SimpleNamespace(**kw),
                    target_provider=lambda: {"hwnd": 12345, "pid": 678})
    try:
        wait_for(lambda: bridge.ready)
        bridge.submit("cpu")
        wait_for(lambda: not bridge.busy)
        assert len(calls) == 1
        assert calls[0][:3] == (12345, 678, "desktop")
        assert calls[0][3] != threading.get_ident()
        assert bridge.messages.snapshot()[0]["verified"]
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)


def test_voice_router_probe_uses_engine_worker_and_never_blocks_gui(app):
    from ui.bridge import Bridge
    engines = []
    class RecognizingEngine(FakeEngine):
        def recognizes(self, text, session_id="desktop"):
            self.threads.append(threading.get_ident())
            return text == "cpu"
    def factory(callback):
        engine = RecognizingEngine(callback)
        engines.append(engine)
        return engine
    bridge = Bridge(factory)
    try:
        wait_for(lambda: bridge.ready)
        assert hasattr(bridge, "recognizes_voice"), "Serialized voice router probe is missing"
        results = []
        thread = threading.Thread(target=lambda: results.append(bridge.recognizes_voice("cpu")))
        thread.start()
        wait_for(lambda: not thread.is_alive())
        thread.join()
        assert results == [True]
        assert bridge.recognizes_voice("cpu") is False  # Defensive nonblocking GUI boundary.
        assert len(set(engines[0].threads)) == 1
        assert threading.get_ident() not in engines[0].threads
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)


def test_unverified_result_has_no_success_indicator(app):
    from ui.messages import MessageModel
    model = MessageModel()
    model.append_event(1, {"text": "команда"})
    model.finish(1, {"status": "success", "verified": False, "message": "не проверено"})
    assert model.snapshot()[0]["verified"] is False
    assert model.snapshot()[0]["status"] == "failed"


def test_shutdown_cancels_queued_commands_and_closes_worker(app):
    bridge, engines = make_bridge()
    wait_for(lambda: bridge.ready)
    bridge.submit("one")
    bridge.submit("two")
    bridge.shutdown()
    wait_for(lambda: bridge.isClosed)
    assert len(engines[0].calls) <= 1
    assert not bridge.submit("three")
    assert engines[0].closed


def test_clear_history_preserves_commands_queued_after_clear(app):
    bridge, engines = make_bridge()
    try:
        wait_for(lambda: bridge.ready)
        bridge.submit("one")
        bridge.clearHistory()
        bridge.submit("two")
        wait_for(lambda: len(engines[0].calls) == 2 and not bridge.busy)
        rows = bridge.messages.snapshot()
        assert len(rows) == 1
        assert rows[0]["userText"] == "two"
    finally:
        bridge.shutdown()
        wait_for(lambda: bridge.isClosed)
