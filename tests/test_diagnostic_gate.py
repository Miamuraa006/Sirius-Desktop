import json
from core.models import Result
import main


def test_successful_text_cannot_hide_failed_resource_diagnostics(tmp_path,monkeypatch):
    import core.config
    import core.engine
    import sounddevice
    config={'_data_dir':str(tmp_path),'_resource_root':str(tmp_path)}
    monkeypatch.setattr(core.config,'load_config',lambda *_:config)
    monkeypatch.setattr(main,'_configure_logging',lambda *_:None)
    monkeypatch.setattr(sounddevice,'query_devices',lambda:[])
    class Engine:
        registry={}
        def __init__(self,*args):pass
        def execute(self,command):return Result.ok('readback')
        def close(self):pass
    monkeypatch.setattr(core.engine,'Engine',Engine)
    output=tmp_path/'receipt.json'
    assert main.main(['--diagnose','--text','cpu','--report',str(output)])==1
    assert json.loads(output.read_text(encoding='utf8'))['passed'] is False
