# Desktop revision — 04 November 2026

Current user request supersedes the old Foundation size: compact panels, one black glass material (dark) and a holographic face from the latest user reference. Wake/sleep follows real voice events with a 60-second text-only fallback. A chat icon, upward send arrow, decorative binary glyphs, state caption and tray zoom options are part of this revision. See UI_FACE.md. The earlier reference path below is provenance only; the current two user attachments determine the visual direction.

# SIRIUS v0.3 Foundation integration contract

This is the new isolated project. Original versions MUST remain read-only.
Specification: C:/Users/Altynbek/Downloads/SIRIUS_FINAL_CODEX_ASTRA_PROMPT.json.
Python: .venv/Scripts/python.exe (3.12). Tests: env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q.

## Core API (parent owns core/, security/, storage/, config/, main.py)
`core.models.Command(text: str, source: str = 'text', session_id: str = 'desktop')`
`core.models.Intent(skill: str, action: str, parameters: dict = {}, context_reference: str | None = None)`
`core.models.Result(status: str, message: str, verified: bool = False, details: dict = {})`
Statuses exactly success/failed/unsupported/needs_confirmation/not_understood. `success` MUST be readback-verified; command merely dispatched with no observable outcome is unsupported or failed, never success.
`Result.ok(message, **details)` returns success verified True; `Result.fail(message, **details)` returns failed; `Result.unsupported(message, **details)` returns unsupported.
No secret payloads in results/events/history.

`core.context.Context`: dataclass `session_id: str = 'desktop'`, `last_app: str | None = None`, `last_window: int | None = None`, `last_skill: str | None = None`, `last_action: str | None = None`, `data: dict = {}`. It is private per-session and only accessed by serialized command worker. An integer native HWND in parameters or context must be validated at operation time, including PID identity when possible. Never target our own UI for background input commands.

`core.engine.Engine(config: dict, data_dir: Path, event_callback: Callable[[dict],None] | None = None, registry=None)`
- `execute(command: Command) -> Result` synchronous, serialized, run in worker NOT GUI.
- `recognizes(text: str, session_id='desktop') -> bool` pure router probe for speech filtering.
- `close()` closes storage.
- `history.recent(limit=200) -> list[dict]`, rows have text, source, session_id, time, status, message, verified, skill.
- Events dictionaries: {type: 'recognized'|'started'|'completed'|'error', text: redacted string, source, session_id, time: ISO string, skill, result?: {status,message,verified,details}}. Unknown voice must emit NOTHING. Unknown text should appear with not_understood result.
- Confirmation uses SAME normal input: reply exactly `подтверждаю` or `отмена`. Security retains pending action server-side, expires it, single-use, same session only. It returns needs_confirmation with precise safe summary; UI needs no extra buttons.

## Skills API (agents own separate skill directories, not core)
Exactly 10 directories. Each `skills/<id>/handler.py` exports `Handler`:
`Handler(adapter=None, config=None)`; `execute(intent: Intent, context: Context) -> Result`.
Default adapter is REAL Windows implementation, injectable fake only in tests. Lazy imports/native resources to keep basic tests importable. No shell=True, no arbitrary command execution, no killing system processes. Each handler must validate parameters even when router validates.
Each `phrases.json` format:
{"skill":"volume","rules":[{"action":"set","patterns":["(?:громкость|установи громкость)(?: на)? (?P<value>-?\\d+)(?: ?%| процентов?)?"],"parameters":{},"examples":["громкость 70","громкость на 70%"]}]}
Router fullmatches case-insensitively; patterns MUST NOT include leading ^ or trailing $ (fullmatch used); raw original captures preserved for paths/clipboard payloads. Named numeric captures `value`, `delta`, `step` converted to integers (Russian number words normalized outside literal payload). Parameters fixed values merge with named captures. Path captures named `path`, `destination`; app capture `app`; text payload `text`; browser `url`/`query`; window optional `target`. Literal paths use double quotes to disambiguate rename/move. Skill patterns may include imperative/infinitive synonyms.
Action names:
- volume/brightness: set {value}, adjust {delta}, mute/unmute (volume only).
- applications: open/close/status/restart {app}. App aliases resolve via config applications. close/restart ALWAYS need core confirmation; last app `его` context resolution core-side.
- windows: minimize/maximize/restore/switch/desktop/activate {target?}.
- browser: open {url}, search {query}, new_tab/close_tab/refresh/back/forward.
- media: play_pause/next/previous/stop.
- files: mkdir/touch/open/trash {path}; rename/move {path,destination}.
- clipboard: status/copy/paste/select_all/set {text}.
- screenshot: full/window.
- system_monitor: cpu/ram/disk/battery/temperature.

