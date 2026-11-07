"""Identify a web application by the selected tab and its observed HTTPS origin."""
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from skills.browser.handler import WindowsBrowserAdapter
from skills.windows.native import WindowRef, NativeUnavailable


@dataclass(frozen=True)
class WebTab(WindowRef):
    url: str = ''
    tab_id: tuple = ()
    document_url: str = ''


def same_site(document_url, site):
    if not document_url:
        return False
    try:
        actual, expected = urlsplit(document_url), urlsplit(site)
        return (actual.scheme == expected.scheme == 'https' and actual.hostname == expected.hostname
                and (actual.port or 443) == (expected.port or 443))
    except ValueError:
        return False


def youtube_video(url):
    page = urlsplit(url)
    if page.path == '/watch':
        return parse_qs(page.query).get('v', [''])[0]
    parts = page.path.strip('/').split('/')
    return parts[1] if len(parts) == 2 and parts[0] in ('shorts', 'live', 'embed') else ''


class WebTargets:
    def __init__(self, windows):
        self.browser = WindowsBrowserAdapter(windows=windows)

    def identify(self, window, site):
        try:
            with self.browser.automation_factory() as api:
                state = self.browser.snapshot(window, api)
        except (ValueError, OSError, NativeUnavailable):
            return None
        if state.selected and same_site(state.document_url, site):
            return WebTab(window.hwnd, window.pid, window.process_name, window.title, window.created,
                          window.executable, site, state.selected, state.document_url)
        return None

    def locate(self, windows, sites, player):
        from skills.applications.registry import BROWSER_PROCESSES
        from skills.windows.native import wait_for
        candidates = []
        landing = None
        names = ('youtube', 'ютуб') if player == 'youtube' else ('яндекс музыка', 'яндекс.музыка', 'yandex music')
        for window in windows:
            if window.process_name not in BROWSER_PROCESSES:
                continue
            for site in sites:
                tab = self.identify(window, site)
                if tab:
                    if player != 'youtube' or youtube_video(tab.document_url):
                        return tab
                    landing = landing or tab
            # The title only nominates a candidate. Verify its real document origin after selection.
            try:
                with self.browser.automation_factory() as api:
                    for el in api.chrome_elements(window):
                        if el.CurrentControlType != 50019:
                            continue
                        label = (el.CurrentName or '').casefold()
                        if label not in names and any(n in label for n in names):
                            selection = api.pattern(el, 10010, 'IUIAutomationSelectionItemPattern')
                            if selection and not selection.CurrentIsSelected:
                                candidates.append((window, api.identity(el)))
            except (NativeUnavailable, OSError, ValueError):
                continue
        if len(candidates) != 1:
            return landing
        window, wanted = candidates[0]
        with self.browser.automation_factory() as api:
            before = self.browser.snapshot(window, api).selected
            def select(identity):
                for el in api.chrome_elements(window):
                    if el.CurrentControlType == 50019 and api.identity(el) == identity:
                        pattern = api.pattern(el, 10010, 'IUIAutomationSelectionItemPattern')
                        if pattern:
                            self.browser.windows.require(window)
                            pattern.Select()
                            return True
                return False
            if not select(wanted):
                return landing
            def verified():
                state = self.browser.snapshot(window, api)
                return state.selected == wanted and any(same_site(state.document_url, s) for s in sites)
            if wait_for(verified, timeout=1.2):
                for site in sites:
                    tab = self.identify(window, site)
                    if tab and tab.tab_id == wanted:
                        return tab
            if before and self.browser.snapshot(window, api).selected == wanted:
                select(before)
        return landing

    def validate(self, tab):
        current = self.identify(tab, tab.url)
        return current is not None and current.tab_id == tab.tab_id

    def close(self, tab):
        def still_selected(state):
            return state.selected == tab.tab_id and same_site(state.document_url, tab.url)
        if not self.browser.perform('close_tab', None, target=tab, tab_guard=still_selected):
            raise NativeUnavailable('Браузер не подтвердил закрытие целевой вкладки.')
