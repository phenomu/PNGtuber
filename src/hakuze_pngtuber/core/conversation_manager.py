"""Per-context conversation memory (Qt-free, bounded, session-only default).

Histories are kept strictly separate per context id. Optional persistence to
conversations.json next to the user settings (config_dir()).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from ..utils.platform_utils import config_dir

_ROLES = ("user", "assistant", "system")
_MAX_MSG_CHARS = 4000  # bound memory / tokens per message


class ConversationManager:
    """History store: {context_id: [ {role, content}, ... ]}."""

    def __init__(self, settings, save_fn=None, store_path: Path | None = None):
        self._settings = settings
        self._save = save_fn or (lambda: None)
        self._lock = threading.RLock()
        self._store: dict[str, list[dict]] = {}
        self._path = Path(store_path) if store_path \
            else config_dir() / "conversations.json"
        if bool(settings.get("ai.history_persistent", False)):
            self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(key, str) and isinstance(value, list):
                        self._store[key] = [
                            m for m in value
                            if isinstance(m, dict)
                            and m.get("role") in _ROLES
                            and isinstance(m.get("content"), str)
                        ]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass  # corrupt/missing file -> session-only memory

    def _persist(self) -> None:
        if not bool(self._settings.get("ai.history_persistent", False)):
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), suffix=".tmp",
                prefix="conversations_")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._store, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except OSError:
            pass  # persistence is best-effort, never fatal

    # ---------------------------------------------------------------- api
    def _limit(self) -> int:
        try:
            limit = int(self._settings.get("ai.history_max_turns", 12))
        except (TypeError, ValueError):
            limit = 12
        return max(2, min(50, limit)) * 2  # turns -> messages

    def history(self, context_id: str) -> list[dict]:
        with self._lock:
            return [dict(m) for m in self._store.get(context_id, [])]

    def append(self, context_id: str, role: str, content: str) -> None:
        if role not in _ROLES or not isinstance(content, str):
            return
        content = content.strip()[:_MAX_MSG_CHARS] or "."
        with self._lock:
            bucket = self._store.setdefault(context_id, [])
            bucket.append({"role": role, "content": content})
            limit = self._limit()
            if len(bucket) > limit:
                del bucket[:len(bucket) - limit]
            self._persist()

    def clear(self, context_id: str) -> None:
        with self._lock:
            self._store.pop(context_id, None)
            self._persist()

    def clear_all(self) -> None:
        with self._lock:
            self._store.clear()
            self._persist()

    def context_ids(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def shutdown(self) -> None:
        """clear_on_exit: wipe the store AND the persisted file."""
        if bool(self._settings.get("ai.history_clear_on_exit", False)):
            self.clear_all()
            try:
                if self._path.exists():
                    self._path.unlink()
            except OSError:
                pass
        elif bool(self._settings.get("ai.history_persistent", False)):
            self._persist()
