"""GSMTC commands with bounded asynchronous state/track readback.

No blind media-key fallback: dispatch alone is not evidence of success.
"""
import asyncio


class MediaUnavailable(RuntimeError):
    """No session or no advertised support for the requested control."""


class NoActiveSession(MediaUnavailable):
    pass


class WindowsMediaAdapter:
    METHODS = {
        'play_pause': ('is_play_pause_toggle_enabled', 'try_toggle_play_pause_async'),
        'pause': ('is_pause_enabled', 'try_pause_async'),
        'play': ('is_play_enabled', 'try_play_async'),
        'next': ('is_next_enabled', 'try_skip_next_async'),
        'previous': ('is_previous_enabled', 'try_skip_previous_async'),
        'stop': ('is_stop_enabled', 'try_stop_async'),
    }

    def __init__(self, manager_factory=None, timeout=4.0, poll_interval=0.05, foreground_factory=None):
        self.manager_factory = manager_factory
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.foreground_factory = foreground_factory
        self._last_source = ''

    async def _manager(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        return await GlobalSystemMediaTransportControlsSessionManager.request_async()

    @staticmethod
    def _source(session):
        return (getattr(session, 'source_app_user_model_id', '') or '').casefold()

    def _foreground_source(self):
        # Foreground identity only breaks ties among real playback sessions.
        if self.foreground_factory is not None:
            return self.foreground_factory()
        if self.manager_factory is not None:
            return ''
        from skills.windows.native import WindowsAdapter
        window = WindowsAdapter().foreground()
        name = window.process_name.casefold() if window else ''
        return {'chrome.exe': 'chrome', 'msedge.exe': 'msedge', 'firefox.exe': 'firefox',
                'brave.exe': 'brave', 'opera.exe': 'opera', 'vivaldi.exe': 'vivaldi',
                'browser.exe': 'yandexbrowser', 'яндекс музыка.exe': 'ru.yandex.desktop.music',
                'yandexmusic.exe': 'ru.yandex.desktop.music'}.get(name, '')

    def _select_session(self, manager, action):
        current = manager.get_current_session()
        sessions = list(manager.get_sessions()) if hasattr(manager, 'get_sessions') else []
        if current is not None and not sessions:
            sessions.append(current)
        rows = []
        for session in sessions:
            try:
                state = session.get_playback_info().playback_status.name.lower()
                if state in {'playing', 'paused', 'stopped', 'opened'}:
                    rows.append((session, state))
            except (OSError, RuntimeError, AttributeError):
                continue
        if not rows:
            raise NoActiveSession('Проигрывание ещё не найдено. Сначала запустите трек или видео в приложении; затем скажите «пауза», «следующая» или «назад».')
        playing = [s for s, state in rows if state == 'playing']
        pool = [s for s, _ in rows] if action == 'play' else playing or [s for s, _ in rows]
        foreground = self._foreground_source()
        focused = [s for s in pool if foreground and foreground in self._source(s)]
        if len(focused) == 1:
            return focused[0]
        if not playing or action == 'play':
            recent = [s for s in pool if self._last_source and self._source(s) == self._last_source]
            if len(recent) == 1:
                return recent[0]
            if not playing and self._last_source and not recent:
                raise MediaUnavailable('Проигрыватель, которым вы управляли, сейчас недоступен. Подождите или выберите окно другого проигрывателя.')
        if len(pool) == 1:
            return pool[0]
        # Prefer actual WinRT identity; app IDs alone need not distinguish tabs.
        preferred = [s for s in pool if current is not None and s == current]
        if not preferred:
            preferred = [s for s in pool if current is not None and self._source(s) == self._source(current)]
        if len(preferred) == 1:
            return preferred[0]
        raise MediaUnavailable('Открыто несколько проигрывателей. Выберите окно нужного приложения и повторите команду.')

    def _remember(self, session, observed):
        # Remember only the app identity, never a COM wrapper or track metadata.
        self._last_source = self._source(session)
        return observed

    @staticmethod
    def _position(session):
        try:
            return session.get_timeline_properties().position.total_seconds()
        except (AttributeError, OSError, RuntimeError):
            return None

    @staticmethod
    async def _snapshot(session, track=False):
        playback = session.get_playback_info()
        state = playback.playback_status.name.lower()
        identity = None
        if track:
            properties = await session.try_get_media_properties_async()
            identity = (properties.title, properties.artist, properties.album_title, properties.track_number)
        return state, identity

    @staticmethod
    def _target_session(manager, source):
        matches = [s for s in manager.get_sessions() if WindowsMediaAdapter._source(s) == source]
        if len(matches) > 1:
            raise MediaUnavailable('У этого плеера несколько медиасессий. Выберите трек в приложении.')
        return matches[0] if matches else None

    async def _start_target(self, manager, target):
        from skills.media.start_button import invoke_play_button
        from skills.windows.native import NativeUnavailable
        try:
            verified = await asyncio.to_thread(invoke_play_button, target)
            if verified:
                self._last_source = target['source']
                return {'state': 'playing', 'track_changed': False}
        except NativeUnavailable as exc:
            raise MediaUnavailable(str(exc)) from exc
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            session = self._target_session(manager, target['source'])
            if session is not None and (await self._snapshot(session))[0] == 'playing':
                return self._remember(session, {'state': 'playing', 'track_changed': False})
            if asyncio.get_running_loop().time() >= deadline:
                raise MediaUnavailable('Плеер не подтвердил начало музыки. Проверьте, доступен ли трек в приложении.')
            await asyncio.sleep(self.poll_interval)

    async def _perform(self, action, target=None):
        if action not in self.METHODS:
            raise ValueError('Неизвестная медиа-команда.')
        manager = await (self.manager_factory or self._manager)()
        if target is not None:
            if action != 'play' or not target.get('source'):
                raise ValueError('Invalid playback target')
            session = self._target_session(manager, target['source'])
            if session is None:
                return await self._start_target(manager, target)
        else:
            session = self._select_session(manager, action)
        # Preserve the intended player even if dispatch/readback fails while
        # a browser replaces its session. A retry must not start other music.
        target_source = self._source(session)
        self._last_source = target_source
        control_name, method_name = self.METHODS[action]
        controls = session.get_playback_info().controls
        track = action in {'next', 'previous'}
        before_state, before_track = await self._snapshot(session, track)
        expected = {'pause': 'paused', 'play': 'playing', 'stop': 'stopped'}.get(action)
        if expected and before_state == expected:
            return self._remember(session, {'state': before_state, 'track_changed': False, 'already': True})
        if action == 'pause' and before_state not in {'playing', 'paused'}:
            raise MediaUnavailable('В этом проигрывателе воспроизведение ещё не запущено.')
        if not getattr(controls, control_name, False):
            if action in {'pause', 'play'} and getattr(controls, 'is_play_pause_toggle_enabled', False):
                method_name = 'try_toggle_play_pause_async'
            else:
                if target and action == 'play':
                    return await self._start_target(manager, target)
                raise MediaUnavailable('Этот проигрыватель не предоставляет нужную кнопку Windows. Для перехода назад или вперёд на YouTube может потребоваться плейлист.')
        if action == 'play_pause' and before_state not in {'playing', 'paused', 'stopped', 'opened'}:
            raise MediaUnavailable('Проигрыватель пока не сообщает устойчивое состояние воспроизведения.')
        before_position = self._position(session) if action == 'previous' else None
        if not await getattr(session, method_name)():
            if target and action == 'play':
                return await self._start_target(manager, target)
            raise RuntimeError('Проигрыватель отклонил команду.')
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            if target_source and hasattr(manager, 'get_sessions'):
                candidates = [s for s in manager.get_sessions() if self._source(s) == target_source]
                if session not in candidates:
                    if len(candidates) == 1:
                        session = candidates[0]
                    else:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise RuntimeError('Выбранный проигрыватель не восстановил медиасессию.')
                        await asyncio.sleep(self.poll_interval)
                        continue
            after_state, after_track = await self._snapshot(session, track)
            restarted = False
            if track:
                verified = after_track != before_track and any(after_track)
                if action == 'previous' and not verified and before_position is not None and before_position > 3:
                    after_position = self._position(session)
                    restarted = after_position is not None and 0 <= after_position < 2
                    verified = restarted
            elif action == 'stop':
                verified = after_state == 'stopped'
            else:
                expected = expected or ('paused' if before_state == 'playing' else 'playing')
                verified = after_state == expected
            if verified:
                # Metadata is compared privately and never returned to logs/history.
                return self._remember(session, {'state': after_state, 'track_changed': bool(track and not restarted), 'restarted': restarted})
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError('Изменение состояния проигрывателя не подтверждено.')
            await asyncio.sleep(self.poll_interval)

    def perform(self, action, target=None):
        if target and target.get('site'):
            from skills.media.web_player import play_web_target
            from skills.windows.native import NativeUnavailable
            if action != 'play':
                raise ValueError('Unsupported tab operation')
            try:
                return play_web_target(target)
            except NativeUnavailable as exc:
                raise MediaUnavailable(str(exc)) from exc
        # UI Automation and Shell discovery can leave the command thread in STA.
        # Create WinRT objects and dispose them on their own MTA thread.
        if self.manager_factory is None:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='sirius-media') as worker:
                return worker.submit(self._run_media, action, target).result()
        return self._run_media(action, target)

    def _run_media(self, action, target):
        runtime = None
        initialized = False
        try:
            if self.manager_factory is None:
                import winrt.runtime as runtime
                runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
                initialized = True
            async def bounded():
                return await asyncio.wait_for(self._perform(action, target), timeout=self.timeout + (8 if target else 3))
            return asyncio.run(bounded())
        finally:
            if initialized:
                runtime.uninit_apartment()


