"""Dynamic AI context manager + global persona (Qt-free).

Contexts are user-created "modes" for the assistant (Minecraft, General,
Programming, ...). Each has stable IDs, instructions, knowledge, language
and response style. The global persona is independent of any context.

Storage: SettingsManager keys (flat, section "ai"):
    ai.contexts            list[dict]  (validated on load)
    ai.active_context_id   str
    ai.default_context_id  str
    ai.persona_*           persona fields
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

VALID_RESPONSE_LENGTHS = ("short", "medium", "long")
VALID_LANGUAGES = ("auto", "id", "en")

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _new_id() -> str:
    return "ctx_" + uuid.uuid4().hex[:12]


def _clean_str(value: Any, default: str = "", limit: int = 20000) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value[:limit]


@dataclass
class ContextConfig:
    """One assistant context. `params` holds free-form extras (e.g. Minecraft
    edition/version) — validated to a flat str/int/float/bool mapping."""

    id: str
    name: str
    description: str = ""
    instructions: str = ""
    knowledge: str = ""
    language: str = "auto"
    response_style: str = ""
    response_length: str = "short"
    params: dict = field(default_factory=dict)

    def validated(self) -> "ContextConfig":
        ctx_id = self.id if isinstance(self.id, str) and _ID_RE.match(self.id) \
            else _new_id()
        length = self.response_length if self.response_length in VALID_RESPONSE_LENGTHS \
            else "short"
        language = self.language if self.language in VALID_LANGUAGES else "auto"
        params: dict = {}
        if isinstance(self.params, Mapping):
            for key, value in self.params.items():
                if isinstance(key, str) and isinstance(
                        value, (str, int, float, bool)):
                    params[key[:64]] = value
        return replace(
            self,
            id=ctx_id,
            name=_clean_str(self.name, "Unnamed")[:120] or "Unnamed",
            description=_clean_str(self.description)[:2000],
            instructions=_clean_str(self.instructions, limit=20000),
            knowledge=_clean_str(self.knowledge, limit=200000),
            language=language,
            response_style=_clean_str(self.response_style)[:2000],
            response_length=length,
            params=params,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "knowledge": self.knowledge,
            "language": self.language,
            "response_style": self.response_style,
            "response_length": self.response_length,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "ContextConfig":
        if not isinstance(data, Mapping):
            return cls(id=_new_id(), name="Unnamed").validated()
        return cls(
            id=data.get("id") or _new_id(),
            name=data.get("name") or "Unnamed",
            description=data.get("description") or "",
            instructions=data.get("instructions") or "",
            knowledge=data.get("knowledge") or "",
            language=data.get("language") or "auto",
            response_style=data.get("response_style") or "",
            response_length=data.get("response_length") or "short",
            params=data.get("params") or {},
        ).validated()

    def clone(self, new_name: str) -> "ContextConfig":
        return replace(self.validated(), id=_new_id(), name=new_name[:120])


@dataclass
class Persona:
    """Global assistant persona — independent of the active context."""

    name: str = "Hakuze"
    personality: str = (
        "cheerful, cute, friendly and supportive anime-style companion; "
        "playful, slightly femboy-inspired energy; casual and warm"
    )
    system_prompt: str = ""
    language: str = "id"
    tone: str = "cheerful"
    speaking_style: str = "casual"
    use_emoji: bool = True
    response_length: str = "short"

    def validated(self) -> "Persona":
        length = self.response_length if self.response_length in VALID_RESPONSE_LENGTHS \
            else "short"
        language = self.language if self.language in VALID_LANGUAGES else "id"
        return replace(
            self,
            name=_clean_str(self.name, "Hakuze")[:60] or "Hakuze",
            personality=_clean_str(self.personality)[:2000],
            system_prompt=_clean_str(self.system_prompt, limit=20000),
            language=language,
            tone=_clean_str(self.tone)[:120],
            speaking_style=_clean_str(self.speaking_style)[:120],
            use_emoji=bool(self.use_emoji),
            response_length=length,
        )

    @classmethod
    def from_mapping(cls, data: Mapping) -> "Persona":
        return cls(
            name=data.get("name") or "Hakuze",
            personality=data.get("personality") or "",
            system_prompt=data.get("system_prompt") or "",
            language=data.get("language") or "id",
            tone=data.get("tone") or "cheerful",
            speaking_style=data.get("speaking_style") or "casual",
            use_emoji=data.get("use_emoji", True),
            response_length=data.get("response_length") or "short",
        ).validated()


_DEFAULT_MINECRAFT = ContextConfig(
    id="ctx_minecraft",
    name="Minecraft Context",
    description="Assistant mode for Minecraft gameplay help on stream.",
    instructions=(
        "You are helping a streamer while they play Minecraft. Give practical, "
        "correct gameplay help: recipes, crafting, mob behavior, redstone, "
        "enchanting, potions. Use the configured edition/version facts from "
        "params when answering. Keep answers compact - the player is mid-game."
    ),
    language="id",
    response_style="practical, direct, gamer-friendly",
    response_length="short",
    params={
        "edition": "Java Edition",
        "version": "1.21.x",
        "notes": "adjust edition/version in context settings",
    },
)

_DEFAULT_GENERAL = ContextConfig(
    id="ctx_general",
    name="General Conversation",
    description="Casual chat companion for just-chatting moments.",
    instructions=(
        "Casual conversation companion. Chat naturally, ask light follow-ups, "
        "keep the stream vibe positive. No topic restrictions."
    ),
    language="id",
    response_style="relaxed, conversational",
    response_length="short",
)


class ContextManager:
    """CRUD + activation for contexts; persists through SettingsManager."""

    def __init__(self, settings, save_fn: Callable[[], None] | None = None):
        # `settings`: SettingsManager-like (get/set). `save_fn`: persist hook.
        self._settings = settings
        self._save = save_fn or (lambda: None)
        self._lock = threading.RLock()
        self._load_or_seed()

    # ------------------------------------------------------------------ io
    def _load_or_seed(self) -> None:
        raw = self._settings.get("ai.contexts", [])
        contexts: list[ContextConfig] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        if isinstance(raw, list):
            for entry in raw:
                ctx = ContextConfig.from_dict(entry)
                if ctx.id in seen_ids:
                    ctx = replace(ctx, id=_new_id())
                base = ctx.name
                n = 2
                while ctx.name in seen_names and base:
                    ctx = replace(ctx, name=f"{base} ({n})"[:120])
                    n += 1
                seen_ids.add(ctx.id)
                seen_names.add(ctx.name)
                contexts.append(ctx)
        if not contexts:
            contexts = [_DEFAULT_MINECRAFT.validated(),
                        _DEFAULT_GENERAL.validated()]
        self._contexts = contexts

        default_id = self._settings.get("ai.default_context_id")
        if not any(c.id == default_id for c in contexts):
            default_id = contexts[0].id
        active_id = self._settings.get("ai.active_context_id")
        if not any(c.id == active_id for c in contexts):
            active_id = default_id
        self._default_id = default_id
        self._active_id = active_id
        self._flush()

    def _flush(self) -> None:
        """Write current state back to settings (caller persists via save())."""
        self._settings.set(
            "ai.contexts", [c.to_dict() for c in self._contexts])
        self._settings.set("ai.active_context_id", self._active_id)
        self._settings.set("ai.default_context_id", self._default_id)

    def save(self) -> None:
        with self._lock:
            self._flush()
        self._save()

    # ---------------------------------------------------------------- api
    @property
    def contexts(self) -> list[ContextConfig]:
        with self._lock:
            return list(self._contexts)

    def get(self, ctx_id: str) -> ContextConfig | None:
        with self._lock:
            for ctx in self._contexts:
                if ctx.id == ctx_id:
                    return ctx
        return None

    @property
    def active_id(self) -> str:
        with self._lock:
            return self._active_id

    @property
    def default_id(self) -> str:
        with self._lock:
            return self._default_id

    def active_context(self) -> ContextConfig:
        ctx = self.get(self._active_id)
        if ctx is None:  # defensive: always resolve
            with self._lock:
                self._active_id = self._default_id
            ctx = self.get(self._default_id) or self._contexts[0]
        return ctx

    def create(self, name: str, **fields) -> ContextConfig:
        with self._lock:
            name = _clean_str(name, "New Context")[:120] or "New Context"
            unique = name
            n = 2
            while any(c.name == unique for c in self._contexts):
                unique = f"{name} ({n})"[:120]
                n += 1
            ctx = ContextConfig(id=_new_id(), name=unique, **fields).validated()
            self._contexts.append(ctx)
            self._flush()
        return ctx

    def update(self, ctx_id: str, **fields) -> ContextConfig | None:
        with self._lock:
            for i, ctx in enumerate(self._contexts):
                if ctx.id != ctx_id:
                    continue
                merged = ctx.to_dict()
                for key, value in fields.items():
                    if key == "id":
                        continue  # ids are immutable
                    merged[key] = value
                if "name" in fields:
                    new_name = _clean_str(fields["name"])[:120] or ctx.name
                    if new_name != ctx.name and any(
                            c.name == new_name for c in self._contexts):
                        raise ValueError(f"context name already used: {new_name}")
                    merged["name"] = new_name
                updated = ContextConfig.from_dict(merged)
                self._contexts[i] = updated
                self._flush()
                return updated
        return None

    def delete(self, ctx_id: str) -> bool:
        """Delete a context. Active/default deletion falls back cleanly.
        The last remaining context cannot be deleted (always keep >= 1)."""
        with self._lock:
            if len(self._contexts) <= 1:
                return False
            if not any(c.id == ctx_id for c in self._contexts):
                return False
            self._contexts = [c for c in self._contexts if c.id != ctx_id]
            if self._active_id == ctx_id:
                self._active_id = self._default_id \
                    if any(c.id == self._default_id for c in self._contexts) \
                    else self._contexts[0].id
            if self._default_id == ctx_id:
                self._default_id = self._contexts[0].id
            if self._active_id == self._default_id and \
                    not any(c.id == self._active_id for c in self._contexts):
                self._active_id = self._contexts[0].id
            self._flush()
        return True

    def set_active(self, ctx_id: str) -> bool:
        with self._lock:
            if not any(c.id == ctx_id for c in self._contexts):
                return False
            self._active_id = ctx_id
            self._flush()
        return True

    def set_default(self, ctx_id: str) -> bool:
        with self._lock:
            if not any(c.id == ctx_id for c in self._contexts):
                return False
            self._default_id = ctx_id
            self._flush()
        return True

    # -------------------------------------------------------------- persona
    def persona(self) -> Persona:
        data = {
            "name": self._settings.get("ai.persona_name"),
            "personality": self._settings.get("ai.persona_personality"),
            "system_prompt": self._settings.get("ai.persona_system_prompt"),
            "language": self._settings.get("ai.persona_language"),
            "tone": self._settings.get("ai.persona_tone"),
            "speaking_style": self._settings.get("ai.persona_speaking_style"),
            "use_emoji": self._settings.get("ai.persona_emoji"),
            "response_length": self._settings.get("ai.persona_response_length"),
        }
        # drop explicit None (settings stubs return None for missing keys)
        data = {k: v for k, v in data.items() if v is not None}
        return Persona.from_mapping(data)

    def set_persona(self, persona: Persona) -> None:
        persona = persona.validated()
        with self._lock:
            self._settings.set("ai.persona_name", persona.name)
            self._settings.set("ai.persona_personality", persona.personality)
            self._settings.set("ai.persona_system_prompt", persona.system_prompt)
            self._settings.set("ai.persona_language", persona.language)
            self._settings.set("ai.persona_tone", persona.tone)
            self._settings.set("ai.persona_speaking_style", persona.speaking_style)
            self._settings.set("ai.persona_emoji", persona.use_emoji)
            self._settings.set("ai.persona_response_length", persona.response_length)
