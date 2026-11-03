"""Global hotkey manager: RegisterHotKey on Windows, mock elsewhere.

Runs a dedicated thread with a Windows message loop (WM_HOTKEY) so the
hotkey works while Minecraft or any other app has focus. QShortcut cannot
do this — it only sees keys when OUR window has focus.
"""
from __future__ import annotations

import threading

# Virtual-key codes (subset; extend as needed)
VK_CODES: dict[str, int] = {
    "END": 0x23, "HOME": 0x24, "INSERT": 0x2D, "DELETE": 0x2E,
    "PRIOR": 0x21, "NEXT": 0x22, "F1": 0x70, "F2": 0x71, "F3": 0x72,
    "F4": 0x73, "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
}
MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8
MOD_NOREPEAT = 0x4000


class HotkeyManager:
    """Register one global hotkey; fire callback on press.

    `callback()` is invoked from the hotkey thread — Qt callers must marshal
    to the GUI thread themselves (the controller does).
    """

    def __init__(self):
        self._callback = None
        self._id = 0xB00B  # arbitrary hotkey id
        self._registered = False
        self._key = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_error: str | None = None

    @property
    def supported(self) -> bool:
        try:
            import ctypes  # noqa: PLC0415
            return ctypes.windll is not None and threading.current_thread() is not None
        except AttributeError:  # non-Windows
            return False

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ----------------------------------------------------------------
    def register(self, key: str, callback) -> bool:
        """Register `key` (e.g. 'END'). Returns True on success."""
        self.unregister()
        key = (key or "END").strip().upper()
        if key not in VK_CODES:
            self._last_error = f"unsupported hotkey: {key}"
            return False
        if not self.supported:
            self._last_error = "global hotkeys need Windows"
            return False
        import ctypes  # noqa: PLC0415 - Windows only path
        import ctypes.wintypes  # noqa: PLC0415

        user32 = ctypes.windll.user32
        vk = VK_CODES[key]
        self._callback = callback
        self._stop_event.clear()

        def _loop():
            msg = ctypes.wintypes.MSG()
            if not user32.RegisterHotKey(None, self._id,
                                         MOD_NOREPEAT, vk):
                self._last_error = (
                    "hotkey registration failed (already used by another app?)")
                self._registered = False
                return
            self._registered = True
            self._last_error = None
            try:
                while not self._stop_event.is_set():
                    if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) == 0:
                        break
                    if msg.message == 0x0312 and msg.wParam == self._id:
                        if self._callback is not None:
                            try:
                                self._callback()
                            except Exception:  # noqa: BLE001 - callback isolated
                                pass
            finally:
                user32.UnregisterHotKey(None, self._id)
                self._registered = False

        self._thread = threading.Thread(
            target=_loop, name="hakuze-hotkey", daemon=True)
        self._thread.start()
        self._thread.join(0.5)  # let registration result land
        return self._registered

    def unregister(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._stop_event.set()
            try:
                import ctypes  # noqa: PLC0415
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread.ident, 0x0012, 0, 0)  # WM_QUIT
            except Exception:  # noqa: BLE001 - non-Windows/mock
                pass
            self._thread.join(timeout=1.0)
        self._thread = None
        self._registered = False

    def shutdown(self) -> None:
        self.unregister()


class MockHotkeyManager(HotkeyManager):
    """Test double: simulate presses without Windows."""

    def __init__(self):
        super().__init__()
        self.registered_keys: list[str] = []
        self.presses: list[str] = []

    def register(self, key: str, callback) -> bool:
        self.registered_keys.append(key)
        self._callback = callback
        self._registered = True
        self._key = key
        self._last_error = None
        return True

    def unregister(self) -> None:
        self._registered = False

    def press(self, key: str | None = None) -> None:
        """Simulate a global key press (fires callback)."""
        key = (key or self._key or "END").upper()
        self.presses.append(key)
        if self._callback is not None and self._registered:
            self._callback()
