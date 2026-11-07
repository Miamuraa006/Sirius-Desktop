"""Opt-in REAL SAPI-to-file + Vosk + native Alt+M (never injects keys).

Run only explicitly: SIRIUS_TEST_GENERATED_VOICE=1 python -m pytest
 tests/test_voice_real.py -q. This opens no microphone or speakers.
"""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt" or os.environ.get("SIRIUS_TEST_GENERATED_VOICE") != "1",
                    reason="Explicit generated-audio/native-hotkey opt-in required; no live capture")
def test_real_generated_stt_wake_and_hotkey(tmp_path):
    from voice.probe import run_probe

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config/defaults.json").read_text(encoding="utf-8"))
    config["_resource_root"] = str(root)
    report = run_probe(config, tmp_path)
    failed = [{"id": row["id"], "expected": row["expected_text"], "observed": row["observed_text"],
               "expected_wake": row["expected_wake"], "wake": row["wake_accepted"]}
              for row in report["speech"].get("cases", []) if not row["passed"]]
    assert report["passed"], {"failed_cases": failed, "speech": report["speech"].get("model"),
                              "hotkey": report["hotkey"], "report_path": report["report_path"]}
    assert report["speech"]["observed_case_count"] == report["speech"]["expected_case_count"]
    assert report["speech_worker"]["released"]
    assert report["privacy"]["microphone_opened"] is False
    assert report["privacy"]["audio_played"] is False
