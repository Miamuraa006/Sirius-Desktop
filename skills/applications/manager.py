"""One application lifecycle shared by every registered target."""
from dataclasses import replace
import time
from core.context import Question
from core.models import Intent, Result
from skills.applications.catalog import resolve_app, protected
from skills.windows.native import NativeUnavailable, remember_window, wait_for


def playback_target(spec, window):
    target = {'source': spec.media_source, 'hwnd': window.hwnd, 'pid': window.pid,
              'created': window.created, 'executable': window.executable, 'play_buttons': spec.play_buttons}
    if getattr(window, 'tab_id', None):
        target.update(site=window.url, tab_id=window.tab_id)
        if spec.name == 'youtube':
            from skills.applications.web_target import youtube_video
            target['video'] = youtube_video(window.document_url)
    return target


class ApplicationManager:
    def __init__(self, adapter, config=None):
        self.adapter = adapter
        self.config = config or {}

    def execute(self, intent, context):
        if intent.action == 'list' and intent.parameters.get('surface') == 'installed':
            from skills.applications.catalog import installed_catalog
            from skills.applications.registry import app_registry
            names = sorted({s.name for s in (*installed_catalog().values(), *app_registry(self.config).values()) if s}, key=str.casefold)
            return Result.ok('Доступные программы: ' + ', '.join(names), count=len(names))
        if intent.action == 'list' and intent.parameters.get('surface'):
            from skills.applications.catalog import taskbar_labels
            tray = intent.parameters['surface'] == 'tray'
            labels = taskbar_labels(tray)
            message = ('Область уведомлений: ' if tray else 'Панель задач: ') + '; '.join(labels)
            return Result.ok(message, count=len(labels)) if labels else Result.unsupported('Windows не показывает значки. Откройте стрелку трея и повторите.')
        if intent.action == 'list':
            windows = self.adapter.windows.windows()
            names = sorted({w.process_name for w in windows})
            return Result.ok('Открытые окна: ' + (', '.join(names) or 'нет'), count=len(names))
        name = intent.parameters.get('app')
        if not isinstance(name, str) or not name.strip():
            return Result.fail('Укажите зарегистрированное приложение.')
        try:
            if protected(name) and intent.action in {'close', 'close_app', 'restart'}:
                return Result.fail('Эта программа защищена от закрытия.')
            spec = resolve_app(name, self.config)
            if spec is None:
                return Result.fail('Приложение не зарегистрировано в разрешенном списке.')
            actions = {'open_app': self.open_app, 'close_app': self.close_app, 'focus_app': self.focus_app,
                       'open': self.open_app, 'close': self.close_app, 'restart': self.restart, 'status': self.status}
            if intent.action not in actions:
                return Result.fail('Неизвестное действие с приложением.')
            if intent.action in {'close', 'close_app', 'restart'} and context.data.get('confirmed') is not True:
                return Result('needs_confirmation', 'Закрытие или перезапуск требует подтверждения через ядро Sirius.')
            spec = self.adapter.prepare(spec)
            result = actions[intent.action](spec, context)
            if result.verified and spec.media_source and intent.action in {'open', 'open_app'}:
                target = context.data['opened_player']
                if target.get('video') == '':
                    return replace(result, message='YouTube открыт. Выберите видео и скажите «включи видео на ютубе».')
                context.question = Question(Intent('media', 'play', target), time.monotonic() + 60)
                prompt = 'Включить видео?' if spec.name == 'youtube' else 'Включить музыку?'
                return replace(result, message=prompt + ' Ответьте «да» или «нет».',
                               details={**result.details, 'presentation': 'question', 'spoken_question': prompt})
            return result
        except NativeUnavailable as exc:
            return Result.unsupported(str(exc))
        except ValueError:
            return Result.fail('Проверьте регистрацию приложения и повторите команду, если его окно изменилось.')
        except Exception:
            return Result.fail('Не удалось выполнить операцию с приложением Windows.')

    def _windows(self, spec):
        windows = self.adapter.find_windows(spec)
        if any(not self.adapter.validate(window) for window in windows):
            raise ValueError('Window identity changed')
        return windows

    def status(self, spec, context):
        running = bool(self._windows(spec))
        return Result.ok('Окна приложения найдены.' if running else 'Открытых окон приложения нет.',
                         app=spec.name, running=running)

    def _remember(self, spec, context, window, message):
        remember_window(context, window)
        context.last_app = spec.name
        if spec.media_source:
            context.data['opened_player'] = playback_target(spec, window)
        return Result.ok(message, app=spec.name, hwnd=window.hwnd, pid=window.pid)

    def open_app(self, spec, context):
        if spec.media_source and hasattr(self.adapter, 'existing_player'):
            existing = self.adapter.existing_player(spec)
            if existing is not None and self.adapter.validate(existing):
                self.adapter.focus(existing)
                if not self.adapter.validate(existing):
                    return Result.fail('Цель воспроизведения изменилась.')
                return self._remember(spec, context, existing, 'Открытый плеер выбран.')
        opened_windows = self._windows(spec)
        if opened_windows and hasattr(self.adapter, 'existing_player') and self.adapter.focus(opened_windows[0]):
            return self._remember(spec, context, opened_windows[0], 'Приложение уже открыто и выбрано.')
        before = {w.hwnd for w in opened_windows}
        self.adapter.launch(spec)
        observed = []
        def opened():
            observed[:] = self._windows(spec)
            return bool(observed)
        if not wait_for(opened, timeout=60.0 if spec.shell_item == 'steam://rungameid/730' else 8.0):
            return Result.fail('Запуск отправлен, но окно приложения не обнаружено.')
        window = next((w for w in observed if w.hwnd not in before), observed[0])
        return self._remember(spec, context, window, 'Приложение открыто.')

    def focus_app(self, spec, context):
        windows = self._windows(spec)
        if not windows:
            return Result.fail('Открытого окна приложения не найдено.')
        window = windows[0]  # EnumWindows returns the topmost matching window first.
        if not self.adapter.focus(window):
            return Result.fail('Windows не разрешила переключить окно. Откройте чат Sirius и повторите команду.')
        return self._remember(spec, context, window, 'Окно приложения на переднем плане.')

    def close_app(self, spec, context):
        windows = self._windows(spec)
        processes = self.adapter.background_processes(spec) if hasattr(self.adapter, 'background_processes') else []
        if spec.url and not windows:
            return Result.fail('Видимой вкладки сайта не найдено.')
        for window in windows:
            if not self.adapter.validate(window):
                return Result.fail('Окно изменилось до закрытия.')
            self.adapter.close(window)
        if not wait_for(lambda: not self.adapter.find_windows(spec), timeout=3.0):
            return Result.fail('Окно осталось открытым. Возможно, приложение ожидает сохранения документа.')
        if processes and not self.adapter.finish_background(spec, processes):
            return Result.fail('Окна закрыты, но процесс ещё работает.')
        if context.last_window in {w.hwnd for w in windows}:
            context.last_window = None
            for key in ('window_pid', 'last_window_pid', 'last_window_created'):
                context.data.pop(key, None)
        if processes:
            return Result.ok('Приложение закрыто. Завершение процесса подтверждено.', app=spec.name, closed=len(windows))
        return Result.ok('Окна приложения закрыты.' if windows else 'Открытых окон приложения нет.',
                         app=spec.name, closed=len(windows))

    def restart(self, spec, context):
        closed = self.close_app(spec, context)
        if not closed.verified:
            return closed
        result = self.open_app(spec, context)
        if result.verified:
            return Result.ok('Окна приложения перезапущены.', **result.details)
        return result
