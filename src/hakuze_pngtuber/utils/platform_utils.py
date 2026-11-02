"""Platform helpers: Windows/WSL interop, config dirs, resource paths.

All cross-platform decisions live here so the rest of the code stays clean.
Runs inside WSL during development but targets native Windows at runtime.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "HakuzePNGtuber"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_path(relative: str) -> Path:
    """Resolve bundled resource (assets/config) both in dev and frozen app.

    Dev layout:  <repo>/src/hakuze_pngtuber/platform_utils.py  -> repo root is parents[2].
    Frozen:      PyInstaller puts data under sys._MEIPASS.
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / relative
    # src/hakuze_pngtuber/utils/platform_utils.py -> parents[3] is the repo root
    return Path(__file__).resolve().parents[3] / relative


def config_dir() -> Path:
    """User-writable settings dir. Windows: %APPDATA%; others: XDG config."""
    if is_windows():
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / APP_DIR_NAME
        else:  # APPDATA missing - fall back to user home
            path = Path.home() / "AppData" / "Roaming" / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        path = Path(base) / "hakuze-pngtuber"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_settings_path() -> Path:
    return resource_path("config") / "default_settings.json"


def set_click_through(hwnd: int, enabled: bool) -> bool:
    """Toggle WS_EX_TRANSPARENT on a Win32 window so mouse events pass through.

    Returns True when applied (Windows only); no-op returns False elsewhere.
    """
    if not is_windows() or not hwnd:
        return False
    import ctypes

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        return True
    except Exception:
        return False


def set_windows_startup(enable: bool, executable: str | None = None) -> bool:
    """Register/unregister the app in the Windows 'Run' registry key."""
    if not is_windows():
        return False
    try:
        import winreg
    except ImportError:
        return False
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                target = executable or sys.executable
                winreg.SetValueEx(key, APP_DIR_NAME, 0, winreg.REG_SZ, f'"{target}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_DIR_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
