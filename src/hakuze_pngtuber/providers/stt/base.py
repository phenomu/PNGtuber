"""STT provider interface (Qt-free)."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class STTError(Exception):
    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or "transcription failed"


class STTCancelled(STTError):
    def __init__(self):
        super().__init__("cancelled", "transcription cancelled")


class STTEmpty(STTError):
    def __init__(self):
        super().__init__("empty transcript", "no speech detected")


@dataclass
class STTRequest:
    audio: bytes                # 16 kHz mono 16-bit PCM WAV
    model: str | None = None
    language: str | None = None  # None = auto-detect
    prompt: str | None = None    # transcription hint
    timeout_s: float = 30.0
    cancel_event: threading.Event | None = None
    extra: dict = field(default_factory=dict)


class BaseSTTProvider(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, request: STTRequest) -> str:
        """Return the transcript text. Raises STTError subclasses."""

    @abstractmethod
    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        """(ok, message) auth/connectivity probe."""
