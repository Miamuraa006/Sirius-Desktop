"""Offline WAV diagnostics; no live capture, playback or command execution.

The callable run_probe is also imported by the frozen CLI. No test dependency
belongs here. Recognition uses the same VoskSTT/VoskWakeWord as VoiceService.
"""
from __future__ import annotations

import array
import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
import platform
import queue
import random
import sys
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from voice.audio_input import enumerate_inputs
from voice.hotkey import GlobalHotkey, Win32HotkeyAPI
from voice.stt import VoskModel, VoskSTT
from voice.wake_word import VoskWakeWord


def recognize_wav(path, recognizer, *, expected_text=None, expected_wake=None,
                  min_confidence=.65, trailing_silence_seconds=2.0):
    """Feed 50 ms PCM blocks faster than realtime; distinguish time domains.

    endpoint_audio_seconds is the sample-clock distance between Vosk's last
    recognized word end and its streaming endpoint, NOT a live microphone or
    wall-clock latency. EOF flushing is explicitly not a streaming endpoint.
    """
    path = Path(path)
    with wave.open(str(path), "rb") as stream:
        rate, frames = stream.getframerate(), stream.getnframes()
        if (stream.getnchannels() != 1 or stream.getsampwidth() != 2 or
                stream.getcomptype() != "NONE" or not 8000 <= rate <= 48000 or
                not 0 < frames <= rate * 120):
            raise ValueError("Probe requires bounded mono signed 16-bit PCM WAV")
        pcm = stream.readframes(frames)
    if len(pcm) != frames * 2:
        raise ValueError("Truncated probe WAV")
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    block_bytes = (rate // 20) * 2
    events = []
    is_wake = expected_wake is not None
    feed_seconds = 0.0
    confirmation_seconds = 0.0
    started = time.perf_counter()
    offset = 0

    def event(result, kind, accepted=False):
        if result is None:
            return
        verification = getattr(recognizer, "last_verification", None) if is_wake else None
        events.append({
            "text": result.text, "confidence": result.confidence,
            "words": [{"text": word.text, "confidence": word.confidence,
                       "start_seconds": word.start, "end_seconds": word.end,
                       "duration_seconds": round(word.duration, 6)} for word in result.words],
            "result_kind": kind, "wake_accepted": bool(accepted),
            "verification": ({"text": verification.text, "confidence": verification.confidence,
                              "word_durations_seconds": [round(word.duration, 6) for word in verification.words]}
                             if verification is not None else None),
            "confirmation_wall_seconds": getattr(recognizer, "verification_wall_seconds", 0.0) if is_wake else None,
            "stream_offset_seconds": offset / (rate * 2),
            "endpoint_audio_seconds": (round(max(0.0, offset / (rate * 2) - result.words[-1].end), 6)
                                       if kind == "stream_endpoint" else None),
            "decoder_wall_to_result_seconds": time.perf_counter() - started,
        })

    padded = pcm + b"\0\0" * int(rate * trailing_silence_seconds)
    for start in range(0, len(padded), block_bytes):
        block = padded[start:start + block_bytes]
        offset += len(block)
        before = time.perf_counter()
        result = recognizer.feed(block)
        feed_seconds += time.perf_counter() - before
        if is_wake:
            confirmation_seconds += getattr(recognizer, "verification_wall_seconds", 0.0)
        event(recognizer.last_result if is_wake else result, "stream_endpoint",
              accepted=result if is_wake else False)
    before = time.perf_counter()
    final = (recognizer.stt if is_wake else recognizer).finish()
    feed_seconds += time.perf_counter() - before
    event(final, "eof_flush")  # A flush cannot stand in for actual wake activation.
    text = " ".join(row["text"] for row in events)
    confidence = min((row["confidence"] for row in events), default=None)
    accepted = any(row["wake_accepted"] for row in events)
    passed = ((accepted is expected_wake) if is_wake else
              text == expected_text and (not text or (confidence is not None and confidence >= min_confidence)))
    return {
        "expected_text": expected_text, "observed_text": text,
        "expected_wake": expected_wake, "wake_accepted": accepted,
        "passed": passed, "min_confidence": confidence,
        "confidence_threshold": .85 if is_wake else min_confidence,
        "wav": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "sample_rate": rate, "channels": 1, "sample_width_bytes": 2,
                "frames": frames, "duration_seconds": frames / rate,
                "peak_amplitude": max(abs(value) for value in samples) / 32768.0},
        "trailing_silence_seconds": trailing_silence_seconds,
        "feed_block_seconds": (block_bytes / 2) / rate,
        "decoder_wall_seconds": feed_seconds,
        "wake_confirmation_wall_seconds": confirmation_seconds if is_wake else None,
        "total_analysis_wall_seconds": time.perf_counter() - started,
        "realtime_factor": feed_seconds / (len(padded) / (rate * 2)),
        "events": events,
    }


