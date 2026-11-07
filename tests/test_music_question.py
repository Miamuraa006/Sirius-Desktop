from dataclasses import replace
from types import SimpleNamespace
import pytest
from core.engine import Engine
from core.models import Command
from skills.media.handler import WindowsMediaAdapter
from test_skill_applications import Apps
from test_skill_media import Session


@pytest.fixture
def scenario(tmp_path):
    music, browser = Session(status='PAUSED'), Session()
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    browser.source_app_user_model_id = 'Chrome'
    sessions = [browser, music]
    async def manager():
        return SimpleNamespace(get_sessions=lambda: list(sessions), get_current_session=lambda: browser)
    engine = Engine({}, tmp_path)
    engine.registry['applications'].adapter = Apps()
    engine.registry['media'].adapter = WindowsMediaAdapter(manager_factory=manager, timeout=.15, poll_interval=.005)
    yield engine, sessions, music, browser
    engine.close()


@pytest.mark.parametrize('source', ['voice', 'text'])
@pytest.mark.parametrize('answer,approve', [('да', True), ('Давай!', True), ('го', True), ('Go', True),
    ('ага', True), ('подтверждаю', True), ('нет', False), ('не надо', False), ('отмена', False), ('отмени', False)])
def test_open_and_answer_once_only_in_same_session(scenario, source, answer, approve):
    engine, _, music, browser = scenario
    opened = engine.execute(Command('открой Яндекс Музыку', source))
    assert opened.verified and 'Включить музыку?' in opened.message and opened.details['presentation'] == 'question'
    assert not music.calls and not browser.calls
    assert not engine.recognizes(answer, 'other') and engine.recognizes(answer)
    assert engine.execute(Command(answer, source, 'other')).status == 'not_understood'
    assert engine.execute(Command(answer, source)).verified
    assert music.calls == (['play'] if approve else []) and not browser.calls
    assert not engine.recognizes(answer)
    assert engine.execute(Command(answer, source)).status == 'not_understood'


@pytest.mark.parametrize('interruption', ['help', 'открой Steam', 'expiration'])
def test_question_is_bounded(scenario, interruption):
    engine, _, music, browser = scenario
    engine.execute(Command('открой яндекс музыку'))
    if interruption == 'expiration':
        ctx = engine.contexts['desktop']
        ctx.question = replace(ctx.question, expires=0)
    else:
        assert engine.execute(Command(interruption)).verified
    assert engine.execute(Command('да', 'voice')).status == 'not_understood'
    assert not music.calls and not browser.calls


def test_failed_open_and_other_apps_do_not_ask(scenario, monkeypatch):
    from skills.applications import manager
    engine, _, _, _ = scenario
    assert engine.execute(Command('открой телеграм')).verified and not engine.recognizes('да')
    engine.registry['applications'].adapter.accept_open = False
    monkeypatch.setattr(manager, 'wait_for', lambda check, **kwargs: check())
    assert not engine.execute(Command('открой Яндекс.Музыку')).verified and not engine.recognizes('да')


@pytest.mark.parametrize('available', [True, False])
def test_cold_start_never_plays_chrome_and_requires_readback(scenario, monkeypatch, available):
    from skills.media import start_button
    engine, sessions, music, browser = scenario
    sessions.remove(music)
    def click(target):
        assert target['hwnd'] == 11 and target['created'] == 1.0
        if available:
            music.status = 'PLAYING'
            sessions.append(music)
    monkeypatch.setattr(start_button, 'invoke_play_button', click)
    assert engine.execute(Command('открой яндекс музыку')).verified
    assert engine.execute(Command('да')).verified == available
    assert not browser.calls


def test_ambiguous_yandex_session_does_not_press_any_button(scenario):
    engine, sessions, music, browser = scenario
    another = Session(status='PAUSED')
    another.source_app_user_model_id = music.source_app_user_model_id
    sessions.append(another)
    engine.execute(Command('открой яндекс музыку'))
    assert not engine.execute(Command('да')).verified
    assert not music.calls and not browser.calls and not another.calls

def test_hidden_chat_opens_for_question_and_receives_spoken_no(tmp_path):
    from PySide6.QtWidgets import QApplication
    from ui.app import DesktopUi
    from ui.bridge import Bridge
    from test_ui_bridge import wait_for

    def factory(callback):
        engine = Engine({}, tmp_path, callback)
        engine.registry['applications'].adapter = Apps()
        return engine

    app = QApplication.instance() or QApplication([])
    bridge = Bridge(factory)
    ui = DesktopUi(app, bridge, chat_visible=False, enable_tray=False)
    try:
        wait_for(lambda: bridge.ready)
        assert not ui.chat.isVisible()
        bridge.submit('открой яндекс музыку')
        wait_for(lambda: not bridge.busy and ui.chat.isVisible())
        assert 'Включить музыку?' in bridge.messages.snapshot()[-1]['resultText']
        bridge.offer_voice_text('нет')
        wait_for(lambda: len(bridge.messages.snapshot()) == 2 and not bridge.busy)
        answer = bridge.messages.snapshot()[-1]
        assert answer['userText'] == 'нет' and answer['source'] == 'voice' and answer['verified']
        assert not ui.qml_errors
    finally:
        ui.shutdown()
        wait_for(lambda: bridge.isClosed)
        ui.dispose()
