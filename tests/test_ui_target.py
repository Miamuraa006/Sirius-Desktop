"""External focus identity never includes our process, UI or recycled HWNDs."""
import importlib.util


def target_type():
    assert importlib.util.find_spec("ui.target") is not None
    from ui.target import ExternalTarget
    return ExternalTarget


class Api:
    def __init__(self):
        self.foreground = 101
        self.windows = {101: 500, 102: 500, 201: 900}
    def foreground_window(self):
        return self.foreground
    def window_pid(self, hwnd):
        return self.windows.get(hwnd)


def test_external_target_retained_when_own_qml_gets_focus_but_not_recycled():
    api = Api()
    target = target_type()(api=api, own_pid=900)
    assert target.snapshot() == {"hwnd": 101, "pid": 500}
    api.foreground = 201
    assert target.snapshot() == {"hwnd": 101, "pid": 500}
    api.windows[101] = 501
    assert target.snapshot() is None
    api.foreground = 102
    assert target.snapshot() == {"hwnd": 102, "pid": 500}
    del api.windows[102]
    assert target.snapshot() is None


def test_target_without_external_window_never_targets_own_process():
    api = Api()
    api.foreground = 201
    target = target_type()(api=api, own_pid=900)
    assert target.snapshot() is None
