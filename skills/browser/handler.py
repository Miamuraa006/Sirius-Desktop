"""Identified-browser input with UI Automation postconditions, never blind success."""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, quote, quote_plus, parse_qs

from core.models import Result
from skills.applications.registry import BROWSER_PROCESSES
from skills.windows.native import WindowsAdapter, NativeUnavailable, context_target, wait_for, remember_window
from skills.windows.interaction import KeyboardInput
from skills.windows.automation import UIAutomation


def web_url(value):
    """Only explicit HTTP(S) navigation; no shell, local files, credentials or scripts."""
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ValueError('Invalid URL')
    if any(ord(c) <= 32 or ord(c) == 127 or c in '\\<>"' for c in value) or re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)', value, re.I):
        raise ValueError('Unsafe URL characters')
    if '://' not in value:
        # Do not transform a scheme token such as javascript: into an HTTPS host.
        if (':' in value.split('/')[0] or '.' not in value.split('/')[0]
                or value.split('/')[0].casefold().endswith(('.exe', '.cmd', '.bat', '.ps1'))):
            raise ValueError('Expected a web domain or explicit HTTP URL')
        value = 'https://' + value
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Only credential-free HTTP(S) URLs are supported')
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        ascii_host = host.encode('idna').decode('ascii')
        if len(ascii_host) > 253 or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in ascii_host.rstrip('.').split('.')):
            raise ValueError('Invalid hostname') from None
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid port')
    return value


def url_key(value):
    parsed = urlsplit(web_url(value))
    path = quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    fragment = quote(parsed.fragment, safe="/%?:@!$&'()*+,;=-._~")
    upper_escape = lambda x: re.sub(r'%[0-9a-f]{2}', lambda m: m[0].upper(), x, flags=re.I)
    return (parsed.scheme.casefold(), parsed.hostname.encode('idna').decode().casefold(),
            parsed.port or (443 if parsed.scheme.casefold() == 'https' else 80),
            upper_escape(path), upper_escape(query), upper_escape(fragment))


def matches_url(actual, expected, search=False):
    try:
        if url_key(actual) == url_key(expected):
            return True
        if search:
            one, two = urlsplit(web_url(actual)), urlsplit(web_url(expected))
            if url_key(actual)[:4] != url_key(expected)[:4]:
                return False
            got = parse_qs(one.query, keep_blank_values=True)
            required = parse_qs(two.query, keep_blank_values=True)
            return bool(required) and all(got.get(k) == v for k, v in required.items())
    except (ValueError, UnicodeError):
        pass
    return False


@dataclass(frozen=True, repr=False)
class BrowserSnapshot:
    address: str | None = None
    document_url: str | None = None
    tabs: tuple = ()
    selected: tuple | None = None
    document_id: tuple | None = None
    loading: bool = False
    address_focused: bool = False


