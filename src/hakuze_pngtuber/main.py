"""Application entry point: wires settings, audio, controller, overlay, tray."""
from __future__ import annotations

import signal
import sys

from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .core.asset_manager import AssetManager
from .core.audio_engine import AudioEngine
from .core.avatar_controller import AvatarController
from .core.settings_manager import SettingsManager
from .ui.settings_window import SettingsWindow
from .utils.platform_utils import config_dir


def _app_icon() -> QIcon:
    # simple generated icon: cyan dot on dark rounded square
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(11, 14, 23, 255))
    p.setPen(QColor(33, 230, 255, 255))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor(185, 107, 255, 255))
    p.drawEllipse(20, 20, 24, 24)
    p.end()
    return QIcon(pm)


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl-C works while Qt loop runs

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray owns the lifetime
    app.setApplicationName("Hakuze PNGtuber")
    app.setApplicationDisplayName("Hakuze PNGtuber")
    icon = _app_icon()
    app.setWindowIcon(icon)

    try:
        settings = SettingsManager(user_path=config_dir() / "settings.json")
    except Exception as exc:  # noqa: BLE001 - fatal, must be readable
        print(f"Fatal: cannot load settings: {exc}", file=sys.stderr)
        return 2

    assets = AssetManager(settings)
    controller = AvatarController(assets=assets)
    engine = AudioEngine()

    win = SettingsWindow(settings, controller, engine, assets)
    win.setWindowIcon(icon)
    win.start_audio()

    # tray ------------------------------------------------------------
    tray = QSystemTrayIcon(icon, app)
    tray_menu = QMenu()
    act_show = QAction("Open settings", tray_menu)
    act_show.triggered.connect(win.showNormal)
    act_quit = QAction("Quit", tray_menu)
    act_quit.triggered.connect(win.really_quit)
    tray_menu.addAction(act_show)
    tray_menu.addSeparator()
    tray_menu.addAction(act_quit)
    tray.setContextMenu(tray_menu)
    tray.setToolTip("Hakuze PNGtuber")
    tray.activated.connect(lambda reason: win.showNormal()
                            if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()

    win.closing_to_tray.connect(lambda: tray.showMessage(
        "Hakuze PNGtuber", "Minimized to tray - double-click to reopen",
        QSystemTrayIcon.Information, 2500))

    def _full_quit() -> None:
        """Tray Quit: stop everything and exit the event loop for real."""
        win._poll.stop()
        engine.stop()
        if win._overlay is not None:
            win._overlay.stop()
        settings.save()
        tray.hide()
        QApplication.quit()

    win.really_quit_requested.connect(_full_quit)

    if not bool(settings.get("app.start_minimized", False)):
        win.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
