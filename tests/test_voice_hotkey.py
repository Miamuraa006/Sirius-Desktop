import queue
import threading
import time
from importlib import import_module, util


def hotkey_class():
    assert util.find_spec("voice.hotkey") is not None, "RegisterHotKey adapter missing"
    return import_module("voice.hotkey").GlobalHotkey


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate(), "condition not reached"


class API:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.calls = []
        self.messages = queue.Queue()
    def register(self, modifiers, key):
        self.calls.append(("register", threading.get_ident(), modifiers, key))
        return self.succeeds
    def poll(self):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return False
    def unregister(self):
        self.calls.append(("unregister", threading.get_ident()))
        return True


def test_alt_m_registration_and_unregistration_share_worker_thread():
    api = API()
    fired = threading.Event()
    errors = []
    hotkey = hotkey_class()(fired.set, api_factory=lambda: api, on_error=errors.append)
    try:
        hotkey.start()
        assert hotkey.wait_ready(1)
        assert hotkey.registered
        assert api.calls[0][2:] == (1 | 0x4000, 77)
        api.messages.put(True)  # Native-message fake, never send real global keys.
        assert fired.wait(1)
        hotkey.start()
        assert len([c for c in api.calls if c[0] == "register"]) == 1
    finally:
        hotkey.stop()
    assert not hotkey.registered
    assert not hotkey.running
    assert api.calls[-1][0] == "unregister"
    assert api.calls[0][1] == api.calls[-1][1] != threading.get_ident()
    assert errors == []


def test_occupied_hotkey_reports_error_and_never_unregisters_other_owner():
    api = API(False)
    errors = []
    hotkey = hotkey_class()(lambda: None, api_factory=lambda: api, on_error=errors.append)
    hotkey.start()
    assert hotkey.wait_ready(1)
    wait_for(lambda: not hotkey.running)
    hotkey.stop()
    assert not hotkey.registered
    assert errors and "занята" in errors[0]
    assert [c[0] for c in api.calls] == ["register"]


def test_hotkey_can_be_reconfigured_and_callback_error_keeps_cleanup():
    api = API()
    errors = []
    def broken():
        raise RuntimeError("private text should not appear")
    hotkey = hotkey_class()(broken, modifiers=3, key=78, api_factory=lambda: api,
                            on_error=errors.append)
    try:
        hotkey.start()
        assert hotkey.wait_ready(1)
        assert api.calls[0][2:] == (3 | 0x4000, 78)
        api.messages.put(True)
        wait_for(lambda: bool(errors))
        assert "private" not in errors[0]
        assert hotkey.registered
    finally:
        hotkey.stop()
    assert api.calls[-1][0] == "unregister"


def test_hotkey_worker_failure_releases_registration_and_can_restart():
    api = API()
    original_poll = api.poll
    failures = [True]

    def poll():
        if failures:
            failures.pop()
            raise OSError("private native details")
        return original_poll()

    api.poll = poll
    errors = []
    hotkey = hotkey_class()(lambda: None, api_factory=lambda: api, on_error=errors.append)
    try:
        hotkey.start()
        wait_for(lambda: errors and not hotkey.running)
        assert not hotkey.registered
        assert [call[0] for call in api.calls] == ["register", "unregister"]
        assert "private" not in errors[0]
        hotkey.start()
        assert hotkey.wait_ready(1) and hotkey.registered
    finally:
        hotkey.stop()
    assert [call[0] for call in api.calls] == ["register", "unregister", "register", "unregister"]
    assert not hotkey.running