# Local-copy receipt recorded in docs/AUDIT.md, not an upstream authenticity claim.
_AUDITED_MODEL_TREE = "3a4ed71d00f4f93c0911e1f8b7184b054960568a6802310810dc04db15907949"
_SPEECH_CASES = (
    ("counting", "один два три четыре пять", "stt", "один два три четыре пять"),
    ("command_volume", "громкость семьдесят", "stt", "громкость семьдесят"),
    ("command_quieter", "тише", "stt", "тише"),
    ("wake_sirius", "Сириус", "wake", True),
    ("nonwake_service", "сервис", "wake", False),
    ("nonwake_series", "серия", "wake", False),
    ("nonwake_sentence", "сегодня хорошая погода", "wake", False),
)
_NOISE_CASES = ("silence", "white_noise", "tone")


def _model_receipt(path):
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("Linked model files cannot be inventoried")
        if item.is_file():
            rows.append({"path": item.relative_to(path).as_posix(), "bytes": item.stat().st_size,
                         "sha256": hashlib.sha256(item.read_bytes()).hexdigest()})
        if len(rows) > 1024:
            raise ValueError("Model inventory is too large")
    rows.sort(key=lambda row: row["path"])
    digest = hashlib.sha256("".join(row["path"] + "\0" + row["sha256"] + "\n" for row in rows).encode()).hexdigest()
    return {"files": rows, "file_count": len(rows), "bytes": sum(row["bytes"] for row in rows),
            "tree_sha256": digest, "audited_tree_sha256": _AUDITED_MODEL_TREE,
            "matches_audited_copy": digest == _AUDITED_MODEL_TREE,
            "provenance": "Local copy receipt from docs/AUDIT.md; not an upstream authenticated checksum"}


def _sapi_files(directory):
    import pythoncom
    from win32com.client.dynamic import Dispatch

    pythoncom.CoInitialize()
    speaker = voices = token = stream = fmt = None
    try:
        speaker = Dispatch("SAPI.SpVoice")
        voices = speaker.GetVoices()
        inventory = []
        selected = None
        for index in range(voices.Count):
            token = voices.Item(index)
            languages = str(token.GetAttribute("Language"))
            inventory.append({"name": str(token.GetDescription()), "language": languages})
            if selected is None and any(code.strip().lower().lstrip("0") == "419"
                                        for code in languages.split(";")):
                selected = token
        if selected is None:
            return {"status": "unsupported", "reason": "No installed SAPI voice with language 419",
                    "voices": inventory}, {}
        speaker.Voice = selected
        speaker.Rate = 0
        speaker.Volume = 100
        metadata = {"status": "passed", "voice": str(selected.GetDescription()),
                    "language": str(selected.GetAttribute("Language")), "voices": inventory,
                    "output": "SAPI.SpFileStream only; no speaker output", "format_type": 18}
        generated = {}
        for name, text, mode, expected in _SPEECH_CASES:
            path = directory / (name + ".wav")
            if path.exists():
                raise FileExistsError("Refusing to replace generated WAV")
            stream = Dispatch("SAPI.SpFileStream")
            fmt = Dispatch("SAPI.SpAudioFormat")
            fmt.Type = 18  # SAFT16kHz16BitMono
            stream.Format = fmt
            stream.Open(str(path), 3, False)
            try:
                # Never call Speak before redirecting the output to the file.
                speaker.AudioOutputStream = stream
                before = time.perf_counter()
                speaker.Speak(text, 0)
                seconds = time.perf_counter() - before
            finally:
                stream.Close()
            generated[name] = {"path": path, "source_text": text, "synthesis_wall_seconds": seconds}
        return metadata, generated
    finally:
        selected = token = voices = speaker = stream = fmt = None
        pythoncom.CoUninitialize()


def _noise_file(path, kind):
    rate = 16000
    rng = random.Random(5349)
    values = array.array("h")
    for index in range(rate * 3):
        if kind == "white_noise":
            value = rng.randint(-2000, 2000)
        elif kind == "tone":
            value = round(2000 * math.sin(2 * math.pi * 440 * index / rate))
        else:
            value = 0
        values.append(value)
    if sys.byteorder != "little":
        values.byteswap()
    with path.open("xb") as file:
        with wave.open(file, "wb") as stream:
            stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            stream.writeframes(values.tobytes())


