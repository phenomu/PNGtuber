import math

import numpy as np
import pytest

from hakuze_pngtuber.core.speech_detector import (
    Calibrator,
    SpeechDetector,
    SpeechParams,
)
from hakuze_pngtuber.utils.audio_utils import block_rms, linear_to_db


def step(detector, level, t_ms):
    return detector.process(level, t_ms)


def feed(detector, level, start_ms, duration_ms, step_ms=20.0):
    t = start_ms
    while t < start_ms + duration_ms:
        state = step(detector, level, t)
        t += step_ms
    return state


class TestSpeechParams:
    def test_defaults_sane(self):
        p = SpeechParams().validated()
        assert 0 < p.rms_threshold <= 1
        assert p.attack_ms > 0
        assert p.silence_ms >= p.release_ms

    def test_from_mapping_ignores_junk(self):
        p = SpeechParams.from_mapping({
            "rms_threshold": "not-a-number",
            "attack_ms": 50,
            "unknown_key": 1,
            "silence_ms": None,
        })
        assert p.attack_ms == 50
        assert p.silence_ms == SpeechParams().silence_ms
        assert not hasattr(p, "unknown_key")

    def test_validation_clamps(self):
        p = SpeechParams(rms_threshold=-5, attack_ms=1e9).validated()
        assert p.rms_threshold > 0
        assert p.attack_ms <= 2000


class TestSpeechDetector:
    def test_silence_stays_idle(self):
        d = SpeechDetector()
        assert feed(d, 0.0, 0, 3000) is False

    def test_low_noise_stays_idle(self):
        d = SpeechDetector(SpeechParams(rms_threshold=0.02, noise_gate=0.004))
        # background hum below threshold
        assert feed(d, 0.006, 0, 3000) is False

    def test_noise_gate_zeroes_sub_gate_levels(self):
        d = SpeechDetector(SpeechParams(rms_threshold=0.01, noise_gate=0.02))
        # 0.015 exceeds threshold but is under the noise gate -> gated out
        assert feed(d, 0.015, 0, 2000) is False

    def test_normal_speech_triggers(self):
        d = SpeechDetector()
        assert feed(d, 0.06, 0, 1000) is True

    def test_sudden_spike_rejected(self):
        d = SpeechDetector(SpeechParams(min_speech_ms=60, attack_ms=30))
        t = 0.0
        # one 20ms spike then silence
        d.process(0.5, t); t += 20
        state = feed(d, 0.0, t, 1000)
        assert state is False

    def test_sustained_speech_stays_talking(self):
        d = SpeechDetector()
        feed(d, 0.08, 0, 500)
        assert d.talking
        assert feed(d, 0.08, 500, 10000) is True

    def test_returns_to_idle_after_silence(self):
        d = SpeechDetector(SpeechParams(silence_ms=300))
        feed(d, 0.08, 0, 500)
        assert d.talking
        state = feed(d, 0.0, 500, 400)
        assert state is False

    def test_brief_dip_bridged_while_talking(self):
        d = SpeechDetector(SpeechParams(silence_ms=400, release_ms=150))
        feed(d, 0.08, 0, 600)
        # 80ms dip (shorter than release_ms), then speech again
        t = 600.0
        for _ in range(4):
            d.process(0.0, t); t += 20
        state = feed(d, 0.08, t, 600)
        assert state is True

    def test_long_gap_returns_idle(self):
        d = SpeechDetector(SpeechParams(silence_ms=300))
        feed(d, 0.08, 0, 500)
        assert feed(d, 0.0, 500, 500) is False

    def test_soft_speech_no_flicker(self):
        """Oscillating near-threshold speech must not rapidly toggle state."""
        d = SpeechDetector(SpeechParams(rms_threshold=0.03, silence_ms=300))
        d.process(0.05, 0)
        t = 20.0
        switches = 0
        prev = d.talking
        for i in range(200):  # 4 seconds alternating loud/quiet 100ms chunks
            level = 0.05 if (i // 5) % 2 == 0 else 0.025
            d.process(level, t)
            if d.talking != prev:
                switches += 1
                prev = d.talking
            t += 20
        assert switches <= 2

    def test_meter_tracks_level(self):
        d = SpeechDetector()
        d.process(0.3, 0.0)
        assert d.meter > 0.1
        d.process(0.0, 20.0)
        assert d.meter > 0.0  # peak-hold decay, not instant zero

    def test_time_going_backwards_resets(self):
        d = SpeechDetector()
        feed(d, 0.08, 0, 400)
        assert d.talking
        d.process(0.08, 10.0)  # clock reset
        assert d.talking is False or d._above_ms >= 0  # no crash


class TestCalibrator:
    def test_suggests_threshold_between_noise_and_speech(self):
        c = Calibrator()
        for _ in range(50):
            c.add_noise(0.002)
        for _ in range(50):
            c.add_speech(0.09)
        thr = c.suggest()
        assert thr is not None
        assert 0.002 * 1.5 < thr < 0.09

    def test_no_speech_returns_none(self):
        c = Calibrator()
        for _ in range(50):
            c.add_noise(0.002)
        assert c.suggest() is None

    def test_unusable_separation_returns_none(self):
        c = Calibrator()
        for _ in range(50):
            c.add_noise(0.05)
        for _ in range(50):
            c.add_speech(0.06)
        assert c.suggest() is None


class TestAudioUtils:
    def test_block_rms_constant(self):
        block = np.full(960, 0.5, dtype=np.float32)
        assert math.isclose(block_rms(block), 0.5, rel_tol=1e-4)

    def test_block_rms_sine(self):
        t = np.linspace(0, 1, 48000, dtype=np.float32)
        block = 0.707 * np.sin(2 * np.pi * 440 * t)
        assert math.isclose(block_rms(block), 0.5, rel_tol=0.02)

    def test_block_rms_empty(self):
        assert block_rms(None) == 0.0
        assert block_rms(np.array([], dtype=np.float32)) == 0.0

    def test_block_rms_stereo_mixes(self):
        block = np.zeros((480, 2), dtype=np.float32)
        block[:, 0] = 1.0
        assert math.isclose(block_rms(block), 0.5, rel_tol=1e-4)

    def test_db_conversions(self):
        assert math.isclose(linear_to_db(0.5), -6.0206, rel_tol=1e-3)
        assert linear_to_db(0.0) == -120.0
