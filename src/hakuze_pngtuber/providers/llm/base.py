"""LLM provider interface + error taxonomy (Qt-free)."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Mapping


class LLMError(Exception):
    """Base error; `.user_message` is safe to show in the UI (no secrets)."""

    def __init__(self, message: str, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or "AI request failed"


class LLMCancelled(LLMError):
    def __init__(self):
        super().__init__("cancelled", "request cancelled")


class LLMAuthError(LLMError):
    def __init__(self, message: str = ""):
        super().__init__(message, "invalid or missing LLM API key")


class LLMConnectionError(LLMError):
    def __init__(self, message: str = ""):
        super().__init__(message, "cannot reach the LLM service (network?)")


class LLMTimeoutError(LLMError):
    def __init__(self, message: str = ""):
        super().__init__(message, "LLM request timed out")


class LLMModelError(LLMError):
    def __init__(self, message: str = ""):
        super().__init__(message, "LLM model unavailable (check model id)")


class LLMEmptyResponse(LLMError):
    def __init__(self):
        super().__init__("empty response", "the model returned an empty response")


class LLMTruncatedError(LLMError):
    """finish_reason == 'length': the token budget cut the answer short.

    Reasoning models (e.g. GLM thinking) spend tokens on hidden
    'reasoning_content' BEFORE the visible answer, so a small
    max_tokens can exhaust the budget mid-thought and the bubble only
    ever receives the first character or two."""

    def __init__(self, message: str = ""):
        super().__init__(message,
                         "answer cut off: max tokens reached - raise "
                         "'max tokens' in AI settings (reasoning models "
                         "think before answering and need a bigger budget)")


@dataclass
class LLMRequest:
    """One chat request: full message list + generation parameters."""
    messages: list[dict]                       # [{role, content}, ...]
    model: str | None = None                   # provider default if None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_s: float | None = None
    extra: Mapping = field(default_factory=dict)   # provider-specific passthrough
    cancel_event: threading.Event | None = None

    @property
    def cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


# deltas are plain str chunks; done carries the full text
StreamCallback = Callable[[str], None]


class BaseLLMProvider(ABC):
    """A chat-completion backend. Implementations must be thread-safe enough
    for one call at a time (the assistant serializes requests)."""

    name: str = "base"

    @abstractmethod
    def complete(self, request: LLMRequest) -> str:
        """Non-streaming completion; returns the full text."""

    @abstractmethod
    def stream(self, request: LLMRequest, on_delta: StreamCallback | None = None) -> str:
        """Streaming completion; returns the full text. `on_delta` receives
        incremental chunks. Must honor cancel_event between chunks."""

    @abstractmethod
    def test_connection(self, timeout_s: float = 10.0) -> tuple[bool, str]:
        """Cheap connectivity + auth probe. Returns (ok, message)."""
