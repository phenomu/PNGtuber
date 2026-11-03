"""TTS provider interface (Qt-free)."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass


class TTSError(Exception):
    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or "speech synthesis failed"


class TTSCancelled(TTSError):
    def __init__(self):
        super().__init__("cancelled", "speech cancelled")


@dataclass
class TTSRequest:
    text: str
    voice: str | None = None
    speed: float = 1.0          # 0.25..4.0
    volume: float = 1.0         # 0..1 (provider-dependent meaning)
    format: str = "wav"
    cancel_event: "threading.Event | None" = None


class BaseTTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> bytes:
        """Return audio bytes (WAV PCM16 by contract)."""

    @abstractmethod
    def list_voices(self) -> list[str]:
        """Available voice names (may be empty)."""


class MockTTS(BaseTTSProvider):
    """Offline test double: emits silence proportional to text length."""

    name = "mock-tts"

    def __init__(self, error: Exception | None = None,
                 voices: list[str] | None = None):
        self.error = error
        self._voices = voices or ["Mock Female", "Mock Male"]
        self.calls: list[str] = []

    def synthesize(self, request: TTSRequest) -> bytes:
        self.calls.append(request.text)
        if self.error is not None:
            raise self.error
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise TTSCancelled()
        return self._silence_wav(max(200, 60 * len(request.text)))

    def list_voices(self) -> list[str]:
        return list(self._voices)

    @staticmethod
    def _silence_wav(duration_ms: int) -> bytes:
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x00" * int(24000 * duration_ms / 1000))
        return buf.getvalue()
