"""WinRT is mocked: tests never control a real player's session."""
from importlib import import_module
from types import SimpleNamespace

import pytest


def module():
    try:
        return import_module('skills.media.handler')
    except ModuleNotFoundError as exc:
        pytest.fail(f'Media implementation is missing: {exc}')


class Session:
    source_app_user_model_id = 'test.player'

    def __init__(self, status='PLAYING', track='Track A', accept=True, change=True):
        self.status = status
        self.track = track
        self.accept = accept
        self.change = change
        self.calls = []
        self.controls = SimpleNamespace(is_play_pause_toggle_enabled=True,
                                        is_pause_enabled=True, is_play_enabled=True,
                                        is_next_enabled=True, is_previous_enabled=True,
                                        is_stop_enabled=True)

    def get_playback_info(self):
        return SimpleNamespace(playback_status=SimpleNamespace(name=self.status), controls=self.controls)

    async def try_get_media_properties_async(self):
        return SimpleNamespace(title=self.track, artist='Test artist', album_title='Test album', track_number=1)

    async def run(self, action):
        self.calls.append(action)
        if self.change:
            if action == 'play_pause':
                self.status = 'PAUSED' if self.status == 'PLAYING' else 'PLAYING'
            elif action == 'pause':
                self.status = 'PAUSED'
            elif action == 'play':
                self.status = 'PLAYING'
            elif action == 'stop':
                self.status = 'STOPPED'
            else:
                self.track = 'Track B'
        return self.accept

    async def try_toggle_play_pause_async(self):
        return await self.run('play_pause')

    async def try_pause_async(self):
        return await self.run('pause')

    async def try_play_async(self):
        return await self.run('play')

    async def try_skip_next_async(self):
        return await self.run('next')

    async def try_skip_previous_async(self):
        return await self.run('previous')

    async def try_stop_async(self):
        return await self.run('stop')


def handler(session):
    async def manager():
        return SimpleNamespace(get_current_session=lambda: session)
    return module().Handler(module().WindowsMediaAdapter(manager_factory=manager, timeout=0.03, poll_interval=0))


@pytest.mark.parametrize('action', ['play_pause', 'pause', 'next', 'previous', 'stop'])
def test_native_media_command_requires_readback(action):
    session = Session()
    result = handler(session).execute(SimpleNamespace(skill='media', action=action, parameters={}), None)
    assert result.status == 'success' and result.verified
    assert session.calls == [action]
    assert 'title' not in result.details  # don't store private listening history


def test_no_session_is_unsupported():
    result = handler(None).execute(SimpleNamespace(skill='media', action='next', parameters={}), None)
    assert result.status == 'unsupported' and not result.verified


@pytest.mark.parametrize('accept,change', [(True, False), (False, False)])
def test_dispatch_or_rejection_without_change_is_not_success(accept, change):
    result = handler(Session(accept=accept, change=change)).execute(
        SimpleNamespace(skill='media', action='next', parameters={}), None)
    assert result.status == 'failed' and not result.verified


def test_unsupported_control_does_not_dispatch():
    session = Session()
    session.controls.is_stop_enabled = False
    result = handler(session).execute(SimpleNamespace(skill='media', action='stop', parameters={}), None)
    assert result.status == 'unsupported'
    assert session.calls == []


@pytest.mark.parametrize('action,state', [('pause','PAUSED'), ('play','PLAYING')])
def test_explicit_state_commands_are_idempotent(action, state):
    session = Session(status=state)
    result = handler(session).execute(SimpleNamespace(skill='media', action=action, parameters={}), None)
    assert result.verified and not session.calls


def test_resume_uses_play_instead_of_toggle():
    session = Session(status='PAUSED')
    result = handler(session).execute(SimpleNamespace(skill='media', action='play', parameters={}), None)
    assert result.verified and session.calls == ['play'] and session.status == 'PLAYING'


def test_pause_falls_back_to_toggle_only_when_playing():
    session = Session()
    session.controls.is_pause_enabled = False
    result = handler(session).execute(SimpleNamespace(skill='media', action='pause', parameters={}), None)
    assert result.verified and session.calls == ['play_pause'] and session.status == 'PAUSED'


@pytest.mark.parametrize('current_is_paused', [True, False])
def test_playing_session_wins_over_stale_paused_current(current_is_paused):
    paused, playing = Session(status='PAUSED'), Session()
    paused.source_app_user_model_id = 'ru.yandex.desktop.music'
    playing.source_app_user_model_id = 'Chrome'
    async def manager():
        return SimpleNamespace(get_current_session=lambda: paused if current_is_paused else None,
                               get_sessions=lambda: [paused, playing])
    adapter = module().WindowsMediaAdapter(manager_factory=manager)
    result = adapter.perform('pause')
    assert result['state'] == 'paused' and playing.calls == ['pause'] and not paused.calls


