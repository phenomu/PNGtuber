"""Wake word detection (Qt-free, local-first).

LIMITATION (documented per spec §6): no pretrained model recognizes an
arbitrary custom phrase like "Hai GPT". openWakeWord only recognizes
models it was trained on. This module therefore offers three REAL modes:

  energy        - local level gate: sustained speech above threshold
                  starts listening (works with any phrase, zero cost)
  phrase-verify - utterance is transcribed (STT) and checked for the wake
                  phrase; if present, the remainder after the phrase (or
                  the NEXT utterance) is the question. Costs one STT call
                  per utterance while ON — but only after speech energy
                  triggered, never continuously.
  manual        - no automatic trigger; the user triggers listening via
                  button/hotkey

openWakeWord is used when importable AND a matching model file exists
(user-supplied); otherwise mode falls back with `available_modes()`
reporting the truth.
"""
from __future__ import annotations

import re

try:
    import openwakeword as _oww  # type: ignore
    _OWW_ERROR = None
except Exception as _exc:  # noqa: BLE001 - optional dependency
    _oww = None
    _OWW_ERROR = str(_exc)


class WakeWordEngine:
    """Stateless checker + energy accumulator for the wake stage."""

    MODES = ("energy", "phrase-verify", "manual")

    def __init__(self, mode: str = "energy", phrase: str = "Hai GPT",
                 sensitivity: float = 0.5):
        self.mode = mode if mode in self.MODES else "energy"
        self.phrase = (phrase or "Hai GPT").strip()
        self.sensitivity = max(0.1, min(1.0, float(sensitivity)))

    # ---------------------------------------------------------- availability
    @staticmethod
    def openwakeword_available() -> tuple[bool, str]:
        """(available, reason). Honest reporting: no custom-model claim."""
        if _oww is None:
            return False, f"openwakeword not importable: {_OWW_ERROR}"
        return True, "openwakeword importable (custom model still required)"

    @classmethod
    def available_modes(cls) -> list[str]:
        modes = list(cls.MODES)
        if _oww is None:
            modes.remove("openwakeword") if "openwakeword" in modes else None
        return modes

    # ---------------------------------------------------------- energy stage
    def energy_threshold(self) -> float:
        """Start-listening RMS threshold derived from sensitivity."""
        # higher sensitivity -> lower threshold
        return 0.020 * (1.0 - 0.8 * (self.sensitivity - 0.1) / 0.9)

    # ---------------------------------------------------------- phrase stage
    _FUZZY_TOLERANCE = 2  # edits

    def phrase_matches(self, transcript: str) -> bool:
        """True if transcript contains the wake phrase (fuzzy prefix)."""
        if not transcript or not self.phrase:
            return False
        hay = self._normalize(transcript)
        needle = self._normalize(self.phrase)
        if not needle:
            return False
        if needle in hay:
            return True
        # fuzzy: allow small typos in the phrase (Levenshtein <= tolerance)
        for token_len in range(max(3, len(needle) - 3), len(needle) + 4):
            for start in range(0, max(1, len(hay) - token_len + 1)):
                cand = hay[start:start + token_len]
                if abs(len(cand) - len(needle)) > self._FUZZY_TOLERANCE:
                    continue
                if self._levenshtein(cand, needle) <= self._FUZZY_TOLERANCE:
                    return True
        return False

    def strip_phrase(self, transcript: str) -> str:
        """Remove the wake phrase from the transcript -> the raw question."""
        if not transcript:
            return ""
        hay = self._normalize(transcript)
        needle = self._normalize(self.phrase)
        if not needle:
            return transcript.strip()
        idx = hay.find(needle)
        if idx >= 0:
            # map back approximately: normalized is shorter; use word ratio
            ratio = len(transcript) / max(1, len(hay))
            cut = idx + len(needle)
            approx = int(cut * ratio)
            approx = min(approx, len(transcript))
            return transcript[approx:].strip(" ,.!?-:")
        return transcript.strip()

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^a-z0-9 ]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                               prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]