def _speech_measurements(config, directory):
    root = Path(config.get("_resource_root", Path(__file__).resolve().parents[1]))
    configured = Path(config.get("voice", {}).get("model_path", "models/ru_vosk"))
    path = configured if configured.is_absolute() else root / configured
    report = {"model": {"status": "failed", "path": str(path)}, "cases": [],
              "sapi": {"status": "untested"}, "passed": False,
              "expected_case_count": len(_SPEECH_CASES) + len(_NOISE_CASES) * 2}
    before = time.perf_counter()
    try:
        owner = VoskModel(path)
        model = owner.load()
    except Exception as exc:
        report["model"].update(error_type=type(exc).__name__, load_wall_seconds=time.perf_counter() - before)
        return report
    report["model"].update(status="passed", load_wall_seconds=time.perf_counter() - before,
                           cold_load_definition="First native load in a fresh spawned process; OS file cache uncontrolled",
                           pid=os.getpid(), thread_id=threading.get_ident())
    before = time.perf_counter()
    report["model"]["cached_same_instance"] = owner.load() is model
    report["model"]["cached_load_wall_seconds"] = time.perf_counter() - before
    # Hash AFTER load, so inventory does not pre-warm the first-load measurement.
    report["model"]["receipt"] = _model_receipt(path)
    try:
        report["sapi"], files = _sapi_files(directory)
    except Exception as exc:
        report["sapi"] = {"status": "failed", "error_type": type(exc).__name__}
        files = {}
    confidence = float(config.get("voice", {}).get("min_confidence", .65))
    for name, text, mode, expected in _SPEECH_CASES:
        if name not in files:
            continue
        generated = files[name]
        started = time.perf_counter()
        adapter = VoskSTT(model, 16000) if mode == "stt" else VoskWakeWord(model, 16000)
        setup_seconds = time.perf_counter() - started
        case = recognize_wav(generated["path"], adapter, min_confidence=confidence,
                             expected_text=expected if mode == "stt" else ("сириус" if expected else None),
                             expected_wake=expected if mode == "wake" else None)
        case.update(id=name, mode=mode, source="SAPI-generated test audio", source_text=text,
                    recognizer_setup_wall_seconds=setup_seconds,
                    synthesis_wall_seconds=generated["synthesis_wall_seconds"])
        report["cases"].append(case)
    for kind in _NOISE_CASES:
        noise = directory / (kind + ".wav")
        _noise_file(noise, kind)
        for mode in ("wake", "stt"):
            started = time.perf_counter()
            adapter = VoskWakeWord(model, 16000) if mode == "wake" else VoskSTT(model, 16000)
            setup_seconds = time.perf_counter() - started
            case = recognize_wav(noise, adapter, expected_wake=False if mode == "wake" else None,
                                 expected_text="" if mode == "stt" else None)
            case.update(id=kind + "_" + mode, mode=mode, source="Deterministic synthetic signal; not microphone audio",
                        random_seed=5349 if kind == "white_noise" else None,
                        recognizer_setup_wall_seconds=setup_seconds)
            report["cases"].append(case)
    report["observed_case_count"] = len(report["cases"])
    report["passed_case_count"] = sum(case["passed"] for case in report["cases"])
    report["passed"] = (report["observed_case_count"] == report["expected_case_count"] and
                        report["passed_case_count"] == report["expected_case_count"] and
                        report["model"]["cached_same_instance"])
    return report


def _speech_worker(config, directory, result_queue):
    try:
        result_queue.put(_speech_measurements(config, Path(directory)))
    except Exception as exc:
        result_queue.put({"passed": False, "error_type": type(exc).__name__, "cases": [],
                          "model": {"status": "unknown"}, "sapi": {"status": "unknown"}})


