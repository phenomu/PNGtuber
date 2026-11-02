"""Avatar state controller: bridges speech detection to avatar rendering state."""
from __future__ import annotations

from enum import Enum

from .animation_engine import AnimationEngine
from .asset_manager import AssetManager
from .speech_detector import Calibrator, SpeechDetector, SpeechParams


class AvatarState(Enum):
    IDLE = "idle"
    TALKING = "talking"


class AvatarController:
    """Owns the detector; maps audio levels to avatar state + images.

    UI polls feed_audio() results and animates via the AnimationEngine.
    """

    def __init__(self, speech_params: SpeechParams | None = None, assets: AssetManager | None = None):
        self.detector = SpeechDetector(speech_params)
        self.animation = AnimationEngine()
        self.assets = assets
        self.state = AvatarState.IDLE

    # ------------------------------------------------------------------
    def feed_level(self, level: float, t_ms: float) -> AvatarState:
        talking = self.detector.process(level, t_ms)
        new_state = AvatarState.TALKING if talking else AvatarState.IDLE
        if new_state is not self.state:
            self.state = new_state
        self.animation.notify_state(talking, t_ms)
        return self.state

    @property
    def talking(self) -> bool:
        return self.state is AvatarState.TALKING

    @property
    def level(self) -> float:
        return self.detector.last_level

    @property
    def meter(self) -> float:
        return self.detector.meter

    def reset(self) -> None:
        self.detector.reset()
        self.animation.reset()
        self.state = AvatarState.IDLE

    # convenience passthrough for the calibration UI -------------------
    def apply_params(self, speech: SpeechParams | None = None, anim: object | None = None) -> None:
        if speech is not None:
            self.detector.params = speech.validated()
        if anim is not None:
            self.animation.params = anim.validated()