class Handler:
    def __init__(self, adapter=None, config=None):
        self.config = config or {}
        self.adapter = adapter if adapter is not None else WindowsMediaAdapter()

    def _generic_play(self, context):
        try:
            return self.adapter.perform('play')
        except NoActiveSession:
            from skills.media.open_player import find_open_player
            from skills.windows.native import NativeUnavailable
            try:
                target = find_open_player(self.config, getattr(context, 'last_window', None))
            except NativeUnavailable as exc:
                raise MediaUnavailable(str(exc)) from exc
            return self.adapter.perform('play', target=target)

    def execute(self, intent, context):
        from core.models import Result
        if intent.skill != 'media' or intent.action not in WindowsMediaAdapter.METHODS:
            return Result.fail('Неизвестная медиа-команда.')
        try:
            if intent.parameters.get('history_if_youtube') and self.adapter.__class__ is WindowsMediaAdapter and self.adapter.manager_factory is None:
                from skills.media.web_player import youtube_back
                back = youtube_back(context)
                if back is True:
                    return Result.ok('Переход назад во вкладке YouTube подтверждён.')
                if back is False:
                    return Result.unsupported('Во вкладке YouTube не подтверждён переход на предыдущую страницу.')
            if intent.parameters.get('player'):
                from skills.applications.handler import WindowsApplicationAdapter
                from skills.applications.manager import playback_target
                from skills.applications.registry import app_registry
                from skills.windows.native import NativeUnavailable
                player = intent.parameters['player']
                windows = WindowsApplicationAdapter()
                try:
                    spec = windows.prepare(app_registry(self.config)[player])
                    window = windows.existing_player(spec)
                    if not window or not windows.validate(window):
                        return Result.unsupported('Откройте нужный плеер или вкладку с видео.')
                    target = playback_target(spec, window)
                    observed = self.adapter.perform(intent.action, target=target)
                except NativeUnavailable as exc:
                    return Result.unsupported(str(exc))
            elif intent.parameters.get('source'):
                observed = self.adapter.perform(intent.action, target=intent.parameters)
            elif intent.action == 'play' and context is not None and context.data.get('opened_player'):
                from skills.applications.registry import app_registry
                spec = app_registry(self.config).get((context.last_app or '').casefold())
                target = context.data['opened_player']
                if spec and spec.media_source == target['source']:
                    observed = self.adapter.perform('play', target=target)
                else:
                    observed = self._generic_play(context)
            elif intent.action == 'play':
                observed = self._generic_play(context)
            else:
                observed = self.adapter.perform(intent.action)
            if not isinstance(observed, dict) or observed.get('state') not in {'playing', 'paused', 'stopped', 'opened'}:
                return Result.fail('Нет достоверного состояния проигрывателя.')
            messages = {'play_pause': 'Состояние воспроизведения изменено.',
                        'pause': 'Воспроизведение на паузе.',
                        'play': 'Воспроизведение продолжается.',
                        'next': 'Переход к следующему треку подтверждён.',
                        'previous': 'Переход к предыдущему треку подтверждён.',
                        'stop': 'Воспроизведение остановлено.'}
            expected = {'pause': 'paused', 'play': 'playing', 'stop': 'stopped'}.get(intent.action)
            if expected and observed['state'] != expected:
                return Result.fail('Запрошенное состояние проигрывателя не подтверждено.')
            if intent.action in {'next', 'previous'} and not (observed.get('track_changed') or observed.get('restarted')):
                return Result.fail('Переход трека не подтверждён проигрывателем.')
            message = 'Текущий трек запущен с начала.' if observed.get('restarted') else messages[intent.action]
            return Result.ok(message, state=observed['state'],
                             track_changed=bool(observed.get('track_changed')), restarted=bool(observed.get('restarted')))
        except MediaUnavailable as exc:
            return Result.unsupported(str(exc))
        except ImportError:
            return Result.unsupported('Windows Media Control недоступен: установите зависимости WinRT.')
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError, AttributeError):
            return Result.fail('Проигрыватель не подтвердил выполнение медиа-команды.')
