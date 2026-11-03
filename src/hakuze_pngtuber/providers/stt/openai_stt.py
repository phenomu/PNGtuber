"""Direct OpenAI transcription provider (audio/transcriptions endpoint).

Sends ONLY the captured utterance (16 kHz mono WAV), never a stream. The
openai SDK is imported lazily; tests inject a fake client.
"""
from __future__ import annotations

import io
import wave
from typing import Any

from .base import BaseSTTProvider, STTError, STTCancelled, STTRequest

_ERR_MAP = {
    "401": "invalid API key (check STT key in AI tab, or route STT via the LLM gateway)",
    "403": "API key not authorized for this model/endpoint",
    "404": "model or endpoint not found on this provider (check STT model id)",
    "429": "rate limit reached",
    "timeout": "transcription timed out",
    "insufficient_quota": "billing quota exhausted",
    "unsupported file format": "audio upload rejected (file format metadata)",
}


class OpenAISTT(BaseSTTProvider):
    name = "openai-stt"

    def __init__(self, api_key: str | None, model: str = "gpt-4o-mini-transcribe",
                 base_url: str | None = None,
                 client_factory=None):
        self._api_key = api_key or ""
        self._model = model
        self._base_url = (base_url or "").strip() or None
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory(
                    api_key=self._api_key, base_url=self._base_url)
            else:
                import openai  # noqa: PLC0415 - lazy by design
                kwargs: dict[str, Any] = dict(
                    api_key=self._api_key or "missing", max_retries=1,
                    timeout=30.0)  # SDK default is 600s - never wait that long
                if self._base_url:
                    # routed through a gateway (e.g. 9Router): same key as
                    # the LLM then, and the endpoint must exist there
                    kwargs["base_url"] = self._base_url
                self._client = openai.OpenAI(**kwargs)
        return self._client

    def reset(self) -> None:
        self._client = None

    def reconfigure(self, api_key: str | None = None,
                    model: str | None = None,
                    base_url: str | None = None) -> None:
        """Hot-apply new credentials/model/base_url; drops the cached client."""
        if api_key is not None:
            self._api_key = api_key
        if model is not None:
            self._model = model or "gpt-4o-mini-transcribe"
        if base_url is not None:
            self._base_url = (base_url or "").strip() or None
        self._client = None

    def transcribe(self, request: STTRequest) -> str:
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise STTCancelled()
        if not request.audio:
            raise STTError("no audio", "nothing to transcribe")
        # normalize to a WAV the API accepts
        wav = self._ensure_wav(request.audio)
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "file": wav,
        }
        if request.language:
            kwargs["language"] = request.language
        if request.prompt:
            kwargs["prompt"] = request.prompt
        try:
            wav.name = "utterance.wav"  # API needs format metadata (400
            # 'Unsupported file format' when the upload has no filename)
            transcript = client.audio.transcriptions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - translated
            raise self._translate(exc) from exc
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise STTCancelled()
        text = getattr(transcript, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise STTError("empty", "no speech detected")
        return text.strip()

    @staticmethod
    def _ensure_wav(pcm: bytes) -> io.BytesIO:
        """Wrap raw PCM into a WAV container (idempotent for WAV input)."""
        if pcm[:4] == b"RIFF" and pcm[8:12] == b"WAVE":
            return io.BytesIO(pcm)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        buf.seek(0)
        return buf

    @staticmethod
    def _translate(exc: Exception) -> STTError:
        text = str(exc)
        low = text.lower()
        for token, msg in _ERR_MAP.items():
            if token in text or token in low:
                return STTError(text, msg)
        return STTError(text, "transcription failed")

    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        # cheapest honest probe: submit 0.1s of silence and expect either a
        # transcript or an "empty" result — auth/network errors surface here
        try:
            client = self._get_client()
            try:
                models = client.models.list()
                n = len(list(models))
                return True, f"connected ({n} models visible)"
            except Exception:  # noqa: BLE001 - /models may be unsupported
                pass
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 1600)
            buf.seek(0)
            buf.name = "silence.wav"  # format metadata required by the API
            try:
                client.audio.transcriptions.create(
                    model=self._model, file=buf)
                return True, "connected"
            except Exception as exc:  # noqa: BLE001 - translated
                err = self._translate(exc)
                if err.user_message == "no speech detected":
                    return True, "connected"
                return False, err.user_message
        except Exception as exc:  # noqa: BLE001
            return False, self._translate(exc).user_message


class MockSTT(BaseSTTProvider):
    """Scripted STT for tests / offline dev."""

    name = "mock-stt"

    def __init__(self, transcripts: list[str] | None = None,
                 error: Exception | None = None):
        self.transcripts = list(transcripts or ["Hai GPT, apa itu obsidian?"])
        self.error = error
        self.calls: list[bytes] = []

    def transcribe(self, request: STTRequest) -> str:
        self.calls.append(request.audio)
        if self.error is not None:
            raise self.error
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise STTCancelled()
        text = self.transcripts[min(len(self.calls) - 1,
                                    len(self.transcripts) - 1)]
        if not text.strip():
            raise STTError("empty", "no speech detected")
        return text

    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        return self.error is None, "mock ok" if self.error is None else "mock error"