def probe_hotkey():
    """Register only Alt+M, verify exclusion and release; never inject a key."""
    if os.name != "nt":
        return {"passed": False, "status": "unsupported", "reason": "Windows required"}
    import ctypes

    records = queue.Queue()
    errors = queue.Queue()
    fired = queue.Queue()

    class ObservedAPI(Win32HotkeyAPI):
        def register(self, modifiers, key):
            ctypes.set_last_error(0)
            result = super().register(modifiers, key)
            records.put({"operation": "register", "thread_id": threading.get_ident(),
                         "result": result, "winerror": 0 if result else ctypes.get_last_error(),
                         "modifiers": modifiers, "key": key})
            return result
        def unregister(self):
            ctypes.set_last_error(0)
            result = super().unregister()
            records.put({"operation": "unregister", "thread_id": threading.get_ident(),
                         "result": result, "winerror": 0 if result else ctypes.get_last_error()})
            return result

    def instance():
        return GlobalHotkey(lambda: fired.put(True), modifiers=1, key=77,
                            api_factory=ObservedAPI, on_error=errors.put)

    holder, contender, reacquire = instance(), instance(), instance()
    initial = collision = repeated = False
    started = time.perf_counter()
    try:
        holder.start()
        initial = holder.wait_ready(2) and holder.registered
        if initial:
            contender.start()
            collision = contender.wait_ready(2) and not contender.registered
            contender.stop()
            holder.stop()
            reacquire.start()
            repeated = reacquire.wait_ready(2) and reacquire.registered
    finally:
        contender.stop()
        holder.stop()
        reacquire.stop()
    rows = []
    while not records.empty():
        rows.append(records.get_nowait())
    messages = []
    while not errors.empty():
        messages.append(errors.get_nowait())
    registrations = [row for row in rows if row["operation"] == "register" and row["result"]]
    releases = [row for row in rows if row["operation"] == "unregister" and row["result"]]
    released = len(registrations) == len(releases) and not any(item.running for item in (holder, contender, reacquire))
    exclusion_confirmed = collision and any(row.get("winerror") == 1409 for row in rows)
    passed = initial and exclusion_confirmed and repeated and released
    return {"passed": passed, "status": "passed" if passed else ("unsupported" if not initial else "failed"),
            "combination": "Alt+M", "registered": initial,
            "collision_rejected": exclusion_confirmed, "reacquired_after_release": repeated,
            "released": released, "records": rows, "messages": messages,
            "wall_seconds": time.perf_counter() - started,
            "global_keys_injected": 0, "physical_press": "untested",
            "external_press_callbacks_observed": fired.qsize()}


