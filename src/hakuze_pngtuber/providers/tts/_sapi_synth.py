"""Standalone SAPI synthesis runner (subprocess isolation).

pyttsx3/SAPI keeps process-global COM state: re-initializing the engine
after voice/model changes, or driving one engine repeatedly, can make
runAndWait() hang forever. If that happens inside the assistant worker
thread, EVERY AI button stops responding (they all just enqueue work to
that thread). Running synthesis in a throwaway subprocess makes hangs
killable (timeout + kill) and COM state impossible to accumulate.

Usage (dev / from source):
    python -m hakuze_pngtuber.providers.tts._sapi_synth voices
    python -m hakuze_pngtuber.providers.tts._sapi_synth synth \
        --text "halo" --voice "Microsoft Zira" --rate 0 --volume 1.0 \
        --out C:\\temp\\out.wav

Usage (frozen exe, dispatched from hakuze_pngtuber.main):
    HakuzePNGtuber.exe --sapi-voices
    HakuzePNGtuber.exe --sapi-synth --text ... --voice ... --out file.wav

stdout: for `voices` a JSON array of voice names; for `synth` nothing.
Exit codes: 0 ok, 2 usage error, 3 TTS failure, 4 output missing/empty.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr)
    return code


def run_voices() -> int:
    try:
        import pyttsx3  # noqa: PLC0415 - Windows-only, lazy
    except Exception as exc:  # noqa: BLE001
        return _fail(3, f"pyttsx3 unavailable: {exc}")
    try:
        engine = pyttsx3.init()
        names = [v.name for v in engine.getProperty("voices")]
        print(json.dumps(names))
        return 0
    except Exception as exc:  # noqa: BLE001
        return _fail(3, f"voice enumeration failed: {exc}")


def run_synth(argv: list[str]) -> int:
    text = ""
    voice = ""
    rate = "0"
    volume = "1.0"
    out = ""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--text" and i + 1 < len(argv):
            text = argv[i + 1]; i += 2; continue
        if arg == "--voice" and i + 1 < len(argv):
            voice = argv[i + 1]; i += 2; continue
        if arg == "--rate" and i + 1 < len(argv):
            rate = argv[i + 1]; i += 2; continue
        if arg == "--volume" and i + 1 < len(argv):
            volume = argv[i + 1]; i += 2; continue
        if arg == "--out" and i + 1 < len(argv):
            out = argv[i + 1]; i += 2; continue
        i += 1
    if not text or not out:
        return _fail(2, "usage: synth --text TEXT --out FILE [--voice NAME] "
                        "[--rate N] [--volume V]")
    try:
        import pyttsx3  # noqa: PLC0415 - Windows-only, lazy
    except Exception as exc:  # noqa: BLE001
        return _fail(3, f"pyttsx3 unavailable: {exc}")
    try:
        engine = pyttsx3.init()
        base_rate = engine.getProperty("rate") or 200
        if voice:
            for v in engine.getProperty("voices"):
                if v.name == voice:
                    engine.setProperty("voice", v.id)
                    break
        try:
            engine.setProperty("rate", int(base_rate * float(rate or "1.0")))
        except ValueError:
            pass
        try:
            engine.setProperty("volume", max(0.0, min(1.0, float(volume))))
        except ValueError:
            pass
        engine.save_to_file(text, out)
        engine.runAndWait()
        path = Path(out)
        if not path.exists() or path.stat().st_size == 0:
            return _fail(4, "no audio produced")
        return 0
    except Exception as exc:  # noqa: BLE001
        return _fail(3, f"synthesis failed: {exc}")


def main() -> int:
    if len(sys.argv) < 2:
        return _fail(2, "usage: _sapi_synth voices|synth ...")
    mode = sys.argv[1]
    if mode == "voices":
        return run_voices()
    if mode == "synth":
        return run_synth(sys.argv[2:])
    return _fail(2, f"unknown mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
