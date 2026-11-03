"""OpenAI-compatible chat-completions provider (9Router / OpenAI / others).

The `openai` SDK is imported lazily so the module imports even without the
package installed (tests inject a fake client). Custom parameters ride in
`extra` and are sent via `extra_body` — servers that ignore unknown fields
simply drop them, and the SDK's TypeError on unknown kwargs is retried once
without extras.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from .base import (
    BaseLLMProvider,
    LLMCancelled,
    LLMConnectionError,
    LLMEmptyResponse,
    LLMError,
    LLMAuthError,
    LLMModelError,
    LLMRequest,
    LLMTimeoutError,
)



class OpenAICompatibleLLM(BaseLLMProvider):
    """Client for any OpenAI-compatible endpoint."""

    name = "openai-compatible"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 default_model: str = "", timeout_s: float = 60.0,
                 client_factory=None):
        self._api_key = api_key or ""
        self._base_url = (base_url or None)  # None -> OpenAI default
        self._default_model = default_model or ""
        self._timeout = float(timeout_s)
        self._client_factory = client_factory   # tests inject a fake
        self._client: Any | None = None
        self._client_lock = threading.Lock()

    # ---------------------------------------------------------------- client
    def _sdk(self):
        """Import the openai package on demand."""
        import openai  # noqa: PLC0415 - lazy by design
        return openai

    def _get_client(self):
        with self._client_lock:
            if self._client is None:
                if self._client_factory is not None:
                    self._client = self._client_factory(
                        api_key=self._api_key, base_url=self._base_url,
                        timeout=self._timeout)
                else:
                    openai = self._sdk()
                    self._client = openai.OpenAI(
                        api_key=self._api_key or "missing",
                        base_url=self._base_url,
                        timeout=self._timeout,
                        max_retries=1,
                    )
            return self._client

    def reset(self) -> None:
        with self._client_lock:
            self._client = None

    def reconfigure(self, api_key: str | None = None, base_url: str | None = None,
                    default_model: str | None = None,
                    timeout_s: float | None = None) -> None:
        """Hot-apply new credentials/model/URL; drops the cached client.

        Called by the controller on toggle/test/settings-change so values
        typed in the UI actually reach the provider without a restart.
        Unspecified (None) arguments keep their current values.
        """
        with self._client_lock:
            if api_key is not None:
                self._api_key = api_key
            if base_url is not None:
                self._base_url = base_url or None
            if default_model is not None:
                self._default_model = default_model
            if timeout_s is not None:
                self._timeout = float(timeout_s)
            self._client = None

    # ---------------------------------------------------------------- kwargs
    def _kwargs(self, request: LLMRequest, stream: bool) -> dict:
        kwargs: dict[str, Any] = {}
        model = request.model or self._default_model
        if not model:
            raise LLMModelError("no model configured")
        kwargs["model"] = model
        kwargs["messages"] = request.messages
        kwargs["stream"] = stream
        if request.temperature is not None:
            kwargs["temperature"] = float(request.temperature)
        if request.max_tokens is not None:
            kwargs["max_tokens"] = int(request.max_tokens)
        if request.timeout_s is not None:
            kwargs["timeout"] = float(request.timeout_s)
        if request.extra:
            kwargs["extra_body"] = dict(request.extra)
        return kwargs

    # ---------------------------------------------------------------- errors
    def _translate(self, exc: Exception) -> LLMError:
        openai = None
        try:
            openai = self._sdk()
        except Exception:  # noqa: BLE001 - SDK optional at import time
            pass
        if openai is not None:
            try:
                if isinstance(exc, openai.AuthenticationError):
                    return LLMAuthError(str(exc))
                if isinstance(exc, openai.NotFoundError):
                    return LLMModelError(str(exc))
                if isinstance(exc, openai.APITimeoutError):
                    return LLMTimeoutError(str(exc))
                if isinstance(exc, (openai.APIConnectionError,
                                    openai.APIStatusError)):
                    return LLMConnectionError(str(exc))
            except Exception:  # noqa: BLE001 - defensive
                pass
        text = str(exc)
        if "timeout" in text.lower():
            return LLMTimeoutError(text)
        if "401" in text or "unauthorized" in text.lower():
            return LLMAuthError(text)
        if "404" in text or "model" in text.lower() and "not" in text.lower():
            return LLMModelError(text)
        return LLMError(text)

    # ---------------------------------------------------------------- calls
    def complete(self, request: LLMRequest) -> str:
        if request.cancelled:
            raise LLMCancelled()
        kwargs = self._kwargs(request, stream=False)
        client = self._get_client()
        try:
            response = client.chat.completions.create(**kwargs)
        except TypeError:
            # server/SDK rejects an optional kwarg -> retry without extras
            kwargs.pop("temperature", None)
            kwargs.pop("max_tokens", None)
            kwargs.pop("extra_body", None)
            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - translated below
                raise self._translate(exc) from exc
        except Exception as exc:  # noqa: BLE001 - translated below
            raise self._translate(exc) from exc

        if request.cancelled:
            raise LLMCancelled()
        try:
            text = response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMEmptyResponse() from exc
        if not text.strip():
            raise LLMEmptyResponse()
        return text

    def stream(self, request: LLMRequest, on_delta=None) -> str:
        if request.cancelled:
            raise LLMCancelled()
        kwargs = self._kwargs(request, stream=True)
        client = self._get_client()
        try:
            chunk_iter = client.chat.completions.create(**kwargs)
            parts: list[str] = []
            for chunk in chunk_iter:
                if request.cancelled:
                    raise LLMCancelled()
                delta = ""
                try:
                    piece = chunk.choices[0].delta.content
                    if piece:
                        delta = piece
                except (AttributeError, IndexError, TypeError):
                    delta = ""
                if delta:
                    parts.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated below
            raise self._translate(exc) from exc

        if request.cancelled:
            raise LLMCancelled()
        text = "".join(parts)
        if not text.strip():
            raise LLMEmptyResponse()
        return text

    # ---------------------------------------------------------------- probe
    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        try:
            client = self._get_client()
            try:
                models = client.models.list()
                n = len(list(models))
                return True, f"connected ({n} models visible)"
            except Exception as exc:  # noqa: BLE001 - models may not exist
                # some proxies don't implement /models: fall back to a chat ping
                probe = LLMRequest(
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1, timeout_s=timeout_s)
                try:
                    self.complete(probe)
                    return True, "connected (chat ping ok)"
                except LLMError as exc2:
                    if isinstance(exc2, LLMEmptyResponse):
                        return True, "connected (chat ping ok)"
                    return False, exc2.user_message
        except LLMError as exc:
            return False, exc.user_message
        except Exception as exc:  # noqa: BLE001
            return False, self._translate(exc).user_message


class MockLLM(BaseLLMProvider):
    """Scripted provider for tests and offline development."""

    name = "mock"

    def __init__(self, responses: list[str] | None = None,
                 error: Exception | None = None, delay_s: float = 0.0):
        self.responses = list(responses or ["Mock reply."])
        self.error = error
        self.delay_s = delay_s
        self.calls: list[dict] = []
        self.cancel_after_chunks = None  # stream: cancel after N chunks

    def complete(self, request: LLMRequest) -> str:
        self.calls.append({"messages": request.messages, "stream": False})
        if self.error is not None:
            raise self.error
        if self.delay_s:
            time.sleep(self.delay_s)
        if request.cancelled:
            raise LLMCancelled()
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if not text.strip():
            raise LLMEmptyResponse()
        return text

    def stream(self, request: LLMRequest, on_delta=None) -> str:
        self.calls.append({"messages": request.messages, "stream": True})
        if self.error is not None:
            raise self.error
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if not text.strip():
            raise LLMEmptyResponse()
        parts: list[str] = []
        for i, ch in enumerate(text):
            if request.cancelled:
                raise LLMCancelled()
            if self.cancel_after_chunks is not None and \
                    i >= self.cancel_after_chunks:
                raise LLMCancelled()
            if self.delay_s:
                time.sleep(self.delay_s)
            parts.append(ch)
            if on_delta is not None:
                on_delta(ch)
        return "".join(parts)

    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        return (not isinstance(self.error, LLMAuthError)), \
            "mock connection ok" if self.error is None else "mock error"
