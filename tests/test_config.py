from pathlib import Path
import json
import pytest


def loader():
    assert (Path(__file__).parents[1]/'core/config.py').exists(), 'Config store missing'
    from core.config import load_config,save_config
    return load_config,save_config


def test_config_created_separately_preserves_invalid_file(tmp_path):
    load,save=loader()
    c=load(tmp_path)
    assert c['voice']['active_seconds']==60
    assert c['_data_dir']==str(tmp_path)
    p=tmp_path/'config.json'
    assert json.loads(p.read_text(encoding='utf8'))['voice']['enabled'] is True
    p.write_text('{corrupt',encoding='utf8')
    with pytest.raises(ValueError):load(tmp_path)
    assert p.read_text(encoding='utf8')=='{corrupt'

@pytest.mark.parametrize('setting',[{'voice':{'enabled':'yes'}},{'history':{'retention_days':-1}},{'voice':{'active_seconds':3}},{'hotkey':{'key':-1}},{'telemetry':True}])
def test_config_rejects_invalid_types_or_unknown_fields(tmp_path,setting):
    load,save=loader();(tmp_path/'config.json').write_text(json.dumps(setting),encoding='utf8')
    with pytest.raises(ValueError):load(tmp_path)


def test_installed_profile_is_writable_and_separate_from_bundle(tmp_path, monkeypatch):
    from core import config
    monkeypatch.setattr(config.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(config.sys, 'executable', str(tmp_path / 'programs/Sirius/Sirius.exe'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'profile'))
    assert config.default_data_dir() == tmp_path / 'profile/Sirius/UserData'


def test_portable_marker_preserves_existing_desktop_data(tmp_path, monkeypatch):
    from core import config
    app = tmp_path / 'app'
    app.mkdir()
    (app / 'portable.marker').touch()
    monkeypatch.setattr(config.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(config.sys, 'executable', str(app / 'Sirius.exe'))
    assert config.default_data_dir() == tmp_path / 'data'
