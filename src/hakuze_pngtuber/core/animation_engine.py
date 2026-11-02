"""Avatar animation math: lift, damped bounce, smooth return, optional breathing.

Pure functions + tiny state - no Qt, fully unit-testable.
Positive offset_y means "character moves up".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping

_DEFAULTS = {
    "enabled": True,
    "talking_lift_px": 10.0,
    "bounce_px": 12.0,
    "duration_ms": 180.0,
    "speed": 1.0,
    "breathing": False,
    "breath_amplitude_px": 3.0,
    "breath_period_ms": 3200.0,
    "sustain_bob_px": 1.5,
    "sustain_bob_period_ms": 1200.0,
}


@dataclass(frozen=True)
class AnimParams:
    enabled: bool = _DEFAULTS["enabled"]
    talking_lift_px: float = _DEFAULTS["talking_lift_px"]
    bounce_px: float = _DEFAULTS["bounce_px"]
    duration_ms: float = _DEFAULTS["duration_ms"]
    speed: float = _DEFAULTS["speed"]
    breathing: bool = _DEFAULTS["breathing"]
    breath_amplitude_px: float = _DEFAULTS["breath_amplitude_px"]
    breath_period_ms: float = _DEFAULTS["breath_period_ms"]
    sustain_bob_px: float = _DEFAULTS["sustain_bob_px"]
    sustain_bob_period_ms: float = _DEFAULTS["sustain_bob_period_ms"]

    @property
    def duration_eff_ms(self) -> float:
        return max(30.0, self.duration_ms / max(0.25, self.speed))

    @classmethod
    def from_mapping(cls, mapping: Mapping | None) -> "AnimParams":
        base = cls()
        if not mapping:
            return base
        bools = {"enabled", "breathing"}
        floats = {f for f in cls.__dataclass_fields__} - bools
        kwargs = {}
        for key, value in mapping.items():
            if key in bools:
                if isinstance(value, bool):
                    kwargs[key] = value
                elif isinstance(value, str) and value.lower() in ("true", "false"):
                    kwargs[key] = value.lower() == "true"
                elif isinstance(value, (int, float)):
                    kwargs[key] = bool(value)
            elif key in floats:
                try:
                    kwargs[key] = float(value)
                except (TypeError, ValueError):
                    continue
        return replace(base, **kwargs).validated()

    def validated(self) -> "AnimParams":
        return replace(
            self,
            talking_lift_px=_safe(self.talking_lift_px, 0.0, 200.0, _DEFAULTS["talking_lift_px"]),
            bounce_px=_safe(self.bounce_px, 0.0, 200.0, _DEFAULTS["bounce_px"]),
            duration_ms=_safe(self.duration_ms, 30.0, 1000.0, _DEFAULTS["duration_ms"]),
            speed=_safe(self.speed, 0.25, 4.0, _DEFAULTS["speed"]),
            breath_amplitude_px=_safe(self.breath_amplitude_px, 0.0, 50.0, _DEFAULTS["breath_amplitude_px"]),
            breath_period_ms=_safe(self.breath_period_ms, 500.0, 20000.0, _DEFAULTS["breath_period_ms"]),
            sustain_bob_px=_safe(self.sustain_bob_px, 0.0, 20.0, _DEFAULTS["sustain_bob_px"]),
            sustain_bob_period_ms=_safe(self.sustain_bob_period_ms, 300.0, 10000.0, _DEFAULTS["sustain_bob_period_ms"]),
        )

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _DEFAULTS}


def _safe(value: float, lo: float, hi: float, fallback: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(v):
        return fallback
    return min(hi, max(lo, v))


def ease_out_cubic(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1.0 - (1.0 - p) ** 3


def ease_in_out_cubic(p: float) -> float:
    p = min(1.0, max(0.0, p))
    if p < 0.5:
        return 4.0 * p ** 3
    return 1.0 - ((-2.0 * p + 2.0) ** 3) / 2.0


@dataclass(frozen=True)
class AnimFrame:
    offset_y: float = 0.0
    scale: float = 1.0
    active: bool = False  # True while animating (timer should keep running)


class AnimationEngine:
    """Computes per-frame vertical offset for the avatar.

    Call notify_state() when the speech state changes, frame() every tick.
    """

    def __init__(self, params: AnimParams | None = None):
        self.params = (params or AnimParams()).validated()
        self._talking = False
        self._t_talk_start: float | None = None
        self._t_idle_start: float | None = None
        self._exit_offset: float = 0.0
        self._clock0: float | None = None

    def notify_state(self, talking: bool, t_ms: float) -> None:
        if talking == self._talking:
            return
        if talking:
            self._t_talk_start = float(t_ms)
            self._t_idle_start = None
        else:
            self._t_idle_start = float(t_ms)
            self._exit_offset = self._current_talking_offset(t_ms)
        self._talking = talking

    def frame(self, talking: bool, t_ms: float) -> AnimFrame:
        p = self.params
        t = float(t_ms)
        if self._clock0 is None:
            self._clock0 = t
        if not p.enabled:
            return AnimFrame(0.0, 1.0, False)
        if talking:
            offset = self._current_talking_offset(t)
            return AnimFrame(offset, 1.0, True)
        offset = self._current_idle_offset(t)
        active = self._t_idle_start is not None and (t - self._t_idle_start) < p.duration_eff_ms
        return AnimFrame(offset, 1.0, active)

    # internals ---------------------------------------------------------
    def _current_talking_offset(self, t_ms: float) -> float:
        p = self.params
        if self._t_talk_start is None:
            return 0.0
        elapsed = max(0.0, t_ms - self._t_talk_start)
        dur = p.duration_eff_ms
        phase = min(1.0, elapsed / dur)
        lift = p.talking_lift_px * ease_out_cubic(phase)
        # damped bounce: one full sine cycle per animation duration
        bounce = p.bounce_px * math.exp(-2.0 * phase) * math.sin(2.0 * math.pi * phase)
        offset = lift + bounce
        if phase >= 1.0 and p.sustain_bob_px > 0.0:
            offset += p.sustain_bob_px * math.sin(
                2.0 * math.pi * (t_ms / max(1.0, p.sustain_bob_period_ms))
            )
        return offset

    def _current_idle_offset(self, t_ms: float) -> float:
        p = self.params
        offset = 0.0
        # smooth return from the exit offset
        if self._t_idle_start is not None:
            elapsed = max(0.0, t_ms - self._t_idle_start)
            phase = min(1.0, elapsed / p.duration_eff_ms)
            offset = self._exit_offset * (1.0 - ease_in_out_cubic(phase))
        # optional breathing overlay (disabled by default per spec)
        if p.breathing and p.breath_amplitude_px > 0.0:
            offset += p.breath_amplitude_px * math.sin(
                2.0 * math.pi * (t_ms / max(1.0, p.breath_period_ms))
            )
        return offset

    def reset(self) -> None:
        self._talking = False
        self._t_talk_start = None
        self._t_idle_start = None
        self._exit_offset = 0.0
        self._clock0 = None
