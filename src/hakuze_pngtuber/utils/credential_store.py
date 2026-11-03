"""Credential storage: Windows Credential Manager via keyring, env fallback.

Priority on read: keyring -> environment variable -> session memory.
Writes go to keyring when the backend works; otherwise session-only and
`stored_persistently()` reports False so the UI can warn the user.

API keys are NEVER logged and NEVER included in exception text. The only
surface where a key exists is the keyring itself and the provider client.
"""
from __future__ import annotations

import os
import threading

_SERVICE = "HakuzePNGtuber"
_NAMES = ("openai_api_key", "llm_api_key")  # llm_api_key = 9Router key


class CredentialStore:
    """Named secret storage with graceful degradation."""

    def __init__(self, env_prefix: str = "HAKUZE_", keyring_backend=None):
        self._env_prefix = env_prefix
        self._keyring = keyring_backend  # injectable for tests; None = auto
        self._lock = threading.Lock()
        self._session: dict[str, str] = {}
        self._keyring_available: bool | None = None
        if keyring_backend is None:
            self._keyring = self._import_keyring()

    @staticmethod
    def _import_keyring():
        try:
            import keyring  # noqa: PLC0415 - optional dependency
            return keyring
        except Exception:  # noqa: BLE001 - backend may be unusable headless
            return None

    # ------------------------------------------------------------------ API
    def _env_name(self, name: str) -> str:
        return self._env_prefix + name.upper()

    def get(self, name: str) -> str | None:
        if name not in _NAMES:
            return None
        # session first (explicitly set this run)
        with self._lock:
            if name in self._session:
                return self._session[name]
        # keyring
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(_SERVICE, name)
                if value:
                    return value
            except Exception:  # noqa: BLE001 - backend broken
                pass
        # environment
        return os.environ.get(self._env_name(name)) or None

    def set(self, name: str, value: str) -> bool:
        """Store a credential. Returns True if persisted in the keyring."""
        if name not in _NAMES or not value:
            return False
        with self._lock:
            self._session[name] = value
        if self._keyring is not None:
            try:
                self._keyring.set_password(_SERVICE, name, value)
                return True
            except Exception:  # noqa: BLE001 - backend read-only/headless
                pass
        return False

    def delete(self, name: str) -> None:
        with self._lock:
            self._session.pop(name, None)
        if self._keyring is not None:
            try:
                self._keyring.delete_password(_SERVICE, name)
            except Exception:  # noqa: BLE001 - may not exist
                pass

    def status(self, name: str) -> str:
        """'keyring' | 'env' | 'session' | 'missing' (never returns the key)."""
        if name not in _NAMES:
            return "missing"
        with self._lock:
            if name in self._session:
                return "session"
        if self._keyring is not None:
            try:
                if self._keyring.get_password(_SERVICE, name):
                    return "keyring"
            except Exception:  # noqa: BLE001
                pass
        if os.environ.get(self._env_name(name)):
            return "env"
        return "missing"

    def backend_name(self) -> str:
        if self._keyring is None:
            return "session-only"
        try:
            backend = getattr(self._keyring, "get_keyring", lambda: None)()
            return f"keyring:{type(backend).__name__}"
        except Exception:  # noqa: BLE001
            return "keyring:unknown"
