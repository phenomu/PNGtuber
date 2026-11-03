"""Speech capture: segment recorder with VAD endpointing (Qt-free).

Consumes raw 20 ms mic blocks (float32, any source rate), buffers an
utterance, decides when speech ends by trailing silence, and emits a
16 kHz mono 16-bit WAV. Used by the assistant worker while the avatar's
RMS path keeps running untouched.
"""
from __future__ import annotations

import io
import wave
import numpy as np

_TARGET_RATE = 16000


class SpeechRecorder:
    """One utterance at a time. feed(block) -> True while capturing.

    Starts on first block above `start_threshold`, ends after
    `endpoint_silence_ms` of continuous quiet below `stop_threshold`
    (or `max_utterance_ms` hard cap). Pre-roll keeps a little lead-in.
    """

    def __init__(self, source_rate: int = 48000,
                 start_threshold: float = 0.012,
                 stop_threshold: float = 0.008,
                 endpoint_silence_ms: int = 700,
                 max_utterance_ms: int = 15000,
                 preroll_blocks: int = 3,
                 min_utterance_ms: int = 300):
        self.source_rate = source_rate
        self.start_threshold = float(start_threshold)
        self.stop_threshold = float(stop_threshold)
        self.endpoint_silence_ms = int(endpoint_silence_ms)
        self.max_utterance_ms = int(max_utterance_ms)
        self.preroll_blocks = int(preroll_blocks)
        self.min_utterance_ms = int(min_utterance_ms)
        self.reset()

    def reset(self) -> None:
        self._active = False
        self._buf: list[np.ndarray] = []
        self._silence_ms = 0.0
        self._speech_ms = 0.0
        self._total_ms = 0.0
        self._preroll: list[np.ndarray] = []

    @property
    def capturing(self) -> bool:
        return self._active

    @staticmethod
    def _rms(block: np.ndarray) -> float:
        if block is None or block.size == 0:
            return 0.0
        mono = block if block.ndim == 1 else block.mean(axis=1)
        return float(np.sqrt(np.mean(np.square(mono.astype(np.float32)))))

    def feed(self, block: np.ndarray) -> bool:
        """Feed one 20 ms block. Returns True while an utterance is active.
        Call result() after feed() returns False and had_speech() is True."""
        rms = self._rms(block)
        block_ms = 1000.0 * max(1, block.shape[0]) / self.source_rate \
            if block is not None and block.size else 20.0
        if not self._active:
            self._preroll.append(block)
            if len(self._preroll) > self.preroll_blocks:
                self._preroll.pop(0)
            if rms >= self.start_threshold:
                self._active = True
                self._buf = list(self._preroll)
                self._preroll = []
                self._speech_ms = block_ms
                self._silence_ms = 0.0
            return self._active

        # capturing
        self._total_ms += block_ms
        if rms >= self.stop_threshold:
            self._speech_ms += block_ms
            self._silence_ms = 0.0
        else:
            self._silence_ms += block_ms
        self._buf.append(block)
        done = (self._silence_ms >= self.endpoint_silence_ms
                or self._total_ms >= self.max_utterance_ms)
        if done:
            self._active = False
        return self._active

    def had_speech(self) -> bool:
        return bool(self._buf) and self._speech_ms >= self.min_utterance_ms

    def result(self) -> bytes:
        """Concatenated utterance as 16 kHz mono 16-bit WAV bytes."""
        if not self._buf:
            return b""
        audio = np.concatenate([np.asarray(b, dtype=np.float32).reshape(-1)
                                for b in self._buf])
        # channels>1 mono-mean
        # (reshape(-1) already interleaved; assume mono input from tap)
        resampled = self._resample(audio, self.source_rate, _TARGET_RATE)
        pcm16 = np.clip(resampled, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_TARGET_RATE)
            w.writeframes(pcm16.tobytes())
        data = buf.getvalue()
        self.reset()
        return data

    @staticmethod
    def _resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst or data.size == 0:
            return data
        # linear interpolation resample (quality is fine for speech STT)
        n_out = int(round(data.size * dst / src))
        if n_out <= 0:
            return np.zeros(0, dtype=np.float32)
        x_src = np.arange(data.size, dtype=np.float64) / src
        x_dst = np.arange(n_out, dtype=np.float64) / dst
        return np.interp(x_dst, x_src, data.astype(np.float64)).astype(np.float32)


def wav_duration_ms(wav_bytes: bytes) -> float:
    """Duration of a WAV byte blob in milliseconds (for tests/logging)."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            return 1000.0 * w.getnframes() / w.getframerate()
    except (wave.Error, OSError):
        return 0.0
