import importlib.util

def test_clean_environment_does_not_resolve_installed_python():
    assert importlib.util.find_spec('scripts.frozen_acceptance') is not None
    from scripts.frozen_acceptance import clean_environment
    env=clean_environment({'SYSTEMROOT':'C:/Windows','PATH':'C:/Python','PYTHONPATH':'C:/source','PYTHONHOME':'C:/Python','VIRTUAL_ENV':'C:/venv','QT_SCALE_FACTOR':'9'})
    assert env['PATH']=='C:/Windows;C:/Windows/System32'
    assert not any(k in env for k in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_SCALE_FACTOR'))
