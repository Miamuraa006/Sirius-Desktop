"""Opt-in Windows release probe; only disposable fixtures are modified.

Run from the repository: python scripts/native_release_probe.py
No hardware/media mutations, no full-desktop capture, no user browser profile.
Clipboard contents are preserved in memory only, never serialized.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture(output):
    import win32con
    import win32gui
    instance = win32gui.GetModuleHandle(None)
    klass = win32gui.WNDCLASS()
    klass.hInstance = instance
    klass.lpszClassName = 'SiriusDisposableNativeFixture'
    klass.hbrBackground = win32con.COLOR_WINDOW + 1
    edit_holder = []
    def wndproc(hwnd, message, wparam, lparam):
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        if message == win32con.WM_SETFOCUS and edit_holder:
            win32gui.SetFocus(edit_holder[0])
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
    klass.lpfnWndProc = wndproc
    atom = win32gui.RegisterClass(klass)
    hwnd = win32gui.CreateWindow(atom, 'Sirius disposable native fixture',
                                win32con.WS_OVERLAPPEDWINDOW, 80, 80, 680, 400, 0, 0, instance, None)
    edit = win32gui.CreateWindowEx(0, 'EDIT', 'Sirius disposable text fixture',
                                  win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP |
                                  win32con.ES_MULTILINE | win32con.ES_AUTOVSCROLL,
                                  20, 20, 620, 290, hwnd, 0, instance, None)
    edit_holder.append(edit)
    win32gui.ShowWindow(hwnd, 1)
    win32gui.UpdateWindow(hwnd)
    win32gui.SetFocus(edit)
    Path(output).write_text(json.dumps({'hwnd': hwnd, 'edit': edit, 'pid': os.getpid()}), encoding='utf-8')
    win32gui.PumpMessages()


class Probe:
    def __init__(self):
        from core.engine import Engine
        from skills.windows.native import WindowsAdapter
        self.root = ROOT / '.qa' / ('native-' + uuid4().hex[:12])
        self.root.mkdir(parents=True)
        self.report = {'started': datetime.now(timezone.utc).isoformat(), 'fixture_root': str(self.root),
                       'scope': 'Real Windows adapters; independent native readback. Unsupported is not passed.',
                       'actions': [], 'cleanup': {}}
        self.config = {'history': {'enabled': False},
                       'files': {'root': str(self.root / 'files'), 'allowed_roots': []},
                       'screenshot': {'directory': str(self.root / 'screenshots')},
                       'applications': {'notepad': {'command': ['notepad.exe', str(self.root / 'notepad.txt')],
                                                    'process_names': ['notepad.exe'], 'aliases': ['блокнот']}}}
        (self.root / 'files').mkdir()
        (self.root / 'notepad.txt').write_text('', encoding='utf-8')
        self.windows = WindowsAdapter()
        self.original_foreground = self.windows.foreground()
        self.original_windows = {w.hwnd for w in self.windows.windows()}
        self.engine = Engine(self.config, self.root / 'state')
        self.owned = []
        self.processes = []
        self.server = None

    def save(self):
        self.report['counts'] = dict(Counter(x['outcome'] for x in self.report['actions']))
        target = ROOT / 'docs' / 'NATIVE_TESTS.json'
        payload = json.dumps(self.report, ensure_ascii=False, indent=2)
        target.write_text(payload, encoding='utf-8')
        (self.root / 'report.json').write_text(payload, encoding='utf-8')

    def record(self, skill, action, result=None, check=None, note='', outcome=None, evidence=None):
        if outcome is None:
            outcome = ('passed' if result.status == 'success' and result.verified and check is True
                       else 'unsupported' if result.status == 'unsupported' else 'failed')
        entry = {'skill': skill, 'action': action, 'outcome': outcome, 'note': note}
        if result is not None:
            entry.update(result=result.to_dict(), independent_readback=check)
        if evidence is not None:
            entry['evidence'] = evidence
        self.report['actions'].append(entry)
        self.save()
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def command(self, text):
        from core.models import Command
        return self.engine.execute(Command(text, session_id='native-release'))

    def files(self):
        root = self.root / 'files'
        for action, text, check in [
            ('mkdir', 'создай папку "sub"', lambda: (root / 'sub').is_dir()),
            ('touch', 'создай пустой txt "alpha.txt"', lambda: (root / 'alpha.txt').is_file() and (root / 'alpha.txt').stat().st_size == 0),
            ('rename', 'переименуй "alpha.txt" в "beta.txt"', lambda: not (root / 'alpha.txt').exists() and (root / 'beta.txt').is_file()),
            ('move', 'перемести "beta.txt" в "sub/beta.txt"', lambda: not (root / 'beta.txt').exists() and (root / 'sub/beta.txt').is_file()),
        ]:
            result = self.command(text)
            self.record('files', action, result, check())
        pending = self.command('удали "sub/beta.txt" в корзину')
        self.record('files', 'trash_confirmation_gate', pending,
                    outcome='passed' if pending.status == 'needs_confirmation' and (root / 'sub/beta.txt').exists() else 'failed')
        cancelled = self.command('отмена')
        self.record('files', 'trash_cancel', cancelled, (root / 'sub/beta.txt').exists())
        self.command('удали "sub/beta.txt" в корзину')
        result = self.command('подтверждаю')
        # Shell recycle-bin namespace is independent of send2trash's return code.
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            items = win32com.client.Dispatch('Shell.Application').NameSpace(10).Items()
            recycled = any(item.Name == 'beta.txt' and
                           str(self.root).casefold() in str(item.ExtendedProperty('System.Recycle.DeletedFrom')).casefold()
                           for item in items)
        finally:
            pythoncom.CoUninitialize()
        self.record('files', 'trash_confirmed', result, not (root / 'sub/beta.txt').exists() and recycled,
                    evidence={'recycle_bin_item_found': recycled})
        self.record('files', 'open', outcome='untested', note='Default document/folder associations may reuse user windows; no association changed.')

    def applications(self):
        from skills.applications.handler import app_registry
        for app, alias in [('calculator', 'калькулятор'), ('notepad', 'блокнот')]:
            adapter = self.engine.registry.get('applications').adapter
            spec = app_registry(self.config)[app]
            if adapter.find_windows(spec):
                self.record('applications', app + '_open_close', outcome='untested', note='Existing user window; not touched.')
                continue
            result = self.command('открой ' + alias)
            found = adapter.find_windows(spec)
            new = [w for w in found if w.hwnd not in self.original_windows]
            self.owned.extend(new)
            self.record('applications', app + '_open', result, bool(new))
            self.record('applications', app + '_status', self.command('запущен ли ' + alias), bool(found))
            if not new or len(new) != len(found):
                continue
            pending = self.command('закрой ' + alias)
            self.record('applications', app + '_close_confirmation', pending,
                        outcome='passed' if pending.status == 'needs_confirmation' and all(self.windows.validate(w) for w in new) else 'failed')
            result = self.command('подтверждаю')
            self.record('applications', app + '_soft_close', result, not any(self.windows.validate(w) for w in new))
        self.record('applications', 'restart', outcome='untested', note='Bounded run focuses launch/status/confirmed soft close.')

    def native_fixture(self):
        from core.context import Context
        from core.models import Intent
        from skills.windows.native import remember_window, wait_for
        output = self.root / 'fixture.json'
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--fixture', str(output)])
        self.processes.append(process)
        if not wait_for(output.exists, timeout=5):
            raise RuntimeError('Disposable fixture did not start')
        data = json.loads(output.read_text(encoding='utf-8'))
        window = self.windows.window(data['hwnd'])
        self.owned.append(window)
        self.fixture_window = window
        self.fixture_edit = data['edit']
        context = Context()
        remember_window(context, window)
        handler = self.engine.registry.get('windows')
        for action, state in [('minimize', 'minimized'), ('restore', 'normal'), ('maximize', 'maximized'), ('restore', 'normal'), ('activate', None)]:
            result = handler.execute(Intent('windows', action, {'target': window.hwnd, 'pid': window.pid}), context)
            check = self.windows.state(window) == state if state else bool(self.windows.foreground() and self.windows.foreground().hwnd == window.hwnd)
            self.record('windows', action, result, check)
        for action in ['switch', 'desktop']:
            self.record('windows', action, outcome='untested', note='Would manipulate unrelated user windows; explicit-HWND state actions exercised instead.')
        # Guard the capture twice against foreground changes; native capture remains HWND scoped.
        from skills.screenshot.handler import Handler, WindowsScreenshotAdapter
        class FixtureScreenshot(WindowsScreenshotAdapter):
            def target(adapter, unused):
                adapter.windows.require(window)
                return window
        result = Handler(adapter=FixtureScreenshot(), config=self.config).execute(Intent('screenshot', 'window'), context)
        from PIL import Image
        check = False
        if result.status == 'success':
            with Image.open(result.details['path']) as image:
                image.load()
                check = image.size == (result.details['width'], result.details['height']) and image.getbbox() is not None
        self.record('screenshot', 'window', result, check, note='Real ImageGrab(window=dedicated HWND); no desktop pixels.')
        self.record('screenshot', 'full', outcome='untested', note='Private desktop deliberately not captured.')
        self.clipboard(context)

    def clipboard(self, context):
        import win32clipboard
        import win32gui
        from core.models import Intent
        from skills.clipboard.handler import Win32Clipboard, WindowsClipboardAdapter, Handler
        clipboard = Win32Clipboard()
        handler = self.engine.registry.get('clipboard')
        result = handler.execute(Intent('clipboard', 'status'), context)
        self.record('clipboard', 'status', result, result.details.get('has_text') == bool(clipboard.read_text()))
        with clipboard.opened() as api:
            formats = []
            current = api.EnumClipboardFormats(0)
            while current:
                formats.append(current)
                current = api.EnumClipboardFormats(current)
        if set(formats) - {1, 7, 13, 16}:
            for action in ['set', 'select_all', 'copy', 'paste']:
                self.record('clipboard', action, outcome='untested', note='Rich clipboard formats cannot be restored losslessly; no mutation.')
            return
        original = clipboard.read_text()
        window = self.fixture_window
        class FixtureClipboard(WindowsClipboardAdapter):
            def target(adapter, unused):
                adapter.windows.require(window)
                return window
        handler = Handler(adapter=FixtureClipboard())
        try:
            result = handler.execute(Intent('clipboard', 'set', {'text': 'Sirius clipboard sentinel'}), context)
            self.record('clipboard', 'set', result, clipboard.read_text() == 'Sirius clipboard sentinel')
            self.windows.activate(window)
            import ctypes
            # Fixture main thread owns focus; EM_SETSEL is confined to owned edit.
            win32gui.SendMessage(self.fixture_edit, 0x00B1, 0, 0)
            ctypes.windll.user32.PostMessageW(window.hwnd, 0x0007, 0, 0)
            result = handler.execute(Intent('clipboard', 'select_all'), context)
            selection = win32gui.SendMessage(self.fixture_edit, 0x00B0, 0, 0)
            selected_all = (selection & 0xFFFF) == 0 and (selection >> 16) == len('Sirius disposable text fixture')
            self.record('clipboard', 'select_all', result, selected_all)
            result = handler.execute(Intent('clipboard', 'copy'), context)
            self.record('clipboard', 'copy', result, clipboard.read_text() == 'Sirius disposable text fixture')
            clipboard.write_text('Sirius replacement text')
            result = handler.execute(Intent('clipboard', 'paste'), context)
            # GetWindowText intentionally cannot read another process's EDIT.
            buffer = win32gui.PyMakeBuffer(4096)
            win32gui.SendMessage(self.fixture_edit, 0x000D, 2048, buffer)
            observed = bytes(buffer).decode('utf-16-le').split('\x00', 1)[0]
            self.record('clipboard', 'paste', result, observed == 'Sirius replacement text')
        finally:
            if original is None:
                with clipboard.opened(writing=True) as api:
                    api.EmptyClipboard()
            else:
                clipboard.write_text(original)
            restored = clipboard.read_text() == original
            self.report['cleanup']['clipboard_text_restored'] = restored
            self.save()
            if not restored:
                raise RuntimeError('Clipboard restoration failed')

    def browser(self):
        from core.context import Context
        from core.models import Intent
        from skills.windows.native import remember_window, wait_for
        from skills.browser.handler import Handler, WindowsBrowserAdapter
        requests = []
        class Page(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                time.sleep(0.15)
                body = ('<!doctype html><title>Sirius isolated ' + self.path + '</title><p>Disposable localhost fixture</p>').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:' + str(self.server.server_port)
        browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        if not browser.is_file():
            browser = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
        profile = self.root / 'browser-profile'
        process = subprocess.Popen([str(browser), '--user-data-dir=' + str(profile), '--no-first-run',
                                    '--no-default-browser-check', '--disable-sync', '--disable-background-networking',
                                    '--disable-extensions', '--disable-background-mode', '--force-renderer-accessibility', '--remote-debugging-port=0',
                                    '--proxy-server=127.0.0.1:9', '--proxy-bypass-list=127.0.0.1;localhost', 'about:blank'])
        self.processes.append(process)
        port_file = profile / 'DevToolsActivePort'
        if not wait_for(port_file.exists, timeout=10):
            raise RuntimeError('Isolated browser CDP did not become available')
        port = port_file.read_text().splitlines()[0]
        def tabs():
            with urlopen('http://127.0.0.1:' + port + '/json', timeout=2) as response:
                return [x for x in json.load(response) if x.get('type') == 'page']
        def owned_browser():
            import psutil
            found = []
            for w in self.windows.windows():
                if w.hwnd in self.original_windows or w.process_name not in {'chrome.exe', 'msedge.exe'}:
                    continue
                try:
                    if any(str(profile) in arg for arg in psutil.Process(w.pid).cmdline()):
                        found.append(w)
                except psutil.Error:
                    pass
            return found
        wait_for(lambda: bool(owned_browser()), timeout=7)
        found = owned_browser()
        self.owned.extend(found)
        if len(found) != 1:
            raise RuntimeError('Cannot identify exactly one isolated browser HWND')
        window = found[0]
        context = Context()
        remember_window(context, window)
        class FixtureBrowser(WindowsBrowserAdapter):
            def target(adapter, unused):
                adapter.windows.require(window)
                return window
        adapter = FixtureBrowser(timeout=5)
        handler = Handler(adapter=adapter, config={'browser': {'search_url': base + '/search?q={query}'}})
        self.windows.activate(window)
        for action, params, expected in [
            ('open', {'url': base + '/one'}, base + '/one'),
            ('open', {'url': base + '/two'}, base + '/two'),
            ('back', {}, base + '/one'), ('forward', {}, base + '/two'),
            ('refresh', {}, base + '/two'), ('search', {'query': 'sirius fixture'}, base + '/search?q=sirius+fixture'),
            ('new_tab', {}, None), ('close_tab', {}, None),
        ]:
            before = tabs()
            if action == 'close_tab' and len(before) < 2:
                self.record('browser', action, outcome='untested', note='New-tab setup failed; do not close the only fixture tab.')
                continue
            hits = len(requests)
            result = handler.execute(Intent('browser', action, params), context)
            time.sleep(0.3)
            after = tabs()
            if action == 'new_tab':
                check = len(after) == len(before) + 1
            elif action == 'close_tab':
                check = len(after) == len(before) - 1
            else:
                check = any(t['url'] == expected for t in after)
                if action == 'refresh':
                    check = check and len(requests) > hits
            self.record('browser', action, result, check,
                        evidence={'CDP_tab_count_before': len(before), 'CDP_tab_count_after': len(after),
                                  'localhost_requests_added': len(requests) - hits,
                                  'document_urls': [x['url'] for x in after]})
            if result.status != 'success' and not check:
                # Keep diagnosing subsequent operations but never fabricate a prior state.
                pass

    def media(self):
        import winrt.runtime as runtime
        from skills.media.handler import WindowsMediaAdapter
        runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
        try:
            async def inspect():
                manager = await WindowsMediaAdapter()._manager()
                sessions = manager.get_sessions()
                session = manager.get_current_session()
                controls = session.get_playback_info().controls if session else None
                return {'session_count': len(sessions), 'current_session_available': session is not None,
                        'controls': {a: bool(getattr(controls, c, False)) for a, (c, _) in WindowsMediaAdapter.METHODS.items()}}
            available = asyncio.run(asyncio.wait_for(inspect(), timeout=5))
            self.record('media', 'availability_read_only', outcome='passed', evidence=available)
            for action in WindowsMediaAdapter.METHODS:
                self.record('media', action, outcome='untested', note='Read-only availability only; user playback never altered.')
        finally:
            runtime.uninit_apartment()

    def cleanup(self):
        from skills.windows.native import wait_for
        # A launch can finish after a failed observation; adopt only the exact
        # disposable Notepad command line, never a generic process-name match.
        import psutil
        for window in self.windows.windows():
            if window.hwnd in self.original_windows or window.process_name != 'notepad.exe':
                continue
            try:
                if str(self.root / 'notepad.txt') in psutil.Process(window.pid).cmdline():
                    self.owned.append(window)
            except psutil.Error:
                pass
        for window in reversed(self.owned):
            if window and window.hwnd not in self.original_windows and self.windows.validate(window):
                try:
                    self.windows.close(window)
                except Exception:
                    pass
        wait_for(lambda: all(not w or not self.windows.validate(w) for w in self.owned), timeout=4)
        self.report['cleanup']['owned_windows_closed'] = all(not w or not self.windows.validate(w) for w in self.owned)
        for process in self.processes:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                # Only Popen handles created by this probe; never unrelated apps.
                process.terminate()
                process.wait(timeout=4)
        self.report['cleanup']['owned_fixture_processes_exited'] = all(p.poll() is not None for p in self.processes)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.original_foreground and self.windows.validate(self.original_foreground):
            try:
                self.windows.activate(self.original_foreground)
            except Exception:
                pass
        self.engine.close()
        self.report['finished'] = datetime.now(timezone.utc).isoformat()
        self.save()

    def run(self):
        try:
            for method in [self.files, self.applications, self.native_fixture, self.browser, self.media_worker]:
                try:
                    method()
                except Exception as exc:
                    self.record(method.__name__, 'probe_error', outcome='failed', note=type(exc).__name__ + ': ' + str(exc))
        finally:
            self.cleanup()
        print(json.dumps({'report': str(ROOT / 'docs/NATIVE_TESTS.json'), 'counts': self.report['counts'],
                          'cleanup': self.report['cleanup']}, ensure_ascii=False), flush=True)
        return 1 if self.report['counts'].get('failed', 0) else 0

    def media_worker(self):
        # WinRT MTA initialization must not conflict with UIA/COM's STA thread.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.media).result(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture')
    args = parser.parse_args()
    if args.fixture:
        fixture(args.fixture)
    else:
        raise SystemExit(Probe().run())