def run_probe(config, output_dir):
    """Return and persist actual source/frozen measurements (bounded to 120s).

    Only the supplied output directory is written. This does not instantiate
    VoiceService, AudioInput, UI, Engine, or a sound output stream. A spawned
    process provides finite cleanup for native Vosk/SAPI calls and a cold model.
    """
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_directory = output / ("generated-" + uuid.uuid4().hex)
    run_directory.mkdir()
    started = time.perf_counter()
    report = {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "passed": False, "scope": "Generated-file offline recognition and native hotkey registration only",
        "runtime": {"frozen": bool(getattr(sys, "frozen", False)), "python": sys.version,
                    "executable": sys.executable, "platform": platform.platform(),
                    "resource_root": str(config.get("_resource_root", "")), "versions": {}},
        "privacy": {"microphone_opened": False, "audio_played": False,
                    "network_requested": False, "raw_microphone_audio_saved": False,
                    "generated_audio_saved": True, "global_keys_injected": 0},
        "hardware": {"microphone_capture": "untested", "spoken_wake": "untested",
                     "speaker_playback": "untested", "physical_alt_m": "untested"},
        "latency_definitions": {
            "model_load": "First load in spawned worker, measured separately from synthesis/recognition; filesystem cache not controlled",
            "decoder_wall": "Actual CPU/wall elapsed feeding prerecorded PCM faster than realtime, excludes model and recognizer creation",
            "endpoint_audio": "Audio sample offset of streaming final minus last recognized word end; includes trailing silence and 50ms chunk quantization",
            "live_endpoint_wall": "Not measured: no live microphone or realtime pacing",
            "wake_confirmation": "Wall time of on-candidate full-vocabulary verification, included in decoder_wall; separate from sample-clock endpoint delay",
            "routing_execution": "Not measured: no commands dispatched by this voice probe"},
        "artifacts_directory": str(run_directory),
    }
    for package in ("vosk", "sounddevice", "pywin32"):
        try:
            report["runtime"]["versions"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["runtime"]["versions"][package] = None
    try:
        devices = enumerate_inputs()
        report["device_inventory"] = {"status": "passed", "count": len(devices), "inputs": devices,
                                      "opened": False}
    except Exception as exc:
        report["device_inventory"] = {"status": "unsupported", "error_type": type(exc).__name__, "opened": False}
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    worker = context.Process(target=_speech_worker, args=(config, str(run_directory), result_queue),
                             name="SiriusVoiceProbe")
    terminated = False
    try:
        worker.start()
        try:
            report["speech"] = result_queue.get(timeout=120)
        except queue.Empty:
            report["speech"] = {"passed": False, "status": "timeout", "cases": []}
        worker.join(5)
    finally:
        if worker.is_alive():
            terminated = True
            worker.terminate()
            worker.join(5)
        report["speech_worker"] = {"pid": worker.pid, "released": not worker.is_alive(),
                                   "exitcode": worker.exitcode, "terminated": terminated,
                                   "timeout_seconds": 120, "caller_pid": os.getpid()}
        result_queue.close()
        result_queue.join_thread()
        if not worker.is_alive():
            worker.close()
    report["hotkey"] = probe_hotkey()
    report["passed"] = (report["speech"].get("passed", False) and report["hotkey"]["passed"] and
                        report["speech_worker"]["released"] and not terminated and
                        report["speech_worker"]["exitcode"] == 0)
    report["total_wall_seconds"] = time.perf_counter() - started
    report["report_path"] = str(output / "VOICE_TESTS.json")
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = output / (".voice-report-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, output / "VOICE_TESTS.json")
        # Keep a per-run receipt so a later run cannot erase an earlier failure.
        with (run_directory / "VOICE_TESTS.json").open("x", encoding="utf-8") as file:
            file.write(text)
    finally:
        temporary.unlink(missing_ok=True)
    if json.loads((output / "VOICE_TESTS.json").read_text(encoding="utf-8")) != report:
        raise OSError("Voice report readback mismatch")
    return report

def diagnostic_vosk(config):
    from voice.stt import VoskModel, VoskSTT
    from core.config import resource_root
    path = Path(config.get('_resource_root', resource_root())) / config['voice']['model_path']
    return VoskSTT(VoskModel(path).load(), 16000)


def analyze_speech_file(path, decoder):
    """Replay the recording through the same resampler, VAD and ASR as the live service."""
    import wave
    import math
    import numpy as np
    from voice.audio_input import PCM16Converter
    from voice.normalization import normalize_command

    path = Path(path)
    started = time.perf_counter()
    with wave.open(str(path), 'rb') as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        if wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE' or not 1 <= channels <= 8:
            raise ValueError('Ожидается несжатый PCM16 WAV.')
        if wav.getnframes() > rate * 120:
            raise ValueError('Максимальная длина диагностической записи — 120 секунд.')
        original = wav.readframes(wav.getnframes())
    raw = np.frombuffer(original, '<i2').astype(np.float64)
    def level(samples):
        if not len(samples):
            return None
        rms = np.sqrt(np.mean(np.square(samples, dtype=np.float64))) / 32768
        return round(20 * math.log10(rms), 1) if rms else None
    channel_levels = [level(raw[index::channels]) for index in range(channels)]
    pcm = PCM16Converter(rate, channels).convert(original, final=True)
    decoder.reset()
    segments = []
    def append_segment(data, bounds):
        decoder.decode(data)
        begin, end = bounds
        segments.append(dict(decoder.last, start_s=round(begin/16000, 3), end_s=round(end/16000, 3),
                             command=normalize_command(decoder.last['text'])))
    if hasattr(decoder, 'vad'):
        vad_started = time.perf_counter()
        chunks = []
        for i in range(0, len(pcm), 1600):
            for data in decoder.vad.feed(pcm[i:i+1600]):
                chunks.append((decoder.vad.bounds, data))
        for data in decoder.vad.finish():
            chunks.append((decoder.vad.bounds, data))
        vad_ms = round(1000 * (time.perf_counter() - vad_started), 1)
        for bounds, data in chunks:
            append_segment(data, bounds)
    else:
        vad_ms = 0.
        def collect(result):
            if result and result.words:
                segments.append(dict(text=result.text, confidence=result.confidence,
                                     start_s=result.words[0].start, end_s=result.words[-1].end,
                                     decode_ms=round((time.perf_counter()-started)*1000, 1),
                                     command=normalize_command(result.text)))
        for i in range(0, len(pcm), 1600):
            collect(decoder.feed(pcm[i:i+1600]))
        collect(decoder.finish())
    return dict(wav=str(path.resolve()), duration_s=round(len(raw)/channels/rate, 3), input_rate=rate,
                input_channels=channels, stt_rate=16000, stt_channels=1,
                rms_dbfs=level(raw), channel_rms_dbfs=channel_levels,
                mono_rms_dbfs=level(np.frombuffer(pcm, '<i2')),
                peak_pcm=int(np.max(np.abs(raw))) if len(raw) else 0,
                clipped_samples=int(np.count_nonzero(np.abs(raw) >= 32767)),
                text=' '.join(seg['text'] for seg in segments), segments=segments,
                vad_compute_ms=vad_ms, endpoint_silence_ms=800 if hasattr(decoder, "vad") else None,
                processing_ms=round(1000*(time.perf_counter()-started), 1))

