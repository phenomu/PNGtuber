from hakuze_pngtuber.core.animation_engine import AnimationEngine, AnimParams
from hakuze_pngtuber.core.avatar_controller import AvatarController, AvatarState
from hakuze_pngtuber.core.speech_detector import SpeechParams


class TestAvatarController:
    def test_starts_idle(self):
        c = AvatarController()
        assert c.state is AvatarState.IDLE

    def test_loud_audio_talks(self):
        c = AvatarController(SpeechParams(attack_ms=30))
        t = 0.0
        while t < 500:
            c.feed_level(0.08, t)
            t += 20
        assert c.state is AvatarState.TALKING

    def test_silence_returns_idle(self):
        c = AvatarController(SpeechParams(silence_ms=300))
        t = 0.0
        while t < 500:
            c.feed_level(0.08, t)
            t += 20
        while t < 1200:
            c.feed_level(0.0, t)
            t += 20
        assert c.state is AvatarState.IDLE

    def test_reset(self):
        c = AvatarController()
        t = 0.0
        while t < 500:
            c.feed_level(0.08, t)
            t += 20
        c.reset()
        assert c.state is AvatarState.IDLE
        assert c.level == 0.0

    def test_level_passthrough(self):
        c = AvatarController()
        c.feed_level(0.123, 0.0)
        assert abs(c.level - 0.123) < 1e-6


class TestAnimationEngine:
    def test_idle_at_rest(self):
        e = AnimationEngine()
        f = e.frame(False, 0.0)
        assert f.offset_y == 0.0

    def test_talking_rises(self):
        e = AnimationEngine(AnimParams(talking_lift_px=10, duration_ms=200))
        e.notify_state(True, 0.0)
        f = e.frame(True, 100.0)
        assert f.offset_y > 0.0

    def test_talking_settles_at_lift(self):
        e = AnimationEngine(AnimParams(talking_lift_px=10, bounce_px=0,
                                       sustain_bob_px=0, duration_ms=200))
        e.notify_state(True, 0.0)
        f = e.frame(True, 1000.0)
        assert abs(f.offset_y - 10.0) < 0.01

    def test_bounce_overshoots_then_settles(self):
        e = AnimationEngine(AnimParams(talking_lift_px=10, bounce_px=6, duration_ms=200))
        e.notify_state(True, 0.0)
        peak = 0.0
        t = 0.0
        while t < 400:
            peak = max(peak, e.frame(True, t).offset_y)
            t += 5
        settled = e.frame(True, 1000.0).offset_y
        assert peak > 10.0  # overshoot beyond the resting lift
        assert settled < peak

    def test_returns_to_rest_after_speech(self):
        e = AnimationEngine(AnimParams(talking_lift_px=10, duration_ms=200))
        e.notify_state(True, 0.0)
        e.frame(True, 1000.0)
        e.notify_state(False, 1000.0)
        f = e.frame(False, 2000.0)
        assert abs(f.offset_y) < 0.01

    def test_smooth_return_not_instant(self):
        e = AnimationEngine(AnimParams(talking_lift_px=10, duration_ms=200))
        e.notify_state(True, 0.0)
        e.frame(True, 1000.0)
        e.notify_state(False, 1000.0)
        f = e.frame(False, 1050.0)  # quarter way through the return
        assert 0.0 < f.offset_y < 10.0

    def test_disabled_animation_flat(self):
        e = AnimationEngine(AnimParams(enabled=False))
        e.notify_state(True, 0.0)
        f = e.frame(True, 100.0)
        assert f.offset_y == 0.0

    def test_breathing_optional(self):
        e = AnimationEngine(AnimParams(breathing=True, breath_amplitude_px=3,
                                       breath_period_ms=2000))
        # idle breathing oscillates around rest
        offs = [e.frame(False, t).offset_y for t in (0, 500, 1000, 1500, 2000)]
        assert abs(offs[1] - offs[3]) > 0.5  # opposite phases differ
        assert max(offs) <= 3.0 + 1e-6

    def test_breathing_off_by_default(self):
        assert AnimParams().breathing is False

    def test_no_jump_on_state_switch(self):
        """Offset right after switching images must be continuous."""
        e = AnimationEngine(AnimParams(talking_lift_px=10, duration_ms=200))
        e.notify_state(True, 0.0)
        t = 0.0
        last = 0.0
        max_jump = 0.0
        while t < 600:
            f = e.frame(True, t)
            max_jump = max(max_jump, abs(f.offset_y - last))
            last = f.offset_y
            t += 16.7
        assert max_jump < 10.0  # sine-continuous: no teleport-level jumps at 60fps

    def test_params_clamped(self):
        p = AnimParams(talking_lift_px=-50, duration_ms=1e9).validated()
        assert p.talking_lift_px == 0.0
        assert p.duration_ms <= 1000.0

    def test_params_from_mapping(self):
        p = AnimParams.from_mapping({"duration_ms": "200", "enabled": "true",
                                     "junk": 1})
        assert p.duration_ms == 200.0
        assert p.enabled is True
