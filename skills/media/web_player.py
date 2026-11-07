"""Play in a verified web tab, independently of the browser's shared media session."""
import re
import time

from skills.applications.web_target import same_site, youtube_video
from skills.browser.handler import WindowsBrowserAdapter
from skills.windows.native import NativeUnavailable, WindowsAdapter

PLAY = ('воспроизведение моей волны', 'воспроизвести', 'воспроизведение', 'начать воспроизведение',
        'смотреть', 'play', 'play video')
PAUSE = ('приостановить', 'пауза', 'приостановить воспроизведение', 'pause')


def play_web_target(target):
    windows = WindowsAdapter()
    window = windows.window(target['hwnd'])
    if window is None or (window.pid, window.created, window.executable) != (
            target['pid'], target['created'], target['executable']):
        raise NativeUnavailable('Окно браузера изменилось. Откройте плеер ещё раз.')
    browser = WindowsBrowserAdapter(windows=windows)
    with browser.automation_factory() as api:
        def document():
            snap = browser.snapshot(window, api)
            if snap.selected != target['tab_id'] or not same_site(snap.document_url, target['site']):
                raise NativeUnavailable('Выбранная вкладка изменилась. Откройте нужный плеер ещё раз.')
            if target['source'] == 'youtube':
                video = youtube_video(snap.document_url)
                if not video:
                    raise NativeUnavailable('YouTube открыт. Выберите видео, затем скажите «включи видео на ютубе».')
                if target.get('video') and video != target['video']:
                    raise NativeUnavailable('Видео сменилось после вопроса. Повторите команду для нового видео.')
            for el in api.chrome_elements(window):
                if el.CurrentControlType == 50030 and api.identity(el) == snap.document_id:
                    return el
            raise NativeUnavailable('Браузер не показывает выбранную страницу через UI Automation.')

        def controls():
            page = document()
            elements = page.FindAll(4, api.api.CreatePropertyCondition(30003, 50000))
            buttons = {}
            for i in range(elements.Length):
                el = elements.GetElement(i)
                if el.CurrentIsEnabled and not el.CurrentIsOffscreen:
                    label = (el.CurrentName or '').strip().casefold()
                    label = re.sub(r'\s*\([kк]\)$', '', label)
                    buttons.setdefault(label, []).append(el)
            return buttons

        sent = False
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            seen = controls()
            if any(len(seen.get(label, ())) == 1 for label in PAUSE):
                return {'state': 'playing', 'already': not sent}
            if not sent:
                for label in PLAY:
                    matches = seen.get(label, ())
                    if len(matches) == 1:
                        invoke = api.pattern(matches[0], 10000, 'IUIAutomationInvokePattern')
                        if invoke:
                            document()
                            invoke.Invoke()
                            sent = True
                            break
            time.sleep(.12)
    raise NativeUnavailable('Вкладка найдена, но плеер не подтвердил воспроизведение. Выберите трек или видео.')

def youtube_back(context):
    """Use the history of the identified YouTube tab, independent of GSMTC."""
    from skills.applications.web_target import WebTargets
    from skills.applications.registry import BROWSER_PROCESSES
    windows = WindowsAdapter()
    active = windows.foreground()
    candidates = [active] if active and active.process_name in BROWSER_PROCESSES else []
    if not candidates and context is not None and context.last_window:
        last = windows.window(context.last_window)
        if last and last.process_name in BROWSER_PROCESSES:
            candidates.append(last)
    targets = WebTargets(windows)
    for window in candidates:
        tab = targets.identify(window, 'https://www.youtube.com/')
        if tab:
            def guard(state):
                return state.selected == tab.tab_id and same_site(state.document_url, tab.url)
            return targets.browser.perform('back', context, target=tab, tab_guard=guard)
    return None
