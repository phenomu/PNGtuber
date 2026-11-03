"""OpenAI TTS provider: POST /v1/audio/speech -> WAV bytes."""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path
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
                    api_key=self._api_key or "missing", max_retries=1,
                    timeout=30.0)  # SDK default is 600s - cap synthesis waits
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

    pyttsx3/SAPI holds process-global COM state: re-initializing the
    engine after voice/model changes, or driving it repeatedly, can make
    runAndWait() hang forever — which used to freeze the whole assistant
    worker (every AI button stopped responding). Synthesis therefore runs
    in a throwaway SUBPROCESS: a hang is killable via timeout, and COM
    state can never accumulate across calls.
    """

    name = "windows-sapi"
    _TIMEOUT_S = 30.0

    def __init__(self, voice: str | None = None, rate: int = 0):
        self._voice = voice
        self._rate = rate
        self._voices_cache: list[str] | None = None
        self._last_error: str | None = None

    # -------------------------------------------------------------- runner
    def _run_subprocess(self, args: list[str], timeout: float) \
            -> tuple[int, str, str]:
        import subprocess
        try:
            proc = subprocess.run(
                args, capture_output=True, timeout=timeout,
                env=self._subprocess_env())
            return (proc.returncode,
                    proc.stdout.decode(errors="replace").strip(),
                    proc.stderr.decode(errors="replace").strip())
        except subprocess.TimeoutExpired:
            return 124, "", "synthesis timed out (killed)"
        except FileNotFoundError as exc:
            return 127, "", f"runner not found: {exc}"
        except Exception as exc:  # noqa: BLE001
            return 1, "", str(exc)

    @staticmethod
    def _subprocess_env():
        """Make `hakuze_pngtuber` importable in the child (dev runs)."""
        import os
        import sys
        env = dict(os.environ)
        src_root = str(Path(__file__).resolve().parents[3])
        if getattr(sys, "frozen", False):
            return env  # exe bundles the package
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing}" \
            if existing else src_root
        return env

    def _base_command(self) -> list[str] | None:
        """Dispatch SAPI commands via a detached exe invocation.

        Frozen: re-invoke our own exe with --sapi-* flags (handled in
        hakuze_pngtuber.main). Source: python -m module. Returns None
        when no usable runner exists (non-Windows dev boxes).
        """
        import sys
        frozen = getattr(sys, "frozen", False)
        if frozen:
            return [sys.executable, "--sapi-voices"]
        # dev source run
        argv = [sys.executable, "-m",
                "hakuze_pngtuber.providers.tts._sapi_synth", "voices"]
        return argv

    def _synth_command(self, text: str, voice: str | None,
                       speed: float, volume: float, out_path: str) \
            -> list[str] | None:
        import sys
        frozen = getattr(sys, "frozen", False)
        if frozen:
            return [sys.executable, "--sapi-synth", "--text", text,
                    "--out", out_path,
                    "--rate", f"{speed or 1.0}",
                    "--volume", f"{volume}"] + \
                (["--voice", voice] if voice else [])
        return [sys.executable, "-m",
                "hakuze_pngtuber.providers.tts._sapi_synth", "synth",
                "--text", text, "--out", out_path,
                "--rate", f"{speed or 1.0}",
                "--volume", f"{volume}"] + \
            (["--voice", voice] if voice else [])

    # -------------------------------------------------------------- API
    def reconfigure(self, voice: str | None = None,
                    rate: int | None = None) -> None:
        """Hot-apply voice/rate (no engine to rebuild — subprocess model)."""
        if voice is not None:
            self._voice = voice or None
        if rate is not None:
            self._rate = int(rate)
        self._voices_cache = None  # force re-enumeration

    def list_voices(self) -> list[str]:
        if self._voices_cache is not None:
            return list(self._voices_cache)
        argv = self._base_command()
        if argv is None:
            self._last_error = "no SAPI runner (non-Windows?)"
            return []
        code, stdout, stderr = self._run_subprocess(argv, timeout=15.0)
        if code != 0 or not stdout:
            self._last_error = stderr or f"voices rc={code}"
            return []
        try:
            names = json.loads(stdout)
            if isinstance(names, list):
                self._voices_cache = [str(n) for n in names]
                return list(self._voices_cache)
        except json.JSONDecodeError:
            pass
        return []

    def synthesize(self, request: TTSRequest) -> bytes:
        self._last_error = None
        if request.cancel_event is not None and request.cancel_event.is_set():
            raise TTSCancelled()
        if not request.text.strip():
            raise TTSError("empty", "nothing to speak")
        import tempfile
        import os
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        voice = request.voice or self._voice
        try:
            argv = self._synth_command(
                request.text, voice, float(request.speed or 1.0),
                float(request.volume if request.volume is not None else 1.0),
                out_path)
            if argv is None:
                raise TTSError("no runner", "local TTS unavailable "
                                "(non-Windows)")
            code, _out, stderr = self._run_subprocess(
                argv, timeout=self._TIMEOUT_S)
            if code != 0:
                raise TTSError(stderr or f"rc={code}",
                               "local TTS failed" if code != 124
                               else "local TTS timed out")
            with open(out_path, "rb") as fh:
                data = fh.read()
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass
        if not data:
            raise TTSError("empty", "local TTS produced no audio")
        return data
