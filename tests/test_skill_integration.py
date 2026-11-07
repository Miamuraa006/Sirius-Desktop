"""Real router/policy/registry/handlers/history; only OS boundaries are injected."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from core.engine import Engine
from core.models import Command
from core.skill_registry import SkillRegistry
from skills.files.handler import WindowsFileAdapter
from skills.system_monitor.handler import WindowsMonitorAdapter
from test_skill_volume import Audio
from test_skill_applications import Apps
from test_skill_windows import Windows
from test_skill_browser import Browser
from test_skill_clipboard import Clipboard
from test_skill_screenshot import Capture
from test_skill_media import Session, handler as media_handler

ROOT = Path(__file__).parents[1]


@pytest.fixture
def engine(tmp_path):
    directory = tmp_path / 'Files'
    directory.mkdir()
    (directory / 'Source.txt').write_text('fixture', encoding='utf-8')
    config = {'_resource_root': str(ROOT), 'files': {'root': str(directory), 'allowed_roots': []},
              'screenshot': {'directory': str(tmp_path / 'Screenshots')}}
    registry = SkillRegistry(config)
    registry['volume'].adapter = Audio()
    registry['brightness'].adapter = Audio()
    registry['applications'].adapter = Apps()
    registry['applications'].adapter.windows = SimpleNamespace(windows=lambda: [])
    registry['windows'].adapter = Windows()
    registry['browser'].adapter = Browser()
    registry['power'].adapter = [].append
    registry['clipboard'].adapter = Clipboard()
    registry['screenshot'].adapter = Capture()
    registry['media'] = media_handler(Session())
    class Files(WindowsFileAdapter):
        @staticmethod
        def open(path):
            return path.is_file()
        @staticmethod
        def trash(path):
            path.rename(path.parent / 'mock-recycled.txt')
    registry['files'].adapter = Files()
    registry['system_monitor'].adapter = WindowsMonitorAdapter(SimpleNamespace(
        cpu_percent=lambda **kw: 20.,
        virtual_memory=lambda: SimpleNamespace(percent=25., used=100, available=300, total=400),
        disk_usage=lambda p: SimpleNamespace(percent=40., used=200, free=300, total=500),
        sensors_battery=lambda: SimpleNamespace(percent=80., power_plugged=True, secsleft=-1),
        sensors_temperatures=lambda: {'fixture': [SimpleNamespace(current=42.)]}))
    events = []
    service = Engine(config, tmp_path / 'Data', events.append, registry)
    try:
        yield service, events, directory
    finally:
        service.close()


CASES = [
    ('что открыто', 'applications', 'list'),
    ('выключи ноутбук', 'power', 'shutdown'), ('перезагрузи устройство', 'power', 'restart'),
    ('следующая вкладка', 'browser', 'next_tab'), ('предыдущая вкладка', 'browser', 'previous_tab'),
    ('верни закрытую вкладку', 'browser', 'reopen_tab'),
    ('громкость на семьдесят процентов', 'volume', 'set'),
    ('ещё тише', 'volume', 'adjust'), ('выключи звук', 'volume', 'mute'),
    ('включи звук', 'volume', 'unmute'), ('яркость на 70%', 'brightness', 'set'),
    ('ещё ярче', 'brightness', 'adjust'), ('открой калькулятор', 'applications', 'open_app'),
    ('закрой блокнот', 'applications', 'close_app'), ('запущен ли блокнот', 'applications', 'status'),
    ('переключись на блокнот', 'applications', 'focus_app'),
    ('перезапусти блокнот', 'applications', 'restart'),
    ('сверни окно', 'windows', 'minimize'), ('разверни окно', 'windows', 'maximize'),
    ('восстанови окно', 'windows', 'restore'), ('переключи окно', 'windows', 'switch'),
    ('покажи рабочий стол', 'windows', 'desktop'), ('активируй окно Calculator', 'windows', 'activate'),
    ('открой сайт https://example.org/Case', 'browser', 'open'),
    ('найди в интернете C++', 'browser', 'search'), ('новая вкладка', 'browser', 'new_tab'),
    ('закрой вкладку', 'browser', 'close_tab'), ('обнови страницу', 'browser', 'refresh'),
    ('перейди назад', 'browser', 'back'), ('перейди вперёд', 'browser', 'forward'),
    ('пауза', 'media', 'pause'), ('продолжи', 'media', 'play'),
    ('play pause', 'media', 'play_pause'), ('следующий трек', 'media', 'next'),
    ('предыдущий трек', 'media', 'previous'), ('стоп', 'media', 'stop'),
    ('создай папку "MiXeD Ёж"', 'files', 'mkdir'),
    ('создай пустой txt "MiXeD.TXT"', 'files', 'touch'),
    ('открой файл "Source.txt"', 'files', 'open'),
    ('переименуй "Source.txt" в "New.txt"', 'files', 'rename'),
    ('перемести "Source.txt" в "Moved.txt"', 'files', 'move'),
    ('удали "Source.txt" в корзину', 'files', 'trash'),
    ('проверь буфер обмена', 'clipboard', 'status'),
    ('скопируй выделенное', 'clipboard', 'copy'), ('вставь', 'clipboard', 'paste'),
    ('выдели всё', 'clipboard', 'select_all'), ('установи буфер обмена MiXeD Ёж', 'clipboard', 'set'),
    ('снимок всего экрана', 'screenshot', 'full'), ('снимок активного окна', 'screenshot', 'window'),
    ('загрузка CPU', 'system_monitor', 'cpu'), ('занятость RAM', 'system_monitor', 'ram'),
    ('свободное место на диске', 'system_monitor', 'disk'), ('заряд батареи', 'system_monitor', 'battery'),
    ('температура', 'system_monitor', 'temperature'),
]


@pytest.mark.parametrize('phrase,skill,action', CASES)
def test_each_required_action_through_actual_engine(engine, phrase, skill, action):
    service, events, directory = engine
    intent = service.router.parse(phrase)
    assert (intent.skill, intent.action) == (skill, action)
    if action == 'focus_app':
        assert service.execute(Command('открой блокнот')).verified
    result = service.execute(Command(phrase))
    if skill == 'power' or (skill, action) in {('applications', 'close_app'), ('applications', 'restart'), ('files', 'trash')}:
        assert result.status == 'needs_confirmation'
        result = service.execute(Command('подтверждаю'))
    assert result.verified and result.status == 'success', result
    assert events[-1]['skill'] == skill and events[-1]['result']['verified']
    assert service.history.recent()[-1]['verified']
    assert 'confirmed' not in service.contexts['desktop'].data
    assert 'file_grant' not in service.contexts['desktop'].data


def test_close_pronoun_resolves_last_app_and_confirms_once(engine):
    service, events, directory = engine
    assert service.execute(Command('открой блокнот')).verified
    app = service.registry['applications'].adapter
    result = service.execute(Command('закрой его'))
    assert result.status == 'needs_confirmation' and len(app.items) == 1
    assert service.execute(Command('подтверждаю')).verified and not app.items
    assert not service.execute(Command('подтверждаю')).verified


def test_payload_never_reaches_events_history_or_results(engine):
    service, events, directory = engine
    secret = 'Private Ёж  70 процентов\nKeepCASE  '
    result = service.execute(Command('установи буфер обмена ' + secret))
    assert result.verified
    assert service.registry['clipboard'].adapter.text == secret
    saved = json.dumps({'events': events, 'history': service.history.recent(), 'result': result.to_dict()}, ensure_ascii=False)
    assert secret not in saved and 'Private' not in saved and 'KeepCASE' not in saved


def test_integration_cases_cover_every_declared_action():
    from test_vocabulary import ACTIONS
    collected = {skill: {action for _, s, action in CASES if s == skill} for skill in ACTIONS}
    assert collected == ACTIONS
