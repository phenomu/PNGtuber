"""Real-time microphone engine built on sounddevice + NumPy.

The PortAudio callback must stay lightweight: it computes RMS only and pushes
a tiny (level, timestamp) tuple into a queue. All further processing happens
on the GUI thread via poll(). Device switching without restart is supported:
the stream is closed and reopened against the new device index.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import numpy as np

try:
    import sounddevice as _sd
    _SD_IMPORT_ERROR = None
except ImportError as _exc:  # allows importing the module for tests without audio stack
    _sd = None
    _SD_IMPORT_ERROR = f"sounddevice not installed: {_exc}"
except OSError as _exc:  # PortAudio shared library missing (headless WSL test env)
    _sd = None
    _SD_IMPORT_ERROR = f"audio backend unavailable: {_exc}"

from ..utils.audio_utils import block_rms

SAMPLE_RATE = 48000
BLOCK_MS = 20.0
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_MS / 1000.0)  # 960 frames


class AudioEngineError(Exception):
    pass


class AudioEngine:
    """Owns the input stream and a thread-safe level queue."""

    def __level_callback(self, indata, frames, time_info, status):
        level = block_rms(indata)
        try:
            self._q.put_nowait((level, time.monotonic() * 1000.0))
        except queue.Full:
            pass  # GUI is slow; drop the oldest-style policy: keep latest below

    def __init__(self, device_index: int | None = None, paused: bool = False):
        self._stream = None
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._lock = threading.Lock()
        self.device_index = device_index
        self._paused = paused
        self.running = False
        self.last_error: str | None = None
        self.error_callback: Callable[[str], None] | None = None
        self._callback = self.__level_callback
        self._overflow_count = 0

    # ------------------------------------------------------------------
    @staticmethod
    def available() -> bool:
        return _sd is not None and _SD_IMPORT_ERROR is None

    @staticmethod
    def list_devices() -> list[dict]:
        """Enumerate input devices as dicts (index, name, channels)."""
        if _sd is None:
            return []
        try:
            devices = _sd.query_devices()
        except Exception:
            return []
        out = []
        for i, dev in enumerate(devices):
            try:
                if dev.get("max_input_channels", 0) > 0:
                    out.append({
                        "index": i,
                        "name": dev.get("name", f"Device {i}"),
                        "channels": dev.get("max_input_channels", 0),
                    })
            except Exception:
                continue
        return out

    @staticmethod
    def default_input_index() -> int | None:
        if _sd is None:
            return None
        try:
            return _sd.default.device[0] or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    def start(self, device_index: int | None = None) -> bool:
        """Open the input stream. Returns True on success."""
        if _sd is None:
            self.last_error = _SD_IMPORT_ERROR or "sounddevice not available"
            return False
        with self._lock:
            if self._stream is not None:
                return True
            if device_index is not None:
                self.device_index = device_index
            try:
                self._stream = _sd.InputStream(
                    device=self.device_index,
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    blocksize=BLOCK_SIZE,
                    dtype="float32",
                    callback=self._callback,
                )
                self._stream.start()
                self.running = True
                self.last_error = None
                return True
            except Exception as exc:  # noqa: BLE001 - surfaced to UI
                self._stream = None
                self.running = False
                self.last_error = str(exc)
                self._notify_error(f"Microphone error: {exc}")
                return False

    def switch_device(self, device_index: int | None) -> bool:
        """Change mic without restarting the app."""
        with self._lock:
            self.stop_locked()
        return self.start(device_index)

    def stop(self) -> None:
        with self._lock:
            self.stop_locked()

    def stop_locked(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.running = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self.stop()
        elif not self.running:
            self.start()

    @property
    def paused(self) -> bool:
        return self._paused

    def poll(self) -> tuple[float, float] | None:
        """Drain the queue; returns the newest (level, t_ms) or None."""
        latest = None
        try:
            while True:
                latest = self._q.get_nowait()
        except queue.Empty:
            pass
        return latest

    def _notify_error(self, message: str) -> None:
        self.last_error = message
        if self.error_callback:
            try:
                self.error_callback(message)
            except Exception:
                pass
