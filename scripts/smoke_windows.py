"""Windows smoke test: audio engine, mic enumeration, full app wiring.

Run inside .wvenv on Windows:
    python scripts/smoke_windows.py
Quits by itself; exit code 0 = OK.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def check_audio() -> int:
    from hakuze_pngtuber.core.audio_engine import AudioEngine

    print("[audio] sounddevice available:", AudioEngine.available())
    devices = AudioEngine.list_devices()
    print(f"[audio] {len(devices)} input device(s):")
    for d in devices:
        print(f"        - {d['index']}: {d['name']}")
    default = AudioEngine.default_input_index()
    print("[audio] default input index:", default)

    engine = AudioEngine()
    ok = engine.start(default)
    print("[audio] stream started:", ok, "| error:", engine.last_error)
    if not ok:
        return 1

    levels = []
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        sample = engine.poll()
        if sample is not None:
            levels.append(sample[0])
        time.sleep(0.02)
    engine.stop()
    print(f"[audio] {len(levels)} blocks received; "
          f"max RMS {max(levels) if levels else 0.0:.4f}")
    return 0


def check_app() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from hakuze_pngtuber.core.asset_manager import AssetManager
    from hakuze_pngtuber.core.audio_engine import AudioEngine
    from hakuze_pngtuber.core.avatar_controller import AvatarController
    from hakuze_pngtuber.core.settings_manager import SettingsManager
    from hakuze_pngtuber.ui.settings_window import SettingsWindow
    import tempfile

    app = QApplication(sys.argv)
    tmp_settings = Path(tempfile.mkdtemp()) / "settings.json"
    settings = SettingsManager(user_path=tmp_settings)
    assets = AssetManager(settings)
    ctrl = AvatarController(assets=assets)
    engine = AudioEngine()
    win = SettingsWindow(settings, ctrl, engine, assets)
    win.start_audio()
    print("[app] engine running:", engine.running,
          "| error:", engine.last_error)
    print("[app] settings window constructed OK")

    ov = win._ensure_overlay()
    win._start_overlay()
    ov.set_state(True)
    ov.set_state(False)
    t0 = time.monotonic() * 1000.0
    for i in range(80):  # 1.6s of synthetic speech then silence
        ctrl.feed_level(0.09 if i < 40 else 0.0, t0 + i * 20)
    print("[app] controller state after synthetic audio:", ctrl.state)
    print("[app] overlay visible:", ov.isVisible())

    QTimer.singleShot(1500, app.quit)
    app.exec()
    print("[app] event loop ran, quitting cleanly")
    return 0


if __name__ == "__main__":
    rc = check_audio()
    rc += check_app()
    print("SMOKE RESULT:", "OK" if rc == 0 else "FAILED")
    sys.exit(rc)
