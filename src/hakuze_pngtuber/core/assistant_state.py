"""Assistant state machine: validated transitions, Qt-free, thread-safe.

States per spec:
    OFF -> IDLE -> WAKE_WORD_DETECTED -> LISTENING -> TRANSCRIBING
        -> THINKING -> RESPONDING -> (SPEAKING) -> IDLE
END pressed in ANY state -> OFF. Errors recover to IDLE, never trap.
"""
from __future__ import annotations

import threading
from enum import Enum


class AssistantState(Enum):
    OFF = "off"
    IDLE = "idle"
    WAKE_WORD_DETECTED = "wake_word_detected"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    RESPONDING = "responding"
    SPEAKING = "speaking"
    ERROR = "error"


# Valid transitions. Every state may go to OFF (END = hard toggle).
_TRANSITIONS: dict[AssistantState, frozenset[AssistantState]] = {
    AssistantState.OFF: frozenset({AssistantState.IDLE}),
    AssistantState.IDLE: frozenset({
        AssistantState.WAKE_WORD_DETECTED,
        AssistantState.LISTENING,      # manual listen / energy trigger
        AssistantState.ERROR,
        AssistantState.OFF,
    }),
    AssistantState.WAKE_WORD_DETECTED: frozenset({
        AssistantState.LISTENING,
        AssistantState.IDLE,            # wake not confirmed -> back to idle
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.LISTENING: frozenset({
        AssistantState.TRANSCRIBING,
        AssistantState.IDLE,            # timeout / aborted / empty utterance
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.TRANSCRIBING: frozenset({
        AssistantState.THINKING,
        AssistantState.IDLE,            # STT failed / empty transcript
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.THINKING: frozenset({
        AssistantState.RESPONDING,
        AssistantState.IDLE,            # LLM failed
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.RESPONDING: frozenset({
        AssistantState.SPEAKING,        # voice/both output mode
        AssistantState.IDLE,            # text mode: done
        AssistantState.LISTENING,       # user interrupted with new speech
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.SPEAKING: frozenset({
        AssistantState.IDLE,
        AssistantState.LISTENING,       # barge-in interruption
        AssistantState.OFF,
        AssistantState.ERROR,
    }),
    AssistantState.ERROR: frozenset({
        AssistantState.IDLE,            # auto-recover
        AssistantState.OFF,
    }),
}


def can_transition(current: AssistantState, new: AssistantState) -> bool:
    return new in _TRANSITIONS.get(current, frozenset())


class AssistantStateMachine:
    """Thread-safe state holder with an optional change listener."""

    def __init__(self, listener=None):
        self._state = AssistantState.OFF
        self._lock = threading.Lock()
        self._listener = listener

    @property
    def state(self) -> AssistantState:
        with self._lock:
            return self._state

    def is_on(self) -> bool:
        return self.state is not AssistantState.OFF

    def transition(self, new: AssistantState) -> bool:
        """Attempt a transition. Returns False (state unchanged) if invalid."""
        with self._lock:
            if new is self._state:
                return True  # idempotent
            if new not in _TRANSITIONS.get(self._state, frozenset()):
                return False
            old = self._state
            self._state = new
        if self._listener is not None:
            try:
                self._listener(old, new)
            except Exception:  # noqa: BLE001 - listener must never break FSM
                pass
        return True

    def force_off(self) -> None:
        """END pressed: OFF from any state, always succeeds."""
        self.transition(AssistantState.OFF)

    def recover(self) -> bool:
        """From ERROR back to IDLE (assistant stays ON)."""
        return self.transition(AssistantState.IDLE)

    def reset(self) -> None:
        with self._lock:
            self._state = AssistantState.OFF
