"""OpenAI TTS provider: POST /v1/audio/speech -> WAV bytes."""
from __future__ import annotations

import io
import wave
from typing import Any

from .base import BaseTTSProvider, TTSError, TTSCancelled, TTSRequest

VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable",
          "nova", "onyx", "sage", "shimmer")


class OpenAITTS(BaseTTSProvider):
    name = "openai-tts"

    def __init__(self, api_key: str | None,
                 model: str = "gpt-4o-mini-tts",
                 client_factory=None):
        self._api_key = api_key or ""
        self._model = model
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory(api_key=self._api_key)
            else:
                import openai  # noqa: PLC0415 - lazy by design
                self._client = openai.OpenAI(
                    api_key=self._api_key or "missing", max_retries=1)
        return self._client

    def reset(self) -> None:
        self._client = None

    def reconfigure(self, api_key: str | None = None,
                    model: str | None = None) -> None:
        """Hot-apply new credentials/model; drops the cached client."""
        if api_key is not None:
            self._api_key = api_key
        if model is not None:
            self._model = model or "gpt-4o-mini-tts"
        self._client = None

    def synthesize(self, request: TTSRequest) -> bytes:
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise TTSCancelled()
        if not request.text.strip():
            raise TTSError("empty", "nothing to speak")
        client = self._get_client()
        try:
            audio = client.audio.speech.create(
                model=self._model,
                voice=request.voice or "alloy",
                input=request.text,
                speed=float(request.speed),
                response_format="wav",
            )
            data = audio.content if hasattr(audio, "content") else audio
            if isinstance(data, str):  # defensive
                data = data.encode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 - translated
            raise self._translate(exc) from exc
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise TTSCancelled()
        return bytes(data)

    @staticmethod
    def _translate(exc: Exception) -> TTSError:
        text = str(exc)
        if "401" in text or "unauthorized" in text.lower():
            return TTSError(text, "invalid OpenAI API key")
        if "timeout" in text.lower():
            return TTSError(text, "speech synthesis timed out")
        return TTSError(text, "speech synthesis failed")

    def list_voices(self) -> list[str]:
        return list(VOICES)


class WindowsSapiTTS(BaseTTSProvider):
    """Local Windows TTS via SAPI (pyttsx3) — no API fees, offline.

    pyttsx3's runAndWait model is blocking and weakly interruptible, so this
    provider SYNTHESIZES to a WAV file using SAPI's ISpVoice SpeakToFile-
    style path (pyttsx3 save_to_file) and lets the shared TTS playback
    engine own cancellation/interruption (documented limitation).
    """

    name = "windows-sapi"

    def __init__(self, voice: str | None = None, rate: int = 0):
        self._engine = None
        self._voice = voice
        self._rate = rate

    def reconfigure(self, voice: str | None = None,
                    rate: int | None = None) -> None:
        """Hot-apply voice/rate; the engine is rebuilt on next use."""
        if voice is not None:
            self._voice = voice or None
            self._engine = None
        if rate is not None:
            self._rate = int(rate)
            self._engine = None

    def _make_engine(self):
        import pyttsx3  # noqa: PLC0415 - Windows-only dep, optional
        engine = pyttsx3.init()
        self._base_rate = engine.getProperty("rate") or 200
        if self._voice:
            for v in engine.getProperty("voices"):
                if v.name == self._voice:
                    engine.setProperty("voice", v.id)
                    break
        engine.setProperty("rate", self._rate)
        return engine

    def synthesize(self, request: TTSRequest) -> bytes:
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise TTSCancelled()
        try:
            if self._engine is None:
                self._engine = self._make_engine()
            # per-request voice (falls back to the configured default)
            voice = request.voice or self._voice
            if voice:
                for v in self._engine.getProperty("voices"):
                    if v.name == voice:
                        self._engine.setProperty("voice", v.id)
                        break
            # per-request speed via base rate (SAPI rate ~ wpm)
            speed = float(request.speed or 1.0)
            if speed != 1.0:
                base = getattr(self, "_base_rate", None) or 200
                self._engine.setProperty("rate", int(base * speed))
            self._engine.setProperty(
                "volume", max(0.0, min(1.0, float(request.volume or 1.0))))
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".wav")
            import os
            os.close(fd)
            self._engine.save_to_file(request.text, path)
            self._engine.runAndWait()
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        except ImportError as exc:
            raise TTSError(str(exc), "local TTS unavailable (pyttsx3 not installed)") from exc
        except Exception as exc:  # noqa: BLE001 - translated
            raise TTSError(str(exc), "local TTS failed") from exc
        if not data:
            raise TTSError("empty", "local TTS produced no audio")
        return data

    def list_voices(self) -> list[str]:
        try:
            if self._engine is None:
                self._engine = self._make_engine()
            return [v.name for v in self._engine.getProperty("voices")]
        except Exception:  # noqa: BLE001 - not on Windows / no voices
            return []
