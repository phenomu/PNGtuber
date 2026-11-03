"""Assistant configuration snapshot read from SettingsManager (Qt-free).

API keys are deliberately NOT here — they live in CredentialStore
(Windows Credential Manager / env). This bundle carries only the
non-secret knobs, validated and clamped.
"""
from __future__ import annotations

from dataclasses import dataclass

_VALID_WAKE_MODES = ("energy", "phrase-verify", "manual")
_VALID_OUTPUT_MODES = ("text", "voice", "both")
_VALID_TTS_PROVIDERS = ("windows", "openai")


@dataclass
class AssistantSettings:
    # control
    wake_mode: str = "energy"
    wake_phrase: str = "Hai GPT"
    wake_sensitivity: float = 0.5
    mic_gain: float = 1.0           # input amplification for the assistant
    hotkey: str = "END"
    start_on_startup: bool = False
    output_mode: str = "text"
    # logging
    log_enabled: bool = False
    # llm (9Router)
    llm_base_url: str = "https://api.ate.my.id/v1"
    llm_model: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int = 300
    llm_timeout_s: float = 60.0
    llm_streaming: bool = True
    # stt (OpenAI)
    stt_model: str = "gpt-4o-mini-transcribe"
    stt_base_url: str = ""      # empty = api.openai.com; else route via gateway
    stt_language: str = ""          # "" = auto
    stt_timeout_s: float = 30.0
    # tts
    tts_provider: str = "windows"   # windows | openai
    tts_voice: str = ""
    tts_speed: float = 1.0
    tts_volume: float = 1.0
    tts_openai_model: str = "gpt-4o-mini-tts"
    tts_output_device: int | None = None
    # interruption
    interrupt_allow: bool = True
    # bubble
    bubble_enabled: bool = True
    bubble_width: int = 420
    bubble_max_lines: int = 6
    bubble_font_size: int = 14
    bubble_typewriter_ms: int = 24
    bubble_duration_s: float = 8.0
    bubble_pos_offset_x: int = 0
    bubble_pos_offset_y: int = 0
    bubble_animation_ms: int = 220
    bubble_opacity: float = 0.88
    bubble_voice_mode: bool = False   # show bubble in voice-only mode
    # conversation
    history_max_turns: int = 12
    history_persistent: bool = False
    history_clear_on_exit: bool = False

    # ----------------------------------------------------------------
    @classmethod
    def from_settings(cls, settings) -> "AssistantSettings":
        def g(key: str, default):
            value = settings.get(f"ai.{key}", default)
            return value if value is not None else default

        def gs(key: str, default: str, limit: int = 500) -> str:
            value = g(key, default)
            return str(value)[:limit] if isinstance(value, str) else default

        def gf(key: str, default: float, lo: float, hi: float) -> float:
            try:
                return max(lo, min(hi, float(g(key, default))))
            except (TypeError, ValueError):
                return default

        def gi(key: str, default: int, lo: int, hi: int) -> int:
            return int(round(gf(key, float(default), float(lo), float(hi))))

        def gb(key: str, default: bool) -> bool:
            value = g(key, default)
            return bool(value) if isinstance(value, (bool, int)) else default

        out = cls()
        mode = gs("wake_mode", "energy", 40)
        out.wake_mode = mode if mode in _VALID_WAKE_MODES else "energy"
        out.wake_phrase = gs("wake_phrase", "Hai GPT", 120).strip() or "Hai GPT"
        out.wake_sensitivity = gf("wake_sensitivity", 0.5, 0.05, 1.0)
        out.mic_gain = gf("mic_gain", 1.0, 0.25, 8.0)
        out.hotkey = gs("hotkey", "END", 24).strip().upper() or "END"
        out.start_on_startup = gb("start_on_startup", False)
        mode = gs("output_mode", "text", 16)
        out.output_mode = mode if mode in _VALID_OUTPUT_MODES else "text"
        out.log_enabled = gb("log_enabled", False)
        out.llm_base_url = gs("llm_base_url",
                              "https://api.ate.my.id/v1", 300).strip()
        out.llm_model = gs("llm_model", "", 200).strip()
        out.llm_temperature = gf("llm_temperature", 0.7, 0.0, 2.0)
        out.llm_max_tokens = gi("llm_max_tokens", 300, 16, 4096)
        out.llm_timeout_s = gf("llm_timeout_s", 60.0, 5.0, 300.0)
        out.llm_streaming = gb("llm_streaming", True)
        out.stt_model = gs("stt_model", "gpt-4o-mini-transcribe", 120).strip()
        out.stt_base_url = gs("stt_base_url", "", 300).strip()
        out.stt_language = gs("stt_language", "", 16).strip().lower()
        out.stt_timeout_s = gf("stt_timeout_s", 30.0, 5.0, 120.0)
        prov = gs("tts_provider", "windows", 40)
        out.tts_provider = prov if prov in _VALID_TTS_PROVIDERS else "windows"
        out.tts_voice = gs("tts_voice", "", 120)
        out.tts_speed = gf("tts_speed", 1.0, 0.25, 4.0)
        out.tts_volume = gf("tts_volume", 1.0, 0.0, 1.0)
        out.tts_openai_model = gs("tts_openai_model", "gpt-4o-mini-tts", 120).strip()
        dev = g("tts_output_device", None)
        out.tts_output_device = int(dev) if isinstance(dev, int) else None
        out.interrupt_allow = gb("interrupt_allow", True)
        out.bubble_enabled = gb("bubble_enabled", True)
        out.bubble_width = gi("bubble_width", 420, 200, 900)
        out.bubble_max_lines = gi("bubble_max_lines", 6, 1, 30)
        out.bubble_font_size = gi("bubble_font_size", 14, 9, 32)
        out.bubble_typewriter_ms = gi("bubble_typewriter_ms", 24, 0, 200)
        out.bubble_duration_s = gf("bubble_duration_s", 8.0, 0.5, 60.0)
        out.bubble_pos_offset_x = gi("bubble_pos_offset_x", 0, -2000, 2000)
        out.bubble_pos_offset_y = gi("bubble_pos_offset_y", 0, -2000, 2000)
        out.bubble_animation_ms = gi("bubble_animation_ms", 220, 50, 1000)
        out.bubble_opacity = gf("bubble_opacity", 0.88, 0.05, 1.0)
        out.bubble_voice_mode = gb("bubble_voice_mode", False)
        out.history_max_turns = gi("history_max_turns", 12, 2, 50)
        out.history_persistent = gb("history_persistent", False)
        out.history_clear_on_exit = gb("history_clear_on_exit", False)
        return out