class WindowsBrowserAdapter:
    SHORTCUTS = {'new_tab': (0x11, 0x54), 'close_tab': (0x11, 0x57), 'refresh': (0x74,),
                 'back': (0x12, 0x25), 'forward': (0x12, 0x27)}
    SHORTCUTS.update(next_tab=(0x11, 0x09), previous_tab=(0x11, 0x10, 0x09), reopen_tab=(0x11, 0x10, 0x54))
    ADDRESS_IDS = {'addresseditbox', 'urlbar-input', 'omnibox', 'urlbar'}
    ADDRESS_NAMES = {'address and search bar', 'search or enter address', 'address bar',
                     'адресная строка и строка поиска', 'адресная строка', 'умная строка',
                     'поиск или ввод адреса', 'search with google or enter address',
                     'поиск в google или ввод адреса'}

    def __init__(self, windows=None, keyboard=None, automation_factory=None, timeout=2.5):
        self.windows = windows if windows is not None else WindowsAdapter()
        self.keyboard = keyboard if keyboard is not None else KeyboardInput(self.windows)
        self.automation_factory = automation_factory or UIAutomation
        self.timeout = timeout

    def target(self, context):
        """Public integration seam: pass an isolated HWND/PID via Context."""
        window = context_target(self.windows, context)
        if window is None or window.process_name.casefold() not in BROWSER_PROCESSES:
            raise NativeUnavailable('Выберите поддерживаемый браузер; команда не отправлена.')
        return window

    def is_address(self, element):
        return element.CurrentControlType == 50004 and (
            (element.CurrentAutomationId or '').casefold() in self.ADDRESS_IDS
            or (element.CurrentName or '').casefold() in self.ADDRESS_NAMES)

    @staticmethod
    def _value(api, element):
        value = api.pattern(element, 10002, 'IUIAutomationValuePattern')
        if value is not None:
            return value.CurrentValue
        legacy = api.pattern(element, 10018, 'IUIAutomationLegacyIAccessiblePattern')
        return legacy.CurrentValue if legacy is not None else None

    def snapshot(self, window, api):
        self.windows.require(window)
        addresses, documents, tabs, selected = [], [], [], []
        loading, focused = False, False
        for element in api.chrome_elements(window):
            role = element.CurrentControlType
            if self.is_address(element) and not element.CurrentIsOffscreen:
                addresses.append(self._value(api, element))
                focused = focused or bool(element.CurrentHasKeyboardFocus)
            if role == 50019:  # TabItem in browser chrome, not a webpage.
                identity = api.identity(element)
                tabs.append(identity)
                selection = api.pattern(element, 10010, 'IUIAutomationSelectionItemPattern')
                if selection is not None and selection.CurrentIsSelected:
                    selected.append(identity)
            if role == 50030 and not element.CurrentIsOffscreen:
                value = self._value(api, element)
                # Chromium exposes toolbar SVG icons as Document controls too.
                # They have no document URL and cannot prove navigation.
                if isinstance(value, str) and value:
                    documents.append((api.identity(element), value))
            if role == 50000 and not element.CurrentIsOffscreen and element.CurrentIsEnabled:
                label = (element.CurrentName or '').casefold()
                loading = loading or label in {'stop', 'stop loading', 'stop loading this page',
                                               'остановить', 'остановить загрузку', 'остановить загрузку страницы'}
        if len(addresses) > 1 or len(selected) > 1:
            raise NativeUnavailable('Состояние браузера неоднозначно.')
        # During a tab transition old/new page roots may overlap. Chrome tab
        # identities remain independent evidence; ambiguous documents prove no
        # navigation, but must not discard a fully observed tab removal.
        if len(documents) > 1:
            documents = []
        return BrowserSnapshot(address=addresses[0] if addresses else None,
                               document_url=documents[0][1] if documents else None,
                               tabs=tuple(tabs), selected=selected[0] if selected else None,
                               document_id=documents[0][0] if documents else None,
                               loading=loading, address_focused=focused)

    def perform(self, action, context, url=None, *, target=None, tab_guard=None):
        if action not in self.SHORTCUTS and action not in {'open', 'search'}:
            raise ValueError('Invalid browser action')
        if action in {'open', 'search'}:
            url = web_url(url)
        window = self.target(context) if target is None else target
        self.windows.require(window)
        active = self.windows.foreground()
        if active is None or active.hwnd != window.hwnd:
            self.windows.activate(window)
        self.keyboard.require_focus(window)
        with self.automation_factory() as api:
            before = self.snapshot(window, api)
            if tab_guard is not None and not tab_guard(before):
                return False
            if action in {'new_tab', 'close_tab', 'next_tab', 'previous_tab', 'reopen_tab'} and (not before.tabs or before.selected is None):
                raise NativeUnavailable('Браузер не предоставляет проверяемый список вкладок; команда не отправлена.')
            if action in {'refresh', 'back', 'forward'} and before.document_id is None:
                raise NativeUnavailable('Браузер не предоставляет проверяемый документ; команда не отправлена.')
            if action in {'open', 'search'}:
                self.keyboard.chord(window, (0x11, 0x4C))
                def address_ready():
                    element = api.focused(window)
                    return self.is_address(element)
                # After Ctrl+L, never type into an unverified page/editor.
                try:
                    if not wait_for(address_ready, timeout=0.7):
                        return False
                    address_id = api.identity(api.focused(window))
                    guard = lambda: api.same_focus(window, address_id) and address_ready()
                    self.keyboard.text(window, url, guard=guard)
                    self.keyboard.chord(window, (0x0D,), guard=guard)
                except Exception:
                    return False
            else:
                if tab_guard is None:
                    self.keyboard.chord(window, self.SHORTCUTS[action])
                else:
                    self.keyboard.chord(window, self.SHORTCUTS[action],
                                        guard=lambda: tab_guard(self.snapshot(window, api)))
            loading_seen = False
            def observed():
                nonlocal loading_seen
                if action == 'close_tab' and len(before.tabs) == 1 and self.windows.window(window.hwnd) is None:
                    return True
                self.keyboard.require_focus(window)
                try:
                    after = self.snapshot(window, api)
                except Exception as exc:
                    # A navigation replaces the UIA document while we traverse it.
                    # Retry readback only, never repeat the shortcut or typed URL.
                    if getattr(exc, 'hresult', None) in {-2147220991, -2147417848, -2147467259}:
                        return False
                    raise
                loading_seen = loading_seen or after.loading
                if action in {'next_tab', 'previous_tab'}:
                    offset = 1 if action == 'next_tab' else -1
                    wanted = before.tabs[(before.tabs.index(before.selected) + offset) % len(before.tabs)]
                    return wanted != before.selected and after.selected == wanted and before.tabs == after.tabs
                if action in {'new_tab', 'reopen_tab'}:
                    return len(after.tabs) == len(before.tabs) + 1 and set(before.tabs).issubset(after.tabs) and after.selected in set(after.tabs) - set(before.tabs)
                if action == 'close_tab':
                    return len(after.tabs) == len(before.tabs) - 1 and set(after.tabs) == set(before.tabs) - {before.selected}
                if action in {'open', 'search'}:
                    # An editable address alone can be unsent text. Require the actual document.
                    return (not after.address_focused and matches_url(after.document_url, url, search=action == 'search'))
                if action in {'back', 'forward'}:
                    return bool(after.document_url and before.document_url and after.document_url != before.document_url and not after.loading)
                return (not after.loading and after.document_id is not None
                        and (after.document_id != before.document_id or loading_seen)
                        and bool(before.document_url) and after.document_url == before.document_url)
            try:
                verified = wait_for(observed, timeout=self.timeout)
            except Exception:
                return False
            if verified and context is not None and self.windows.validate(window):
                remember_window(context, window)
            return verified


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsBrowserAdapter()
        self.config = config or {}

    def execute(self, intent, context):
        action = intent.action
        if intent.skill != 'browser' or action not in {'open', 'search', *WindowsBrowserAdapter.SHORTCUTS}:
            return Result.fail('Неизвестная команда браузера.')
        try:
            url = None
            if action == 'open':
                url = web_url(intent.parameters.get('url'))
            if action == 'search':
                query = intent.parameters.get('query')
                if not isinstance(query, str) or not query.strip() or len(query) > 4096 or any(ord(c) < 32 for c in query):
                    return Result.fail('Нужен непустой поисковый запрос допустимой длины.')
                template = self.config.get('browser', {}).get('search_url', 'https://www.google.com/search?q={query}')
                if not isinstance(template, str) or template.count('{query}') != 1 or '{' in template.replace('{query}', '') or '}' in template.replace('{query}', ''):
                    raise ValueError('Invalid search provider')
                url = web_url(template.replace('{query}', quote_plus(query)))
            if self.adapter.perform(action, context, url=url) is not True:
                return Result.unsupported('Команда отправлена браузеру, но изменение вкладки или документа не подтверждено UI Automation.')
            return Result.ok({'open': 'Адрес открытого документа подтверждён браузером.',
                              'search': 'Поисковый адрес открыт и подтверждён браузером.',
                              'next_tab': 'Выбрана следующая вкладка.', 'previous_tab': 'Выбрана предыдущая вкладка.',
                              'reopen_tab': 'Закрытая вкладка восстановлена.', 'new_tab': 'Новая вкладка открыта.', 'close_tab': 'Вкладка закрыта.',
                              'refresh': 'Обновление документа подтверждено.',
                              'back': 'Переход назад подтверждён.', 'forward': 'Переход вперёд подтверждён.'}[action])
        except NativeUnavailable:
            return Result.unsupported('Поддерживаемый активный браузер или проверяемый интерфейс UI Automation не найден; команда не отправлена.')
        except (ValueError, UnicodeError):
            return Result.fail('Неверный веб-адрес, поисковая настройка или изменившееся целевое окно.')
        except Exception:
            return Result.fail('Операция браузера не подтверждена Windows.')
