from importlib import import_module, util


def state_class():
    assert util.find_spec("voice") is not None, "voice package missing"
    assert util.find_spec("voice.activation_state") is not None, "activation FSM missing"
    return import_module("voice.activation_state").ActivationState


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_activation_expires_at_exact_monotonic_boundary():
    clock = Clock()
    state = state_class()(clock=clock)
    assert state.state == "idle"
    assert state.activate()
    assert state.state == "listening"
    assert state.deadline == 160.0
    clock.now = 159.999
    assert state.tick() == "listening"
    clock.now = 160.0
    assert state.tick() == "idle"
    assert state.deadline is None


def test_only_accepted_command_completion_extends_window():
    clock = Clock()
    state = state_class()(clock=clock)
    assert hasattr(state, "command_accepted"), "accepted-command gate missing"
    state.activate()
    clock.now = 120.0
    state.command_completed(True)  # Unsolicited completion is not a command.
    assert state.deadline == 160.0
    assert state.command_accepted()
    assert state.state == "processing"
    assert state.deadline == 160.0
    clock.now = 180.0
    assert state.tick() == "processing"  # Completion, not start, opens new 60s.
    state.command_completed(True)
    assert state.state == "listening"
    assert state.deadline == 240.0
    assert state.command_accepted()
    clock.now = 200.0
    state.command_completed(False)
    assert state.deadline == 240.0


def test_disabled_state_cannot_be_reactivated_by_late_completion():
    clock = Clock()
    state = state_class()(clock=clock)
    assert hasattr(state, "set_enabled"), "disable gate missing"
    state.activate()
    state.command_accepted()
    state.set_enabled(False)
    assert not state.activate()
    state.command_completed(True)
    assert state.state == "idle"
    assert state.deadline is None
    state.set_enabled(True)
    assert not state.command_accepted()
    assert state.activate()
    assert state.command_accepted()
    assert not state.activate()  # No parallel voice command while executing.


def test_timeout_and_unknown_do_not_admit_command():
    clock = Clock()
    state = state_class()(clock=clock)
    assert hasattr(state, "command_accepted"), "accepted-command gate missing"
    assert not state.command_accepted()
    state.activate()
    clock.now = 160.0
    assert not state.command_accepted()
    assert state.state == "idle"
