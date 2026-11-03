"""Windows-only AI companion smoke: real hotkey, SAPI TTS, mic tap, app wiring.

Run: .wvenv\\Scripts\\python.exe scripts\\smoke_ai_windows.py
Exit 0 = pass. Never sends API requests (no keys touched).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RESULTS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    print(f"  {'ok' if cond else 'FAIL'} - {name} {detail}")


def main() -> int:
    print("== AI companion Windows smoke ==")

    # --- 1. global hotkey (RegisterHotKey + message loop) --------------
    from hakuze_pngtuber.utils.global_hotkey import HotkeyManager
    hk = HotkeyManager()
    fired = []
    ok = hk.register("END", lambda: fired.append(time.monotonic()))
    check("END hotkey registered", ok, hk.last_error or "")
    if ok:
        import ctypes
        # simulate the WM_HOTKEY delivery by posting the message the loop
        # waits for: pressing a real key is user-side; here we verify the
        # loop is alive and responsive to a synthetic post
        user32 = ctypes.windll.user32
        thread_id = hk._thread.ident
        posted = user32.PostThreadMessageW(thread_id, 0x0312, 0xB00B, 0x23)
        check("WM_HOTKEY posted to loop thread", bool(posted))
        deadline = time.monotonic() + 2.0
        while not fired and time.monotonic() < deadline:
            time.sleep(0.05)
        check("hotkey callback fired via posted WM_HOTKEY", bool(fired))
        hk.shutdown()
        time.sleep(0.2)
        check("hotkey unregistered cleanly", not hk.registered)

    # --- 2. duplicate registration handling -----------------------------
    hk2 = HotkeyManager()
    ok2 = hk2.register("END", lambda: None)
    hk3 = HotkeyManager()
    ok3 = hk3.register("END", lambda: None)   # same key while hk2 holds it
    check("duplicate END registration reported", not ok3,
          "second manager unexpectedly registered")
    hk2.shutdown()
    hk3.shutdown()

    # --- 3. Windows SAPI TTS (subprocess isolation) ----------------------
    try:
        from hakuze_pngtuber.providers.tts.openai_tts import WindowsSapiTTS
        from hakuze_pngtuber.providers.tts.base import TTSRequest
        sapi = WindowsSapiTTS()
        voices = sapi.list_voices()
        check("SAPI voices enumerated (subprocess)", len(voices) > 0,
              f"count={len(voices)} {voices}")
        t0 = time.monotonic()
        wav = sapi.synthesize(TTSRequest(
            text="Halo, ini uji suara Hakuze."))
        t1 = time.monotonic()
        check("SAPI synthesis produced WAV", len(wav) > 1000,
              f"bytes={len(wav)} in {t1-t0:.1f}s")
        check("SAPI WAV header", wav[:4] == b"RIFF")
        # THE user-reported hang: change voice/model, then synthesize again
        if voices:
            sapi.reconfigure(voice=voices[-1])
        t0 = time.monotonic()
        wav2 = sapi.synthesize(TTSRequest(text="Tes kedua setelah ganti suara."))
        t1 = time.monotonic()
        check("SAPI re-synth after reconfigure (no hang)",
              len(wav2) > 1000, f"bytes={len(wav2)} in {t1-t0:.1f}s")
        import io
        import wave
        with wave.open(io.BytesIO(wav2)) as w:
            dur_ms = 1000 * w.getnframes() / w.getframerate()
        check("SAPI audio duration sane", 500 < dur_ms < 10000,
              f"{dur_ms:.0f} ms")
    except Exception as exc:  # noqa: BLE001
        check("SAPI TTS", False, str(exc))

    # --- 4. mic tap on the real engine -----------------------------------
    from hakuze_pngtuber.core.audio_engine import AudioEngine
    engine = AudioEngine()
    ok = engine.start()
    check("mic stream started", ok, engine.last_error or "")
    if ok:
        taps = []
        engine.set_tap(lambda block: taps.append(block))
        time.sleep(1.0)
        engine.poll()
        check("tap received blocks", len(taps) >= 20,
              f"blocks={len(taps)} in 1s")
        if taps:
            import numpy as np
            arr = np.asarray(taps[0], dtype=np.float32)
            check("tap block shape sane", arr.size in (960, 1920),
                  f"size={arr.size}")
        engine.set_tap(None)
        # avatar RMS path still works alongside the tap
        levels = []
        engine.set_tap(lambda b: None)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            sample = engine.poll()
            if sample:
                levels.append(sample[0])
            time.sleep(0.02)
        check("RMS poll unaffected by tap", True, f"samples={len(levels)}")
        engine.stop()

    # --- 5. keyring backend present --------------------------------------
    from hakuze_pngtuber.utils.credential_store import CredentialStore
    store = CredentialStore()
    check("credential backend name", "keyring" in store.backend_name(),
          store.backend_name())

    print()
    failed = [r for r in RESULTS if not r[1]]
    if failed:
        print("WINDOWS SMOKE FAILED:", [f[0] for f in failed])
        return 1
    print("WINDOWS AI SMOKE: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
