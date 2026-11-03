"""Persistent application settings with validation and safe defaults."""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from ..utils.platform_utils import default_settings_path


def _deep_merge(base: dict, override: Mapping) -> dict:
    out = dict(base)
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, Mapping):
            out[key] = _deep_merge(base[key], value)
        else:
            out[key] = value
    return out


class SettingsError(Exception):
    pass


class SettingsManager:
    """Loads bundled defaults, deep-merges the user file, validates values.

    Save is atomic (temp file + os.replace) so a crash never corrupts settings.
    """

    _RANGES: dict[str, tuple[float, float]] = {
        "scale": (0.05, 2.0),
        "pos_x": (-10000.0, 10000.0),
        "pos_y": (-10000.0, 10000.0),
        "grayscale_intensity": (0.0, 1.0),
        "sensitivity": (0.0, 1.0),
        "rms_threshold": (0.0005, 1.0),
        "noise_gate": (0.0, 1.0),
        "attack_ms": (1.0, 2000.0),
        "release_ms": (1.0, 2000.0),
        "min_speech_ms": (0.0, 5000.0),
        "silence_ms": (1.0, 5000.0),
        "talking_lift_px": (0.0, 200.0),
        "bounce_px": (0.0, 200.0),
        "duration_ms": (30.0, 1000.0),
        "speed": (0.25, 4.0),
        "breath_amplitude_px": (0.0, 50.0),
        "breath_period_ms": (500.0, 20000.0),
        "sustain_bob_px": (0.0, 20.0),
        "sustain_bob_period_ms": (300.0, 10000.0),
        # assistant (section "ai") — key names unique across sections
        "wake_sensitivity": (0.05, 1.0),
        "mic_gain": (0.25, 8.0),
        "llm_temperature": (0.0, 2.0),
        "llm_max_tokens": (16.0, 4096.0),
        "llm_timeout_s": (5.0, 300.0),
        "stt_timeout_s": (5.0, 120.0),
        "tts_speed": (0.25, 4.0),
        "tts_volume": (0.0, 1.0),
        "bubble_width": (200.0, 900.0),
        "bubble_max_lines": (1.0, 30.0),
        "bubble_font_size": (9.0, 32.0),
        "bubble_typewriter_ms": (0.0, 200.0),
        "bubble_duration_s": (0.0, 60.0),
        "bubble_pos_offset_x": (-2000.0, 2000.0),
        "bubble_pos_offset_y": (-2000.0, 2000.0),
        "bubble_animation_ms": (50.0, 1000.0),
        "bubble_opacity": (0.05, 1.0),
        "history_max_turns": (2.0, 50.0),
    }

    _BOOLEANS = {
        "enabled", "breathing", "always_on_top", "click_through", "show_on_start",
        "edit_mode", "minimize_to_tray", "start_minimized", "start_with_windows",
        # assistant booleans (also valid in other sections if ever added)
        "ai_enabled", "start_on_startup", "llm_streaming", "interrupt_allow",
        "bubble_enabled", "bubble_voice_mode", "history_persistent",
        "history_clear_on_exit", "log_enabled", "persona_emoji", "use_emoji",
    }

    _INTEGERS = {"pos_x", "pos_y", "attack_ms", "release_ms", "min_speech_ms", "silence_ms",
                 "duration_ms", "breath_period_ms", "sustain_bob_period_ms",
                 # assistant integers
                 "llm_max_tokens", "bubble_width", "bubble_max_lines",
                 "bubble_font_size", "bubble_typewriter_ms",
                 "bubble_pos_offset_x", "bubble_pos_offset_y",
                 "bubble_animation_ms", "history_max_turns"}

    def __init__(self, user_path: Path | None = None, defaults_path: Path | None = None):
        self._defaults_path = Path(defaults_path or default_settings_path())
        self._user_path = Path(user_path) if user_path else None
        self._data: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------------
    @property
    def user_path(self) -> Path | None:
        return self._user_path

    def load(self) -> None:
        with self._lock:
            self._defaults = self._read_json(self._defaults_path, fallback={})
            if not self._defaults:
                raise SettingsError(
                    f"Default settings missing or unreadable: {self._defaults_path}"
                )
            user: dict[str, Any] = {}
            if self._user_path is not None:
                user = self._read_json(self._user_path, fallback={})
                if not isinstance(user, dict):
                    user = {}
            self._data = self._validate(_deep_merge(self._defaults, user))

    def save(self) -> None:
        if self._user_path is None:
            return
        with self._lock:
            self._user_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._user_path.parent), suffix=".tmp", prefix="settings_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, indent=2, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self._user_path)
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

    # ------------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    return default
            return copy.deepcopy(node)

    def set(self, dotted: str, value: Any) -> None:
        with self._lock:
            node = self._data
            parts = dotted.split(".")
            for part in parts[:-1]:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
            node[parts[-1]] = copy.deepcopy(value)

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def reset_to_defaults(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(self._defaults)

    # ------------------------------------------------------------------
    @staticmethod
    def _read_json(path: Path, fallback: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return fallback
        except (json.JSONDecodeError, OSError):
            # A corrupt user file is replaced by defaults on next save
            return fallback

    def _validate(self, data: dict) -> dict:
        out = copy.deepcopy(data)
        for section in list(out.keys()):
            if not isinstance(out[section], dict):
                out.pop(section)
                continue
            for key in list(out[section].keys()):
                value = out[section][key]
                if key in self._RANGES:
                    out[section][key] = self._validate_number(key, value, section)
                elif key in self._BOOLEANS:
                    out[section][key] = self._validate_bool(value)
        # device_index may be int or None
        di = out.get("audio", {}).get("device_index")
        if di is not None:
            try:
                out["audio"]["device_index"] = int(di)
            except (TypeError, ValueError):
                out["audio"]["device_index"] = None
        # string path fields
        for field in ("idle_image", "talking_image"):
            val = out.get("avatar", {}).get(field)
            if val is not None and not isinstance(val, str):
                out["avatar"][field] = ""
        return out

    def _validate_number(self, key: str, value: Any, section: str) -> Any:
        lo, hi = self._RANGES[key]
        default_val = self._defaults.get(section, {}).get(key, lo)
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = default_val
        if math.isnan(v) or math.isinf(v):
            v = default_val
        v = min(hi, max(lo, v))
        if key in self._INTEGERS:
            return int(round(v))
        return v

    @staticmethod
    def _validate_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        return False
