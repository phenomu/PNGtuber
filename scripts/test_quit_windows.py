"""Verify the tray-quit path actually terminates the process.

Run on Windows:
    .wvenv/Scripts/python.exe scripts/test_quit_windows.py
It builds the same object graph as main.py, emits really_quit_requested
(the tray Quit path), and asserts QApplication exits (process returns).
Exit code 0 = quit works.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INNER = textwrap.dedent("""
    import sys, tempfile, time
    from pathlib import Path
    sys.path.insert(0, r"{root}\\src")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from hakuze_pngtuber.core.settings_manager import SettingsManager
    from hakuze_pngtuber.core.asset_manager import AssetManager
    from hakuze_pngtuber.core.avatar_controller import AvatarController
    from hakuze_pngtuber.core.audio_engine import AudioEngine
    from hakuze_pngtuber.ui.settings_window import SettingsWindow

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    tmp = Path(tempfile.mkdtemp()) / "s.json"
    settings = SettingsManager(user_path=tmp)
    assets = AssetManager(settings)
    ctrl = AvatarController(assets=assets)
    engine = AudioEngine()
    win = SettingsWindow(settings, ctrl, engine, assets)
    win.show()

    tray = QSystemTrayIcon(app)
    tray.show()

    def _full_quit():
        win._poll.stop()
        engine.stop()
        if win._overlay is not None:
            win._overlay.stop()
        settings.save()
        tray.hide()
        QApplication.quit()

    win.really_quit_requested.connect(_full_quit)

    # simulate: user clicks tray Quit after 800ms
    QTimer.singleShot(800, win.really_quit_requested.emit)
    # safety: if quit is broken, force-fail at 4s
    QTimer.singleShot(4000, lambda: (print("QUIT FAILED - still alive"),
                                     app.exit(3)))
    rc = app.exec()
    print("event loop exited, rc =", rc)
    sys.exit(0 if rc == 0 else 3)
""").format(root=str(ROOT))

inner_path = ROOT / "scripts" / "_quit_inner.py"
inner_path.write_text(INNER, encoding="utf-8")

venv_py = ROOT / ".wvenv" / "Scripts" / "python.exe"
proc = subprocess.run([str(venv_py), str(inner_path)],
                      capture_output=True, text=True, timeout=60)
print(proc.stdout.strip())
if proc.returncode != 0:
    print("STDERR:", proc.stderr[-800:])
inner_path.unlink()
print("TRAY QUIT TEST:", "OK" if proc.returncode == 0 else "FAILED")
sys.exit(proc.returncode)
