from pathlib import Path
import pytest


def test_success_requires_verified_readback():
    assert (Path(__file__).parents[1] / 'core/models.py').exists(), 'Typed result contract is not implemented'
    from core.models import Result
    with pytest.raises(ValueError, match='verified'):
        Result('success', 'done', False)
    assert Result.ok('Проверено').verified
    assert not Result.fail('Ошибка').verified
    assert not Result.unsupported('Недоступно').verified
