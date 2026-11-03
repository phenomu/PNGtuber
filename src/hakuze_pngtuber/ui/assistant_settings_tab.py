"""AI Assistant settings tab (sections A–H of the spec).

Business logic lives in core; this file only reads/writes settings and
calls the controller. Credentials go through CredentialStore — the key
edit field is write-only (never displays a stored key).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.context_manager import VALID_LANGUAGES, VALID_RESPONSE_LENGTHS
from .widgets import LabeledSlider, LevelMeter, NumberBox, ToggleRow, section


class SecretEdit(QWidget):
    """Write-only credential field: shows masked placeholder, never the key.

    Placeholder reflects the storage status (keyring/env/session) — the
    value itself is never rendered."""

    changed = Signal(str)

    def __init__(self, store, name: str, placeholder: str, parent=None):
        super().__init__(parent)
        self._store = store
        self._name = name
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.Password)
        self._edit.setPlaceholderText(self._status_text())
        self._edit.textChanged.connect(self._on_text)
        row.addWidget(self._edit, 1)
        self._btn_clear = QPushButton("forget")
        self._btn_clear.setObjectName("flat")
        self._btn_clear.clicked.connect(self._clear)
        row.addWidget(self._btn_clear)
        self._hint = placeholder
        self._edit.setToolTip(placeholder)

    def _status_text(self) -> str:
        status = self._store.status(self._name)
        return {
            "keyring": "key stored (Windows Credential Manager) - enter to replace",
            "env": "key from environment variable - enter to override",
            "session": "key set this session (not persisted) - enter to replace",
            "missing": "no key stored - enter API key",
        }.get(status, "no key stored - enter API key")

    def _on_text(self, text: str) -> None:
        if text.strip():
            self.changed.emit(text.strip())

    def consume(self) -> str:
        """Return the typed key and clear the field (keeps the masked look)."""
        text = self._edit.text().strip()
        if text:
            self._edit.clear()
            self._edit.setPlaceholderText(self._status_text())
        return text

    def _clear(self) -> None:
        self._store.delete(self._name)
        self._edit.clear()
        self._edit.setPlaceholderText(self._status_text())

    def commit(self, text: str) -> bool:
        """Store the currently typed key. Returns True if persisted."""
        ok = self._store.set(self._name, text)
        self._edit.clear()
        self._edit.setPlaceholderText(self._status_text())
        return ok


class AssistantSettingsTab(QWidget):
    """All AI Companion settings, built into the existing SettingsWindow."""

    test_requested = Signal(str)      # "llm" | "stt" | "tts"
    clear_history_requested = Signal(str)  # "current" | "all"
    speak_test_requested = Signal(str)
    status_message = Signal(str)

    def __init__(self, settings, controller, contexts, credentials, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        self._log_cursor = 0  # log lines already shown in the view
        self._contexts = contexts
        self._creds = credentials
        self._pending_keys: dict[str, str] = {}

        from .context_manager_widget import ContextManagerWidget

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(12)

        # ---------------- A. control ----------------
        panel, col = section("assistant control")
        self.state_label = QLabel("STATE: OFF")
        self.state_label.setObjectName("stateLabel")
        col.addWidget(self.state_label)
        self.btn_toggle = QPushButton("enable AI companion (END)")
        self.btn_toggle.clicked.connect(self._toggle_assistant)
        col.addWidget(self.btn_toggle)
        self.btn_manual_listen = QPushButton("listen now (manual)")
        self.btn_manual_listen.setObjectName("flat")
        self.btn_manual_listen.clicked.connect(self._manual_listen)
        col.addWidget(self.btn_manual_listen)

        row = QHBoxLayout()
        row.addWidget(QLabel("global hotkey"))
        self.cmb_hotkey = QComboBox()
        for key in ("END", "HOME", "INSERT", "DELETE", "F6", "F7", "F8", "F9"):
            self.cmb_hotkey.addItem(key)
        self.cmb_hotkey.setCurrentText(str(settings.get("ai.hotkey", "END")))
        self.cmb_hotkey.currentTextChanged.connect(
            lambda v: self._save("ai.hotkey", v))
        row.addWidget(self.cmb_hotkey)
        col.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("wake mode"))
        self.cmb_wake = QComboBox()
        self.cmb_wake.addItem("energy (any speech starts listening)", "energy")
        self.cmb_wake.addItem("phrase verify (checks wake phrase via STT)", "phrase-verify")
        self.cmb_wake.addItem("manual (button only)", "manual")
        self._select_combo(self.cmb_wake, settings.get("ai.wake_mode", "energy"))
        self.cmb_wake.currentIndexChanged.connect(
            lambda: self._save("ai.wake_mode", self.cmb_wake.currentData()))
        row.addWidget(self.cmb_wake, 1)
        col.addLayout(row)

        self.ed_wake_phrase = QLineEdit(str(settings.get("ai.wake_phrase", "Hai GPT")))
        self.ed_wake_phrase.setToolTip("used by phrase-verify mode; energy mode ignores it")
        row = QHBoxLayout()
        row.addWidget(QLabel("wake phrase"))
        row.addWidget(self.ed_wake_phrase, 1)
        self.ed_wake_phrase.editingFinished.connect(
            lambda: self._save("ai.wake_phrase", self.ed_wake_phrase.text()))
        col.addLayout(row)

        self.sl_wake_sens = LabeledSlider(
            "wake sensitivity", 0.05, 1.0,
            float(settings.get("ai.wake_sensitivity", 0.5)))
        self.sl_wake_sens.value_changed.connect(
            lambda v: self._save("ai.wake_sensitivity", v))
        col.addWidget(self.sl_wake_sens)

        # mic boost for quiet mics (IEM): amplifies AI input only —
        # PNGtuber mouth detection keeps its own sensitivity settings
        self.sl_mic_gain = LabeledSlider(
            "mic gain (AI input boost, x)", 0.25, 8.0,
            float(settings.get("ai.mic_gain", 1.0)), decimals=2)
        self.sl_mic_gain.setToolTip(
            "multiplies assistant input level before wake detection; "
            "use for quiet mics (IEM/headset) — watch the level bar below "
            "and raise gain until the bar fills while you talk")
        self.sl_mic_gain.value_changed.connect(
            lambda v: self._save("ai.mic_gain", v))
        col.addWidget(self.sl_mic_gain)

        # live AI input level vs wake threshold (updated by the poll loop)
        self.wake_meter = LevelMeter()
        self.wake_meter.setMaximumHeight(10)
        col.addWidget(self.wake_meter)
        self.wake_level_label = QLabel("input: --  (enable assistant + talk)")
        self.wake_level_label.setObjectName("subtitle")
        self.wake_level_label.setWordWrap(True)
        col.addWidget(self.wake_level_label)

        self.tg_startup = ToggleRow(
            "enable assistant on app startup",
            bool(settings.get("ai.start_on_startup", False)))
        self.tg_startup.toggled.connect(
            lambda v: self._save("ai.start_on_startup", v))
        col.addWidget(self.tg_startup)
        root.addWidget(panel)

        # ---------------- B. OpenAI STT ----------------
        panel, col = section("openai stt")
        self.sec_openai = SecretEdit(credentials, "openai_api_key",
                                     "OpenAI API key (STT + optional TTS)")
        self.sec_openai.changed.connect(
            lambda t: self._key_changed("openai_api_key", t))
        col.addWidget(self.sec_openai)
        self.ed_stt_model = QLineEdit(str(settings.get("ai.stt_model",
                                                       "gpt-4o-mini-transcribe")))
        row = QHBoxLayout()
        row.addWidget(QLabel("stt model"))
        row.addWidget(self.ed_stt_model, 1)
        self.ed_stt_model.editingFinished.connect(
            lambda: self._save("ai.stt_model", self.ed_stt_model.text()))
        col.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("stt base url"))
        self.ed_stt_base = QLineEdit(
            str(settings.get("ai.stt_base_url", "")))
        self.ed_stt_base.setPlaceholderText(
            "empty = OpenAI direct; set your LLM gateway URL (e.g. "
            "https://api.ate.my.id/v1) to reuse the LLM key for STT")
        self.ed_stt_base.editingFinished.connect(
            lambda: self._save("ai.stt_base_url", self.ed_stt_base.text()))
        row.addWidget(self.ed_stt_base, 1)
        col.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("language"))
        self.cmb_stt_lang = QComboBox()
        self.cmb_stt_lang.addItem("auto", "")
        self.cmb_stt_lang.addItem("Indonesian (id)", "id")
        self.cmb_stt_lang.addItem("English (en)", "en")
        self._select_combo(self.cmb_stt_lang, settings.get("ai.stt_language", ""))
        self.cmb_stt_lang.currentIndexChanged.connect(
            lambda: self._save("ai.stt_language", self.cmb_stt_lang.currentData() or ""))
        row.addWidget(self.cmb_stt_lang)
        self.btn_test_stt = QPushButton("test connection")
        self.btn_test_stt.setObjectName("flat")
        self.btn_test_stt.clicked.connect(lambda: self.test_requested.emit("stt"))
        row.addWidget(self.btn_test_stt)
        col.addLayout(row)
        root.addWidget(panel)

        # ---------------- C. 9Router LLM ----------------
        panel, col = section("9router llm (openai-compatible)")
        self.sec_llm = SecretEdit(credentials, "llm_api_key",
                                  "9Router API key")
        self.sec_llm.changed.connect(lambda t: self._key_changed("llm_api_key", t))
        col.addWidget(self.sec_llm)
        self.ed_llm_base = QLineEdit(str(settings.get(
            "ai.llm_base_url", "https://api.ate.my.id/v1")))
        row = QHBoxLayout()
        row.addWidget(QLabel("base url"))
        row.addWidget(self.ed_llm_base, 1)
        self.ed_llm_base.editingFinished.connect(
            lambda: self._save("ai.llm_base_url", self.ed_llm_base.text()))
        col.addLayout(row)
        self.ed_llm_model = QLineEdit(str(settings.get("ai.llm_model", "")))
        self.ed_llm_model.setPlaceholderText("model id, e.g. gpt-4o-mini")
        row = QHBoxLayout()
        row.addWidget(QLabel("model id"))
        row.addWidget(self.ed_llm_model, 1)
        self.ed_llm_model.editingFinished.connect(
            lambda: self._save("ai.llm_model", self.ed_llm_model.text()))
        col.addLayout(row)
        self.sl_llm_temp = LabeledSlider(
            "temperature", 0.0, 2.0, float(settings.get("ai.llm_temperature", 0.7)))
        self.sl_llm_temp.value_changed.connect(
            lambda v: self._save("ai.llm_temperature", v))
        col.addWidget(self.sl_llm_temp)
        self.nb_llm_tokens = NumberBox(
            16, 4096, int(settings.get("ai.llm_max_tokens", 300)),
            suffix="tokens")
        row = QHBoxLayout()
        row.addWidget(QLabel("max tokens"))
        row.addWidget(self.nb_llm_tokens)
        row.addStretch(1)
        self.nb_llm_tokens.valueChanged.connect(
            lambda v: self._save("ai.llm_max_tokens", int(v)))
        col.addLayout(row)
        self.nb_llm_timeout = NumberBox(
            5, 300, int(settings.get("ai.llm_timeout_s", 60)), suffix="s")
        row = QHBoxLayout()
        row.addWidget(QLabel("timeout"))
        row.addWidget(self.nb_llm_timeout)
        row.addStretch(1)
        self.nb_llm_timeout.valueChanged.connect(
            lambda v: self._save("ai.llm_timeout_s", int(v)))
        col.addLayout(row)
        self.tg_llm_stream = ToggleRow(
            "streaming responses", bool(settings.get("ai.llm_streaming", True)))
        self.tg_llm_stream.toggled.connect(
            lambda v: self._save("ai.llm_streaming", v))
        col.addWidget(self.tg_llm_stream)
        self.tg_llm_reason = ToggleRow(
            "thinking model (slower, deep reasoning)",
            bool(settings.get("ai.llm_reasoning", False)))
        self.tg_llm_reason.toggled.connect(
            lambda v: self._save("ai.llm_reasoning", v))
        self.tg_llm_reason.setToolTip(
            "OFF: models like GLM 'thinking' answer instantly.\n"
            "ON: the model reasons first (long 'thinking' pause) and needs\n"
            "a much larger max tokens budget, or the answer gets cut off.")
        col.addWidget(self.tg_llm_reason)
        self.btn_test_llm = QPushButton("test connection")
        self.btn_test_llm.setObjectName("flat")
        self.btn_test_llm.clicked.connect(lambda: self.test_requested.emit("llm"))
        col.addWidget(self.btn_test_llm)
        root.addWidget(panel)

        # ---------------- D. TTS ----------------
        panel, col = section("tts")
        row = QHBoxLayout()
        row.addWidget(QLabel("provider"))
        self.cmb_tts = QComboBox()
        self.cmb_tts.addItem("Windows local TTS (SAPI, free)", "windows")
        self.cmb_tts.addItem("OpenAI TTS (API)", "openai")
        self._select_combo(self.cmb_tts, settings.get("ai.tts_provider", "windows"))
        self.cmb_tts.currentIndexChanged.connect(
            lambda: self._save("ai.tts_provider", self.cmb_tts.currentData()))
        row.addWidget(self.cmb_tts, 1)
        col.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("voice"))
        self.cmb_tts_voice = QComboBox()
        self.cmb_tts_voice.setEditable(True)
        self.cmb_tts_voice.setToolTip(
            "engine voice name (SAPI voices on Windows / OpenAI voices) — "
            "this selects WHO speaks, not the text; the test button speaks "
            "a fixed sample sentence")
        self.cmb_tts_voice.setPlaceholderText("provider default")
        self.cmb_tts_voice.currentTextChanged.connect(
            lambda v: self._save("ai.tts_voice", v))
        row.addWidget(self.cmb_tts_voice, 1)
        col.addLayout(row)
        # populate with the REAL voice list from the active provider
        try:
            voices = controller.tts_voices() if controller is not None else []
        except Exception:  # noqa: BLE001 - list is cosmetic
            voices = []
        if voices:
            self.cmb_tts_voice.blockSignals(True)
            self.cmb_tts_voice.clear()
            self.cmb_tts_voice.addItems(voices)
            self.cmb_tts_voice.setCurrentText(
                str(settings.get("ai.tts_voice", "")))
            self.cmb_tts_voice.blockSignals(False)
        self.sl_tts_speed = LabeledSlider(
            "speed", 0.25, 4.0, float(settings.get("ai.tts_speed", 1.0)))
        self.sl_tts_speed.value_changed.connect(
            lambda v: self._save("ai.tts_speed", v))
        col.addWidget(self.sl_tts_speed)
        self.sl_tts_volume = LabeledSlider(
            "volume", 0.0, 1.0, float(settings.get("ai.tts_volume", 1.0)))
        self.sl_tts_volume.value_changed.connect(
            lambda v: self._save("ai.tts_volume", v))
        col.addWidget(self.sl_tts_volume)
        self.btn_test_tts = QPushButton("test voice")
        self.btn_test_tts.setObjectName("flat")
        self.btn_test_tts.clicked.connect(
            lambda: self.test_requested.emit("tts"))
        col.addWidget(self.btn_test_tts)
        root.addWidget(panel)

        # ---------------- output mode ----------------
        panel, col = section("assistant output")
        row = QHBoxLayout()
        row.addWidget(QLabel("output mode"))
        self.cmb_output = QComboBox()
        self.cmb_output.addItem("text (bubble only)", "text")
        self.cmb_output.addItem("voice (speak only)", "voice")
        self.cmb_output.addItem("both (bubble + voice)", "both")
        self._select_combo(self.cmb_output, settings.get("ai.output_mode", "text"))
        self.cmb_output.currentIndexChanged.connect(
            lambda: self._save("ai.output_mode", self.cmb_output.currentData()))
        row.addWidget(self.cmb_output, 1)
        col.addLayout(row)
        self.tg_interrupt = ToggleRow(
            "allow user to interrupt while speaking",
            bool(settings.get("ai.interrupt_allow", True)))
        self.tg_interrupt.toggled.connect(
            lambda v: self._save("ai.interrupt_allow", v))
        col.addWidget(self.tg_interrupt)
        root.addWidget(panel)

        # ---------------- E. persona ----------------
        panel, col = section("global persona")
        self.ed_p_name = QLineEdit(str(settings.get("ai.persona_name", "Hakuze")))
        row = QHBoxLayout()
        row.addWidget(QLabel("name"))
        row.addWidget(self.ed_p_name, 1)
        self.ed_p_name.editingFinished.connect(
            lambda: self._save("ai.persona_name", self.ed_p_name.text()))
        col.addLayout(row)
        self.ed_p_personality = QLineEdit(str(settings.get(
            "ai.persona_personality", "")))
        self.ed_p_personality.setPlaceholderText("personality description")
        row = QHBoxLayout()
        row.addWidget(QLabel("personality"))
        row.addWidget(self.ed_p_personality, 1)
        self.ed_p_personality.editingFinished.connect(
            lambda: self._save("ai.persona_personality", self.ed_p_personality.text()))
        col.addLayout(row)
        self.ed_p_prompt = QLineEdit(str(settings.get("ai.persona_system_prompt", "")))
        self.ed_p_prompt.setPlaceholderText("extra global system prompt")
        row = QHBoxLayout()
        row.addWidget(QLabel("system prompt"))
        row.addWidget(self.ed_p_prompt, 1)
        self.ed_p_prompt.editingFinished.connect(
            lambda: self._save("ai.persona_system_prompt", self.ed_p_prompt.text()))
        col.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("language"))
        self.cmb_p_lang = QComboBox()
        self.cmb_p_lang.addItem("auto", "auto")
        self.cmb_p_lang.addItem("Indonesian", "id")
        self.cmb_p_lang.addItem("English", "en")
        self._select_combo(self.cmb_p_lang, settings.get("ai.persona_language", "id"))
        self.cmb_p_lang.currentIndexChanged.connect(
            lambda: self._save("ai.persona_language", self.cmb_p_lang.currentData()))
        row.addWidget(self.cmb_p_lang)
        row.addWidget(QLabel("tone"))
        self.ed_p_tone = QLineEdit(str(settings.get("ai.persona_tone", "cheerful")))
        row.addWidget(self.ed_p_tone)
        self.ed_p_tone.editingFinished.connect(
            lambda: self._save("ai.persona_tone", self.ed_p_tone.text()))
        col.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("style"))
        self.ed_p_style = QLineEdit(str(settings.get("ai.persona_speaking_style", "casual")))
        row.addWidget(self.ed_p_style)
        self.ed_p_style.editingFinished.connect(
            lambda: self._save("ai.persona_speaking_style", self.ed_p_style.text()))
        row.addWidget(QLabel("length"))
        self.cmb_p_len = QComboBox()
        for length in VALID_RESPONSE_LENGTHS:
            self.cmb_p_len.addItem(length)
        self.cmb_p_len.setCurrentText(str(settings.get("ai.persona_response_length", "short")))
        self.cmb_p_len.currentTextChanged.connect(
            lambda v: self._save("ai.persona_response_length", v))
        row.addWidget(self.cmb_p_len)
        col.addLayout(row)
        self.tg_p_emoji = ToggleRow(
            "use emoji", bool(settings.get("ai.persona_emoji", True)))
        self.tg_p_emoji.toggled.connect(lambda v: self._save("ai.persona_emoji", v))
        col.addWidget(self.tg_p_emoji)
        root.addWidget(panel)

        # ---------------- F. contexts ----------------
        self.context_widget = ContextManagerWidget(contexts, parent=self)
        self.context_widget.active_changed.connect(
            lambda: self.status_message.emit(
                f"active context: {self._contexts.active_context().name}"))
        root.addWidget(self.context_widget)

        # ---------------- G. bubble ----------------
        panel, col = section("dialogue bubble")
        self.tg_bubble = ToggleRow("enable bubble",
                                   bool(settings.get("ai.bubble_enabled", True)))
        self.tg_bubble.toggled.connect(lambda v: self._save("ai.bubble_enabled", v))
        col.addWidget(self.tg_bubble)
        self.sl_bubble_w = LabeledSlider(
            "width", 200, 900, float(settings.get("ai.bubble_width", 420)),
            decimals=0, suffix="px")
        self.sl_bubble_w.value_changed.connect(
            lambda v: self._save("ai.bubble_width", int(v)))
        col.addWidget(self.sl_bubble_w)
        self.sl_bubble_lines = LabeledSlider(
            "max lines", 1, 30, float(settings.get("ai.bubble_max_lines", 6)),
            decimals=0)
        self.sl_bubble_lines.value_changed.connect(
            lambda v: self._save("ai.bubble_max_lines", int(v)))
        col.addWidget(self.sl_bubble_lines)
        self.sl_bubble_font = LabeledSlider(
            "font size", 9, 32, float(settings.get("ai.bubble_font_size", 14)),
            decimals=0)
        self.sl_bubble_font.value_changed.connect(
            lambda v: self._save("ai.bubble_font_size", int(v)))
        col.addWidget(self.sl_bubble_font)
        self.sl_bubble_type = LabeledSlider(
            "typewriter speed", 0, 200, float(settings.get("ai.bubble_typewriter_ms", 24)),
            decimals=0, suffix="ms")
        self.sl_bubble_type.value_changed.connect(
            lambda v: self._save("ai.bubble_typewriter_ms", int(v)))
        col.addWidget(self.sl_bubble_type)
        self.sl_bubble_dur = LabeledSlider(
            "display duration", 0.5, 60.0, float(settings.get("ai.bubble_duration_s", 8.0)),
            suffix="s")
        self.sl_bubble_dur.value_changed.connect(
            lambda v: self._save("ai.bubble_duration_s", v))
        col.addWidget(self.sl_bubble_dur)
        self.sl_bubble_op = LabeledSlider(
            "opacity", 0.05, 1.0, float(settings.get("ai.bubble_opacity", 0.88)))
        self.sl_bubble_op.value_changed.connect(
            lambda v: self._save("ai.bubble_opacity", v))
        col.addWidget(self.sl_bubble_op)
        self.tg_bubble_voice = ToggleRow(
            "show bubble in voice-only mode",
            bool(settings.get("ai.bubble_voice_mode", False)))
        self.tg_bubble_voice.toggled.connect(
            lambda v: self._save("ai.bubble_voice_mode", v))
        col.addWidget(self.tg_bubble_voice)
        self.btn_bubble_preview = QPushButton("preview bubble")
        self.btn_bubble_preview.setObjectName("flat")
        self.btn_bubble_preview.clicked.connect(self._preview_bubble)
        col.addWidget(self.btn_bubble_preview)
        root.addWidget(panel)

        # ---------------- H. logs (what you said, session-only) ------------
        panel, col = section("logs")
        self.tg_logs = ToggleRow(
            "capture logs (session only, never saved to disk)",
            bool(settings.get("ai.log_enabled", False)))
        self.tg_logs.toggled.connect(self._on_log_toggle)
        self._controller.set_log_enabled(
            bool(settings.get("ai.log_enabled", False)))
        col.addWidget(self.tg_logs)
        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMaximumHeight(220)
        self.txt_logs.setPlaceholderText(
            "Enable capture, then talk to the assistant. Every pipeline "
            "stage appears here: wake trigger levels, what was heard "
            "(STT transcript), phrase matching, LLM/TTS results and errors.")
        self.txt_logs.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px;")
        col.addWidget(self.txt_logs)
        row = QHBoxLayout()
        self.btn_log_clear = QPushButton("clear log view")
        self.btn_log_clear.setObjectName("flat")
        self.btn_log_clear.clicked.connect(self._clear_log_view)
        row.addWidget(self.btn_log_clear)
        self.btn_log_ctx_history = QPushButton("clear current context history")
        self.btn_log_ctx_history.setObjectName("flat")
        self.btn_log_ctx_history.clicked.connect(self._clear_ctx_history)
        row.addWidget(self.btn_log_ctx_history)
        self.btn_log_all_history = QPushButton("clear all history")
        self.btn_log_all_history.setObjectName("flat")
        self.btn_log_all_history.clicked.connect(self._clear_all_history)
        row.addWidget(self.btn_log_all_history)
        col.addLayout(row)
        root.addWidget(panel)

        # ---------------- I. conversation ----------------
        panel, col = section("conversation")
        self.sl_hist = LabeledSlider(
            "history limit (turns)", 2, 50, float(settings.get("ai.history_max_turns", 12)),
            decimals=0)
        self.sl_hist.value_changed.connect(
            lambda v: self._save("ai.history_max_turns", int(v)))
        col.addWidget(self.sl_hist)
        self.tg_hist_persist = ToggleRow(
            "persist history across restarts",
            bool(settings.get("ai.history_persistent", False)))
        self.tg_hist_persist.toggled.connect(
            lambda v: self._save("ai.history_persistent", v))
        col.addWidget(self.tg_hist_persist)
        self.tg_hist_clear = ToggleRow(
            "clear history on exit",
            bool(settings.get("ai.history_clear_on_exit", False)))
        self.tg_hist_clear.toggled.connect(
            lambda v: self._save("ai.history_clear_on_exit", v))
        col.addWidget(self.tg_hist_clear)
        row = QHBoxLayout()
        self.btn_clear_ctx = QPushButton("clear current context history")
        self.btn_clear_ctx.setObjectName("flat")
        self.btn_clear_ctx.clicked.connect(
            lambda: self.clear_history_requested.emit("current"))
        row.addWidget(self.btn_clear_ctx, 1)
        self.btn_clear_all = QPushButton("clear ALL history")
        self.btn_clear_all.setObjectName("danger")
        self.btn_clear_all.clicked.connect(
            lambda: self.clear_history_requested.emit("all"))
        row.addWidget(self.btn_clear_all, 1)
        col.addLayout(row)
        root.addWidget(panel)

        root.addStretch(1)

    # ------------------------------------------------------------------
    @staticmethod
    def _select_combo(combo: QComboBox, data) -> None:
        idx = combo.findData(data)
        if idx < 0:
            idx = combo.findText(str(data))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _save(self, key: str, value) -> None:
        self._settings.set(key, value)
        self._settings.save()
        self._controller.settings_changed()
        self.status_message.emit(f"{key} = {value}")

    def _key_changed(self, name: str, text: str) -> None:
        self._pending_keys[name] = text

    def commit_keys(self) -> None:
        """Persist any typed API keys (called on test / toggle / app close)."""
        for name, edit in (("openai_api_key", self.sec_openai),
                           ("llm_api_key", self.sec_llm)):
            text = edit.consume()
            if text:
                self._store_key(name, text)
        self._pending_keys.clear()

    def _store_key(self, name: str, text: str) -> None:
        ok = self._creds.set(name, text)
        if not ok:
            self.status_message.emit(
                f"{name}: stored for this session only (no secure backend)")

    def _toggle_assistant(self) -> None:
        self.commit_keys()
        self._controller.toggle()

    def _manual_listen(self) -> None:
        self._controller.manual_listen()

    def _preview_bubble(self) -> None:
        self.speak_test_requested.emit("bubble_preview")

    def poll_wake_meter(self) -> None:
        """Live input level vs wake threshold (from the poll loop)."""
        rms, thr, on = self._controller.input_level()
        gain = float(self._settings.get("ai.mic_gain", 1.0))
        if not on:
            self.wake_meter.set_level(0.0)
            self.wake_level_label.setText(
                "input: --  (assistant OFF - press END or toggle to test mic)")
            return
        if rms is None:
            self.wake_meter.set_level(0.0)
            self.wake_level_label.setText(
                "input: no audio reaching assistant (mic muted? wrong "
                "device? mute is in the audio tab)")
            return
        self.wake_meter.set_level(min(1.0, rms / thr) if thr > 0 else 0.0)
        state = "OK - above threshold (listening)" if rms >= thr \
            else "too quiet - raise mic gain or wake sensitivity"
        self.wake_level_label.setText(
            f"input: {rms:.4f}  threshold: {thr:.4f}  gain: {gain:.2f}x"
            f"  ->  {state}")

    def _on_log_toggle(self, enabled: bool) -> None:
        """Apply immediately AND persist (settings_changed alone had the
        same snapshot bug class: save without the controller learning)."""
        self._settings.set("ai.log_enabled", bool(enabled))
        self._settings.save()
        self._controller.set_log_enabled(bool(enabled))
        self.status_message.emit(
            "log capture ON - talking now appears in the log" if enabled
            else "log capture OFF")
        if enabled:
            self._log_cursor = self._controller.log_line_count()

    # ---------------------------------------------------------------- logs
    def _clear_log_view(self) -> None:
        self._controller.clear_log()
        self.txt_logs.clear()

    def _clear_ctx_history(self) -> None:
        btn = QMessageBox.question(
            self, "Clear history",
            "Clear CURRENT context conversation history?\n"
            "(also clears the log view)")
        if btn == QMessageBox.Yes:
            self._controller.clear_history("current")
            self._clear_log_view()

    def _clear_all_history(self) -> None:
        btn = QMessageBox.question(
            self, "Clear history", "Clear ALL conversation history?\n"
            "(also clears the log view)")
        if btn == QMessageBox.Yes:
            self._controller.clear_history(None)
            self._clear_log_view()

    def poll_log_lines(self) -> None:
        """Called from the settings window poll: append new controller
        log lines to the view (only when capture is enabled)."""
        if not self._controller.log_enabled:
            return
        lines = self._controller.poll_log_lines(
            after=self._log_cursor)
        if lines:
            self.txt_logs.appendPlainText("\n".join(lines))
            sb = self.txt_logs.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._log_cursor = self._controller.log_line_count()

    # ------------------------------------------------------------------
    def set_assistant_state(self, state: str) -> None:
        self.state_label.setText(f"STATE: {state.upper()}")
        on = state.lower() != "off"
        self.btn_toggle.setText(
            "disable AI companion (END)" if on else "enable AI companion (END)")

    def show_test_result(self, what: str, ok: bool, message: str) -> None:
        icon = QMessageBox.Information if ok else QMessageBox.Warning
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(f"{what.upper()} test")
        box.setText(message if ok else f"FAILED: {message}")
        box.exec()

    def refresh_context_list(self) -> None:
        self.context_widget.reload()
