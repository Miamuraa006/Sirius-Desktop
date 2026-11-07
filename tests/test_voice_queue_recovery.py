from types import SimpleNamespace
import threading
from PySide6.QtWidgets import QApplication
from ui.bridge import Bridge
from voice.activation_state import ActivationState
from test_ui_bridge import FakeEngine,wait_for


def test_rejected_voice_enqueue_acknowledges_without_extending_deadline():
    app=QApplication.instance() or QApplication([])
    entered=threading.Event();release=threading.Event()
    class BlockedEngine(FakeEngine):
        def execute(self,command):
            entered.set();release.wait(3)
            return super().execute(command)
    bridge=Bridge(BlockedEngine,command_factory=lambda **kw:SimpleNamespace(**kw))
    clock=[0.0];state=ActivationState(clock=lambda:clock[0])
    completions=[]
    def completed(result):
        if result.get('source')=='voice':
            completions.append(result)
            state.command_completed(result.get('status') not in {'cancelled','not_understood'})
    bridge.commandFinished.connect(completed)
    try:
        wait_for(lambda:bridge.ready)
        for _ in range(16):assert bridge.submit('cpu')
        assert entered.wait(1)
        assert state.activate() and state.command_accepted()
        original=state.deadline
        clock[0]=12.0
        bridge.offer_voice_text('cpu')
        wait_for(lambda:bool(completions),timeout=500)
        assert completions==[{'source':'voice','status':'cancelled','verified':False,'message':''}]
        assert state.state=='listening' and state.deadline==original
        clock[0]=120
        assert state.tick()=='idle'
        assert state.activate()
    finally:
        release.set();bridge.shutdown();wait_for(lambda:bridge.isClosed)
