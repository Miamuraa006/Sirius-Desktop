from types import SimpleNamespace
from ui.runtime import ApplicationRuntime


def test_bad_hotkey_constructor_cannot_start_microphone_service():
    calls=[]
    class Voice:
        def __init__(self,*args,**kwargs):pass
        def start(self):calls.append('microphone-started')
    def bad_hotkey(*args,**kwargs):raise ValueError('invalid')
    bridge=SimpleNamespace(**{name:(lambda *args:None) for name in ('offer_voice_text','offer_voice_state','offer_voice_level','recognizes_voice','offer_notice','offer_activation')})
    runtime=SimpleNamespace(_voice_factory=Voice,_hotkey_factory=bad_hotkey,config={},bridge=bridge)
    ApplicationRuntime._start_services(runtime)
    assert calls==[]
