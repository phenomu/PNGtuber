"""LLM orchestration: persona+context prompt composition and history flow.

Pure logic over injected provider — the controller owns threads and Qt.
"""
from __future__ import annotations

from typing import Callable

from .context_manager import ContextConfig, ContextManager, Persona
from .conversation_manager import ConversationManager
from ..providers.llm.base import BaseLLMProvider, LLMRequest

_LENGTH_HINTS = {
    "short": "Keep replies very short: 1-3 sentences, livestream-friendly.",
    "medium": "Keep replies moderate: one short paragraph at most.",
    "long": "Replies may be detailed, but stay structured and readable.",
}


def build_system_prompt(persona: Persona, context: ContextConfig) -> str:
    """Final system instruction: global persona first, then active context.

    Persona is NEVER overridden by the context; context adds domain focus.
    """
    persona = persona.validated()
    context = context.validated()
    length = context.response_length or persona.response_length
    hint = _LENGTH_HINTS.get(length, _LENGTH_HINTS["short"])

    lang = context.language if context.language != "auto" else persona.language
    lang_name = {"id": "Indonesian", "en": "English"}.get(lang, "the user's language")

    parts: list[str] = []
    parts.append(
        f"You are {persona.name}, an AI companion avatar on a live stream "
        f"(a PNGtuber character). You talk with the streamer through voice "
        f"and a dialogue bubble."
    )
    if persona.system_prompt:
        parts.append(f"Global persona instructions (highest priority):\n{persona.system_prompt}")
    parts.append(f"Personality: {persona.personality}")
    parts.append(
        f"Speaking tone: {persona.tone}. Style: {persona.speaking_style}. "
        f"Respond in {lang_name} (mirror the user's language if it differs)."
    )
    if not persona.use_emoji:
        parts.append("Do not use emoji.")
    parts.append(hint)
    parts.append(
        "You are on a live stream: never send long lectures unless asked, "
        "never pretend to control the game or other applications, and never "
        "reveal API keys or credentials."
    )

    parts.append(f"\nACTIVE CONTEXT: {context.name}")
    if context.description:
        parts.append(context.description)
    if context.instructions:
        parts.append(f"Context instructions:\n{context.instructions}")
    if context.knowledge:
        parts.append(f"Context knowledge/notes:\n{context.knowledge}")
    if context.params:
        kv = ", ".join(f"{k}={v}" for k, v in context.params.items())
        parts.append(f"Context parameters: {kv}")
    if context.response_style:
        parts.append(f"Context response style: {context.response_style}")

    return "\n\n".join(parts)


class LLMEngine:
    """Compose prompt + history, call provider, store conversation."""

    def __init__(self, provider: BaseLLMProvider,
                 contexts: ContextManager,
                 conversations: ConversationManager,
                 temperature: float = 0.7, max_tokens: int = 300,
                 timeout_s: float = 60.0, streaming: bool = True,
                 reasoning: bool = True):
        self.provider = provider
        self.contexts = contexts
        self.conversations = conversations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.streaming = streaming
        self.reasoning = reasoning

    def apply_settings(self, temperature: float | None = None,
                       max_tokens: int | None = None,
                       timeout_s: float | None = None,
                       streaming: bool | None = None,
                       reasoning: bool | None = None) -> None:
        if temperature is not None:
            self.temperature = max(0.0, min(2.0, float(temperature)))
        if max_tokens is not None:
            self.max_tokens = max(16, min(4096, int(max_tokens)))
        if timeout_s is not None:
            self.timeout_s = max(5.0, min(300.0, float(timeout_s)))
        if streaming is not None:
            self.streaming = bool(streaming)
        if reasoning is not None:
            self.reasoning = bool(reasoning)

    def _messages(self, persona: Persona, context: ContextConfig,
                  user_text: str) -> list[dict]:
        history = self.conversations.history(context.id)
        messages = [{"role": "system",
                     "content": build_system_prompt(persona, context)}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def respond(self, user_text: str, on_delta=None, cancel_event=None) -> str:
        """Full turn: history + prompt -> provider -> store conversation.

        Raises LLM errors; caller decides error states. On cancellation the
        user message is NOT stored (the turn never completed).
        """
        persona = self.contexts.persona()
        context = self.contexts.active_context()
        extra: dict = {}
        if not self.reasoning:
            # reasoning models (GLM thinking, R1, ...) burn the max_tokens
            # budget on hidden 'reasoning_content' BEFORE the visible
            # answer, cutting the answer to 1-3 chars; disabling thinking
            # makes the answer stream fully and much faster
            extra["enable_thinking"] = False
        request = LLMRequest(
            messages=self._messages(persona, context, user_text),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout_s=self.timeout_s,
            cancel_event=cancel_event,
            extra=extra or None,
        )
        if self.streaming:
            text = self.provider.stream(request, on_delta=on_delta)
        else:
            text = self.provider.complete(request)
        self.conversations.append(context.id, "user", user_text)
        self.conversations.append(context.id, "assistant", text)
        return text

    def test_connection(self) -> tuple[bool, str]:
        return self.provider.test_connection(timeout_s=self.timeout_s)
