"""Window commands replace unsafe blind hotkeys in legacy lite/windows.py."""
from core.models import Result
from skills.windows.native import WindowsAdapter, NativeUnavailable, context_target, remember_window, wait_for, focus_window
import os


class Handler:
    def __init__(self, adapter=None, config=None):
        self.adapter = adapter if adapter is not None else WindowsAdapter()
        self.config = config or {}

    def _safe(self, window):
        return window is not None and window.pid != os.getpid() and self.adapter.validate(window)

    def _target(self, parameters, context):
        target = parameters.get('target')
        if target is None:
            return context_target(self.adapter, context)
        if type(target) is int and target > 0:
            window = self.adapter.window(target)
            expected_pid = parameters.get('pid')
            if expected_pid is not None and (type(expected_pid) is not int or not window or window.pid != expected_pid):
                return None
            return window if self._safe(window) else None
        if not isinstance(target, str) or not target.strip():
            return None
        key = target.strip().casefold()
        names = {key, key + '.exe'}
        from skills.applications.registry import app_registry
        spec = app_registry(self.config).get(key)
        if spec is not None:
            from skills.applications.handler import WindowsApplicationAdapter
            apps = WindowsApplicationAdapter(self.adapter)
            matches = apps.find_windows(apps.prepare(spec))
            return matches[0] if len(matches) == 1 and self._safe(matches[0]) else None
        matches = [w for w in self.adapter.windows() if self._safe(w)
                   and (w.title.casefold() == key or w.process_name.casefold() in names)]
        return matches[0] if len(matches) == 1 else None

    def execute(self, intent, context):
        action = intent.action
        if action not in {'minimize', 'maximize', 'restore', 'switch', 'desktop', 'activate'}:
            return Result.fail('Неизвестное действие с окнами.')
        try:
            if action == 'desktop':
                windows = [w for w in self.adapter.windows() if self._safe(w)]
                for window in windows:
                    self.adapter.show(window, 'minimize')
                if not wait_for(lambda: all(not self.adapter.validate(w) or self.adapter.state(w) == 'minimized' for w in windows)):
                    return Result.fail('Не все окна свернуты; рабочий стол не подтвержден.')
                return Result.ok('Окна свернуты, рабочий стол показан.', windows=len(windows))
            if action == 'switch':
                active = self.adapter.foreground()
                choices = [w for w in self.adapter.windows() if self._safe(w) and (active is None or w.hwnd != active.hwnd)]
                window = choices[0] if choices else None
            else:
                window = self._target(intent.parameters, context)
            if not self._safe(window):
                return Result.fail('Не удалось однозначно определить безопасное окно.')
            if action in {'activate', 'switch'}:
                if not focus_window(self.adapter, window, self._safe):
                    return Result.fail('Windows не подтвердила переход к окну.')
            else:
                self.adapter.show(window, action)
                expected = {'minimize': 'minimized', 'maximize': 'maximized', 'restore': 'normal'}[action]
                def verified():
                    return self._safe(window) and self.adapter.state(window) == expected
                if not wait_for(verified):
                    return Result.fail('Windows не подтвердила изменение состояния окна.')
            remember_window(context, window)
            message = {'minimize':'Окно свернуто.', 'maximize':'Окно развернуто.',
                       'restore':'Окно восстановлено.', 'switch':'Окно переключено.',
                       'activate':'Окно активировано.'}[action]
            return Result.ok(message, hwnd=window.hwnd, pid=window.pid)
        except NativeUnavailable as exc:
            return Result.unsupported(str(exc))
        except Exception:
            return Result.fail('Windows отклонила операцию с окном.')
