import pytest

from core.engine import Engine
from core.models import Command


@pytest.fixture
def power(tmp_path):
    calls = []
    engine = Engine({}, tmp_path)
    engine.registry['power'].adapter = calls.append
    yield engine, calls
    engine.close()


@pytest.mark.parametrize('command,action', [
    ('отключи ноутбук', 'shutdown'), ('выключи ноут', 'shutdown'), ('выключить ноутбук', 'shutdown'),
    ('перезагрузить ноутбук', 'restart'), ('перезагрузи устройство', 'restart')])
@pytest.mark.parametrize('reply', ['да', 'да-да', 'да да'])
def test_power_only_after_one_bound_answer(power, command, action, reply):
    engine, calls = power
    question = engine.execute(Command(command, 'voice'))
    assert question.status == 'needs_confirmation'
    assert question.details['presentation'] == 'question'
    assert question.details['spoken_question'] in {'Выключить ноутбук сейчас?', 'Перезагрузить ноутбук сейчас?'}
    assert not engine.execute(Command(reply, 'voice', 'other')).verified and not calls
    assert engine.execute(Command(reply, 'voice')).verified
    assert not engine.execute(Command(reply)).verified and calls == [action]


@pytest.mark.parametrize('next_command', ['нет', 'help', 'не да', 'громкость неизвестно'])
def test_interruption_discards_power_request(power, next_command):
    engine, calls = power
    engine.execute(Command('перезагрузи ноут'))
    engine.execute(Command(next_command))
    assert not engine.execute(Command('да')).verified and not calls


def test_power_does_not_accept_go_or_late_confirmation(power):
    engine, calls = power
    engine.policy.clock = lambda: 0
    engine.execute(Command('выключи ноут'))
    assert engine.execute(Command('го')).status == 'needs_confirmation' and not calls
    engine.policy.clock = lambda: 61
    assert not engine.execute(Command('да')).verified and not calls
