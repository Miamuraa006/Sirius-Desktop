"""Run Sirius' actual offline voice probe without starting the GUI or mic.

Source: .venv/Scripts/python.exe scripts/voice_probe.py --output DIR
Frozen: Sirius.exe --voice-probe DIR --report REPORT.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description="SAPI-generated WAV → real Vosk; no microphone or playback")
    parser.add_argument("--output", type=Path, required=True, help="Generated WAVs and VOICE_TESTS.json directory")
    parser.add_argument("--report", type=Path, help="Optional second JSON report destination")
    parser.add_argument("--model", type=Path, help="Explicit installed model path (never downloads)")
    args = parser.parse_args(argv)
    from voice.probe import run_probe

    # Read defaults only: diagnostics must not change the user's saved settings.
    config = json.loads((ROOT / "config" / "defaults.json").read_text(encoding="utf-8"))
    config["_resource_root"] = str(ROOT)
    if args.model is not None:
        config["voice"]["model_path"] = str(args.model.resolve())
    report = run_probe(config, args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        if json.loads(args.report.read_text(encoding="utf-8")) != report:
            raise OSError("Probe report readback mismatch")
    if sys.stdout is not None:
        print(json.dumps({"passed": report["passed"], "report_path": report["report_path"],
                          "speech_passed": report["speech"].get("passed", False),
                          "hotkey_status": report["hotkey"]["status"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
