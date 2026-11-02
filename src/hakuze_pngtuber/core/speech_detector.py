"""Microphone activity detector with hysteresis.

Pure logic: consumes scalar RMS levels with timestamps, produces a stable
IDLE/TALKING state. No audio hardware, no Qt - fully unit-testable offline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

# Defaults per spec: quick attack, generous release, flicker-free.
_DEFAULTS = {
    "rms_threshold": 0.02,
    "noise_gate": 0.005,
    "attack_ms": 30,
    "release_ms": 250,
    "silence_ms": 300,
    "min_speech_ms": 60,
    "exit_ratio": 0.75,
}


@dataclass(frozen=True)
class SpeechParams:
    rms_threshold: float = _DEFAULTS["rms_threshold"]
    noise_gate: float = _DEFAULTS["noise_gate"]
    attack_ms: float = _DEFAULTS["attack_ms"]
    release_ms: float = _DEFAULTS["release_ms"]
    silence_ms: float = _DEFAULTS["silence_ms"]
    min_speech_ms: float = _DEFAULTS["min_speech_ms"]
    exit_ratio: float = _DEFAULTS["exit_ratio"]

    @property
    def exit_hold_ms(self) -> float:
        """Effective hold before IDLE: dips shorter than this are bridged."""
        return max(self.silence_ms, self.release_ms)

    def validated(self) -> "SpeechParams":
        return replace(
            self,
            rms_threshold=_clamp(self.rms_threshold, 0.0005, 1.0, _DEFAULTS["rms_threshold"]),
            noise_gate=_clamp(self.noise_gate, 0.0, 1.0, _DEFAULTS["noise_gate"]),
            attack_ms=_clamp(self.attack_ms, 1.0, 2000.0, _DEFAULTS["attack_ms"]),
            release_ms=_clamp(self.release_ms, 1.0, 2000.0, _DEFAULTS["release_ms"]),
            silence_ms=_clamp(self.silence_ms, 1.0, 5000.0, _DEFAULTS["silence_ms"]),
            min_speech_ms=_clamp(self.min_speech_ms, 0.0, 5000.0, _DEFAULTS["min_speech_ms"]),
            exit_ratio=_clamp(self.exit_ratio, 0.1, 1.0, _DEFAULTS["exit_ratio"]),
        )

    @classmethod
    def from_mapping(cls, mapping: Mapping | None) -> "SpeechParams":
        """Build params from a settings dict, ignoring unknown/invalid keys."""
        base = cls()
        if not mapping:
            return base
        fields = {f for f in cls.__dataclass_fields__}
        kwargs = {}
        for key, value in mapping.items():
            if key in fields:
                try:
                    kwargs[key] = float(value)
                except (TypeError, ValueError):
                    continue
        return replace(base, **kwargs).validated()

    def to_dict(self) -> dict:
        return {
            "rms_threshold": self.rms_threshold,
            "noise_gate": self.noise_gate,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
            "silence_ms": self.silence_ms,
            "min_speech_ms": self.min_speech_ms,
            "exit_ratio": self.exit_ratio,
        }


def _clamp(value: float, lo: float, hi: float, fallback: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(v):
        return fallback
    return min(hi, max(lo, v))


class SpeechDetector:
    """Threshold detector with attack/release hysteresis.

    Level units are normalized RMS (0.0 .. 1.0, float audio samples).
    """

    def __init__(self, params: SpeechParams | None = None):
        self.params = (params or SpeechParams()).validated()
        self.talking = False
        self.last_level = 0.0
        self.meter = 0.0  # smoothed display level
        self._above_ms = 0.0
        self._below_ms = 0.0
        self._segment_start_ms: float | None = None
        self._last_t: float | None = None
        self.last_change_ms: float | None = None

    # ------------------------------------------------------------------
    def process(self, level: float, t_ms: float) -> bool:
        """Feed one RMS sample at time t_ms; return current talking state."""
        p = self.params
        try:
            lvl = max(0.0, float(level))
            t = float(t_ms)
        except (TypeError, ValueError):
            return self.talking

        if self._last_t is not None and t < self._last_t:  # clock reset
            self._reset_timers()
        if self._last_t is None:
            dt = 0.0
        else:
            dt = t - self._last_t
        dt = min(dt, 500.0)  # protect against huge gaps
        self._last_t = t

        if lvl < p.noise_gate:
            lvl = 0.0
        self.last_level = lvl

        decay = 0.85 ** (dt / 16.7)  # per-frame display smoothing
        self.meter = max(lvl, self.meter * decay)

        enter_thr = p.rms_threshold
        exit_thr = p.rms_threshold * p.exit_ratio

        if not self.talking:
            if lvl >= enter_thr:
                self._above_ms += dt
            else:
                self._above_ms = 0.0
            if self._above_ms >= p.attack_ms:
                self.talking = True
                self._segment_start_ms = t - self._above_ms
                self._below_ms = 0.0
                self.last_change_ms = t
        else:
            if lvl < exit_thr:
                self._below_ms += dt
            else:
                self._below_ms = 0.0
            if self._below_ms >= p.exit_hold_ms:
                self.talking = False
                self._segment_start_ms = None
                self._above_ms = 0.0
                self._below_ms = 0.0
                self.last_change_ms = t
        return self.talking

    def process_sequence(self, samples: Iterable[tuple[float, float]]) -> bool:
        """Convenience: feed (level, t_ms) pairs; returns final state."""
        for level, t_ms in samples:
            self.process(level, t_ms)
        return self.talking

    def reset(self) -> None:
        self.talking = False
        self._reset_timers()

    def _reset_timers(self) -> None:
        self._above_ms = 0.0
        self._below_ms = 0.0
        self._segment_start_ms = None
        self._last_t = None
        self.last_level = 0.0
        self.meter = 0.0


class Calibrator:
    """Two-phase ambient/speech measurement that suggests a threshold."""

    def __init__(self, noise_seconds: float = 3.0, speech_seconds: float = 4.0):
        self.noise_seconds = noise_seconds
        self.speech_seconds = speech_seconds
        self.noise_samples: list[float] = []
        self.speech_samples: list[float] = []

    def add_noise(self, level: float) -> None:
        self.noise_samples.append(max(0.0, float(level)))

    def add_speech(self, level: float) -> None:
        self.speech_samples.append(max(0.0, float(level)))

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def noise_level(self) -> float:
        # 90th percentile-ish: mean of top half is overkill, mean is fine
        return self._mean(self.noise_samples)

    def speech_level(self) -> float:
        return self._mean(self.speech_samples)

    def suggest(self) -> float | None:
        """Suggested threshold between noise floor and speech level.

        Returns None when calibration is unusable (no speech detected or
        speech level indistinguishable from noise).
        """
        noise = self.noise_level()
        speech = self.speech_level()
        if not self.speech_samples or speech <= 0.0:
            return None
        floor = max(noise * 1.5, noise + 0.003)
        if speech <= floor * 1.15:
            return None
        # 35% of the way from floor toward speech: sensitive but safe
        return min(0.5, floor + (speech - floor) * 0.35)