def test_foreground_player_wins_when_both_are_playing():
    music, video = Session(), Session()
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    video.source_app_user_model_id = 'Chrome.Profile1'
    async def manager():
        return SimpleNamespace(get_current_session=lambda: music, get_sessions=lambda: [music, video])
    adapter = module().WindowsMediaAdapter(manager_factory=manager, foreground_factory=lambda: 'chrome')
    adapter.perform('pause')
    assert video.calls == ['pause'] and not music.calls


def test_unsupported_next_does_not_switch_to_other_player():
    active, paused = Session(), Session(status='PAUSED')
    active.controls.is_next_enabled = False
    async def manager():
        return SimpleNamespace(get_current_session=lambda: paused, get_sessions=lambda: [active, paused])
    adapter = module().WindowsMediaAdapter(manager_factory=manager)
    with pytest.raises(module().MediaUnavailable): adapter.perform('next')
    assert not active.calls and not paused.calls


def test_ambiguous_same_app_sessions_are_not_collapsed_or_randomly_controlled():
    one, two = Session(), Session()
    async def manager():
        return SimpleNamespace(get_current_session=lambda: None, get_sessions=lambda: [one, two])
    adapter = module().WindowsMediaAdapter(manager_factory=manager)
    with pytest.raises(module().MediaUnavailable): adapter.perform('pause')
    assert not one.calls and not two.calls


def test_previous_can_verifiably_restart_current_track():
    from datetime import timedelta
    session = Session(change=False)
    positions = iter([timedelta(seconds=20), timedelta(seconds=.5)])
    session.get_timeline_properties = lambda: SimpleNamespace(position=next(positions))
    result = handler(session).execute(SimpleNamespace(skill='media', action='previous', parameters={}), None)
    assert result.verified and result.details['restarted'] and not result.details['track_changed']


def test_previous_rejection_is_not_verified_by_unchanged_track():
    session = Session(change=False)
    result = handler(session).execute(SimpleNamespace(skill='media', action='previous', parameters={}), None)
    assert not result.verified


def test_resume_remembers_player_just_paused_despite_stale_system_current():
    music, video = Session(), Session(status='PAUSED')
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    video.source_app_user_model_id = 'Chrome'
    async def manager():
        return SimpleNamespace(get_current_session=lambda: video, get_sessions=lambda: [music, video])
    adapter = module().WindowsMediaAdapter(manager_factory=manager)
    adapter.perform('pause')
    adapter.perform('pause')
    adapter.perform('play')
    assert music.calls == ['pause', 'play'] and not video.calls
    assert music.status == 'PLAYING' and video.status == 'PAUSED'


def test_pause_on_stopped_player_never_toggles_into_playing():
    session = Session(status='STOPPED')
    session.controls.is_pause_enabled = False
    result = handler(session).execute(SimpleNamespace(skill='media', action='pause', parameters={}), None)
    assert not result.verified and not session.calls


def test_failed_navigation_does_not_redirect_retry_to_another_paused_player():
    chrome, music = Session(change=False), Session(status='PAUSED')
    chrome.source_app_user_model_id = 'Chrome'
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    available = [chrome, music]
    async def manager():
        return SimpleNamespace(get_current_session=lambda: music, get_sessions=lambda: available)
    adapter = module().WindowsMediaAdapter(manager_factory=manager, timeout=.01, poll_interval=0)
    with pytest.raises(RuntimeError): adapter.perform('next')
    available.remove(chrome)
    with pytest.raises(module().MediaUnavailable): adapter.perform('previous')
    assert chrome.calls == ['next'] and not music.calls
    adapter.foreground_factory = lambda: 'ru.yandex.desktop.music'
    adapter.perform('play')
    assert music.calls == ['play']  # Explicit foreground selection still works.


def test_track_readback_follows_replacement_session_of_the_same_app():
    chrome, replacement, music = Session(change=False), Session(), Session(status='PAUSED')
    chrome.source_app_user_model_id = replacement.source_app_user_model_id = 'Chrome'
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    replacement.track = 'Track B'
    available = [chrome, music]
    async def skip():
        available[:] = [replacement, music]
        return True
    chrome.try_skip_next_async = skip
    async def manager():
        return SimpleNamespace(get_current_session=lambda: music, get_sessions=lambda: available)
    adapter = module().WindowsMediaAdapter(manager_factory=manager, timeout=.03, poll_interval=0)
    assert adapter.perform('next')['track_changed']
    assert not music.calls


def test_lost_target_readback_does_not_accept_another_apps_track_change():
    chrome, music = Session(change=False), Session()
    chrome.source_app_user_model_id = 'Chrome'
    music.source_app_user_model_id = 'ru.yandex.desktop.music'
    available = [chrome]
    async def skip():
        available[:] = [music]
        music.track = 'Track B'
        return True
    chrome.try_skip_next_async = skip
    async def manager():
        return SimpleNamespace(get_current_session=lambda: chrome, get_sessions=lambda: available)
    adapter = module().WindowsMediaAdapter(manager_factory=manager, timeout=.01, poll_interval=0)
    with pytest.raises(RuntimeError): adapter.perform('next')
    assert not music.calls