## Config
`config/defaults.json` plain dict:
voice {enabled: true, device: null, model_path: 'models/ru_vosk', active_seconds:60, sample_rate:16000, min_confidence:0.65}; hotkey {modifiers:1, key:77}; history {enabled:true, retention_days:30}; files {root:'%USERPROFILE%/Documents/Sirius', allowed_roots:[...]}; applications {name:{command:[absolute exe or safe allowlisted exe],process_names:[...],aliases:[...]}}; ui {chat_visible:true}; screenshot {directory:'%USERPROFILE%/Pictures/Sirius Screenshots'}.
Core config adds `_resource_root` absolute bundled resource directory and `_data_dir`.
Safe default apps calculator/notepad/explorer/browser in adapter; configured executables require explicit configured path, never derive executable from free speech.

## Voice API (voice agent owns voice/ and tests/test_voice*.py)
`voice.service.VoiceService(config, on_text, on_state, on_level, is_recognized)` callbacks; `start()`, `stop()`, `activate()`, `command_completed(recognized: bool = True)`, `set_enabled(bool)`.
Callback on_state(string) idle/listening/processing/error, errors via optional on_error(str) constructor kwarg.
State machine monotonic 60s, unknowns don't reset; completion of recognized commands resets active deadline. Source ui bridge sends Command(...,'voice','desktop'). Model loaded once; no downloads; background audio worker; reconnect cleanly. Existing model copied by parent to models/ru_vosk.
`voice.hotkey.GlobalHotkey(callback, modifiers=1, key=77, on_error=None)` start/stop, Windows RegisterHotKey Alt+M no admin. Don't install hooks globally for keyboard collection.

## UI API (UI agent owns ui/, tests/test_ui*.py)
`ui.app.run(config: dict, data_dir: Path, *, smoke_output: Path | None = None, no_voice: bool = False) -> int` creates Engine and bridge. Parent main calls this.
180x284 and 360x284 logical panels SAME shared scale, chat exactly twice mini, no prohibited UI. Paired top/bottom, dock dragging, clamp available screen; mini stays stable when chat toggled. Frameless dark-blue glass, rounded cyan edge. Holographic eyes and smile replace M, with a digital shell and fine orbital lines. A chat icon at top left toggles chat without waking the face. No theme switch or theme tray menu; ui.theme is fixed to dark. One X each. Only chat title, truthful messages and bottom composer/send. No timer/mic/minus/tabs. Small binary glyphs are decorative, never fabricated reasoning or telemetry. X mini -> tray; X chat -> chat only. Tray show, activation, mic toggle, clear history, exit (settings via config, no extra panels). All commands and model load off GUI thread.
QML named objects for tests and smoke: miniWindow, chatWindow, miniChatToggle, miniClose, faceActivate, chatClose, commandInput, sendButton, messageList. Smoke must issue real harmless CPU text command, capture both windows, record geometry and QML errors, exit cleanly. Never insert example history.
Current character reference: ui/assets/hologram-reference.png, copied unmodified from the user's 19 October face illustration. Retain 180:360 widths and 284 shared-height logical geometry. Black glass and animated eye/mouth transitions supersede the earlier M design; do not bake controls/history into images. Engine.set_window_context(hwnd, pid=None, session_id='desktop') is the implemented external-target snapshot API; UI must call this exact method, not set_external_window.

## Ownership
Parent: core/security/storage/config/main/build/requirements/docs/integration.
Skills agent A: volume,brightness,applications,windows,browser + matching tests, any adapters under owned dirs.
Skills agent B: media,files,clipboard,screenshot,system_monitor + matching tests.
Voice agent: voice + voice tests.
UI agent: ui + UI tests.
Audit agent: docs/AUDIT.md and docs/legacy-manifest.json only.
Shared contract changes must be communicated; do not overwrite another agent's files.
TDD: write failing behavior tests, run, implement, run. Record actual evidence, not imagined test counts. Use tools and finish runnable code, no stubs. Never execute intrusive live skills in tests without parent coordinating; mock native boundaries for unit tests. Parent handles real hardware probes and portable acceptance.

Latest refinement: animation is frozen at startup and after the sleep transition. Only explicit activation (sphere, voice wake, Alt+M/tray activation, or exact case-insensitive Sirius/Сириус prefix in chat) starts it. Ordinary chat commands remain functional but do not wake the face. Retired clear and blue settings migrate to dark. Feature UV bounds use the actual 1254px reference; face scale 2.62 and centre (0.5005, 0.5323).

Latest request: onboarding says Alt + M or say Sirius, and type help. Help is an informational Engine built-in, not an eleventh Windows skill. Typed and recognized speech aliases produce a canonical help history row. The helpPresented signal opens chat and scrolls to the start of the guide. No execution of examples during help.
