"""Main settings window: avatar, audio, animation, overlay, app tabs."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from pathlib import Path

from ..core.asset_manager import AssetManager
from ..core.audio_engine import AudioEngine
from ..core.avatar_controller import AvatarController
from ..core.settings_manager import SettingsManager
from ..core.speech_detector import Calibrator
from .avatar_overlay import AvatarOverlay
from .styles import STYLESHEET
from .widgets import LabeledSlider, LevelMeter, NumberBox, ToggleRow, section


def _short_path(path: str, limit: int = 32) -> str:
    """Compact a file path for preview labels: keep filename, trim middle."""
    if not path:
        return "placeholder"
    name = Path(path).name
    if len(name) <= limit:
        return name
    half = (limit - 3) // 2
    return name[:half] + "..." + name[-half:]


class SettingsWindow(QMainWindow):
    """Cyberpunk-styled control panel; owns overlay + audio + controller."""

    closing_to_tray = Signal()
    really_quit_requested = Signal()

    TABS = ("Avatar", "Audio", "Animation", "Overlay", "AI Assistant", "App")

    def __init__(self, settings: SettingsManager, controller: AvatarController,
                 engine: AudioEngine, assets: AssetManager, app_icon=None):
        super().__init__()
        self._settings = settings
        self._controller = controller
        self._engine = engine
        self._assets = assets
        self._overlay: AvatarOverlay | None = None
        self._calibrator: Calibrator | None = None
        self._calibration_phase = None  # None | "noise" | "speech"
        self._muted = False

        self.setWindowTitle("Hakuze PNGtuber")
        self.setMinimumSize(600, 560)
        self.resize(620, 760)
        self.setStyleSheet(STYLESHEET)

        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 10)
        layout.setSpacing(10)

        title = QLabel("HAKUZE PNGTUBER")
        title.setObjectName("title")
        subtitle = QLabel("mic-driven avatar overlay // v0.1.0")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        status_row = QHBoxLayout()
        self.state_label = QLabel("STATE: IDLE")
        self.state_label.setObjectName("stateLabel")
        self.placeholder_warning = QLabel()
        self.placeholder_warning.setObjectName("warningLabel")
        if self._assets.using_placeholder:
            self.placeholder_warning.setText("using placeholder art - set your PNGs in Avatar tab")
        status_row.addWidget(self.state_label)
        status_row.addStretch(1)
        status_row.addWidget(self.placeholder_warning, 0, Qt.AlignRight)
        layout.addLayout(status_row)

        self.tabs = QTabWidget()
        for name in self.TABS:
            page = QWidget()
            build = getattr(self, f"_build_{name.lower().replace(' ', '_')}_tab")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(10, 14, 10, 10)
            page_layout.setSpacing(12)
            build(page_layout)
            page_layout.addStretch(1)
            # scroll area per tab: on Windows (bigger fonts/DPI) the audio
            # tab content can exceed the window height and widgets overlapped
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, name)
        layout.addWidget(self.tabs, 1)

        self.statusBar().showMessage("ready")
        self.setCentralWidget(root)

        # poll loop: drains audio queue, feeds controller, updates meters
        self._sync_detector()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(20)

    def _sync_detector(self) -> None:
        """Push current audio settings into the controller's detector."""
        from ..core.speech_detector import SpeechParams
        from ..core.animation_engine import AnimParams
        p = SpeechParams.from_mapping({
            "rms_threshold": self._settings.get("audio.rms_threshold", 0.02),
            "noise_gate": self._settings.get("audio.noise_gate", 0.005),
            "attack_ms": self._settings.get("audio.attack_ms", 30),
            "release_ms": self._settings.get("audio.release_ms", 250),
            "silence_ms": self._settings.get("audio.silence_ms", 300),
            "min_speech_ms": self._settings.get("audio.min_speech_ms", 60),
        })
        self._controller.apply_params(speech=p)
        a = AnimParams.from_mapping({
            "enabled": self._settings.get("animation.enabled", True),
            "talking_lift_px": self._settings.get("animation.talking_lift_px", 10),
            "bounce_px": self._settings.get("animation.bounce_px", 12),
            "duration_ms": self._settings.get("animation.duration_ms", 180),
            "speed": self._settings.get("animation.speed", 1.0),
            "breathing": self._settings.get("animation.breathing", False),
        })
        self._controller.apply_params(anim=a)

    # ------------------------------------------------------------------ AV
    def _build_avatar_tab(self, L: QVBoxLayout) -> None:
        panel, col = section("character images")
        self.btn_idle_img = QPushButton("select idle PNG")
        self.btn_idle_img.setObjectName("flat")
        self.btn_talk_img = QPushButton("select talking PNG")
        self.btn_talk_img.setObjectName("flat")
        self.btn_idle_img.clicked.connect(lambda: self._pick_image("idle_image"))
        self.btn_talk_img.clicked.connect(lambda: self._pick_image("talking_image"))
        row = QHBoxLayout()
        row.addWidget(self.btn_idle_img, 1)
        row.addWidget(self.btn_talk_img, 1)
        col.addLayout(row)

        # live preview of current idle / talking art
        preview_row = QHBoxLayout()
        idle_box = QVBoxLayout()
        self.preview_idle = QLabel("IDLE")
        self.preview_idle.setObjectName("subtitle")
        self.preview_idle.setAlignment(Qt.AlignCenter)
        self.preview_idle_img = QLabel()
        self.preview_idle_img.setAlignment(Qt.AlignCenter)
        self.preview_idle_img.setFixedSize(150, 150)
        idle_box.addWidget(self.preview_idle_img)
        idle_box.addWidget(self.preview_idle)
        talk_box = QVBoxLayout()
        self.preview_talk = QLabel("TALKING")
        self.preview_talk.setObjectName("subtitle")
        self.preview_talk.setAlignment(Qt.AlignCenter)
        self.preview_talk_img = QLabel()
        self.preview_talk_img.setAlignment(Qt.AlignCenter)
        self.preview_talk_img.setFixedSize(150, 150)
        talk_box.addWidget(self.preview_talk_img)
        talk_box.addWidget(self.preview_talk)
        preview_row.addLayout(idle_box)
        preview_row.addLayout(talk_box)
        col.addLayout(preview_row)
        self._update_preview()
        L.addWidget(panel)

        panel, col = section("size & position")
        self.sl_scale = LabeledSlider("avatar scale", 0.05, 2.0,
                                      float(self._settings.get("avatar.scale", 0.55)))
        self.sl_scale.value_changed.connect(self._on_scale_changed)
        col.addWidget(self.sl_scale)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("position"))
        self.nb_pos_x = NumberBox(-10000, 10000, int(self._settings.get("avatar.pos_x", 120)))
        self.nb_pos_y = NumberBox(-10000, 10000, int(self._settings.get("avatar.pos_y", 120)))
        self.nb_pos_x.valueChanged.connect(lambda v: self._set_and_save("avatar.pos_x", v))
        self.nb_pos_y.valueChanged.connect(lambda v: self._set_and_save("avatar.pos_y", v))
        pos_row.addWidget(self.nb_pos_x)
        pos_row.addWidget(self.nb_pos_y)
        pos_row.addStretch(1)
        col.addLayout(pos_row)

        btn_row = QHBoxLayout()
        self.btn_edit_pos = QPushButton("edit position")
        self.btn_edit_pos.setObjectName("flat")
        self.btn_edit_pos.setCheckable(True)
        self.btn_edit_pos.toggled.connect(self._toggle_edit_mode)
        self.btn_save_pos = QPushButton("save position")
        self.btn_save_pos.setObjectName("flat")
        self.btn_save_pos.clicked.connect(self._save_position)
        btn_row.addWidget(self.btn_edit_pos, 1)
        btn_row.addWidget(self.btn_save_pos, 1)
        col.addLayout(btn_row)
        L.addWidget(panel)

        panel, col = section("look")
        self.sl_gray = LabeledSlider("idle grayscale intensity", 0.0, 1.0,
                                     float(self._settings.get("avatar.grayscale_intensity", 0.85)))
        self.sl_gray.value_changed.connect(self._on_grayscale_changed)
        col.addWidget(self.sl_gray)
        L.addWidget(panel)

    # ------------------------------------------------------------------ AU
    def _build_audio_tab(self, L: QVBoxLayout) -> None:
        panel, col = section("input device")
        self.cmb_device = QComboBox()
        self._refresh_devices()
        self.cmb_device.currentIndexChanged.connect(self._on_device_changed)
        col.addWidget(self.cmb_device)

        btn_dev_row = QHBoxLayout()
        self.btn_refresh_dev = QPushButton("refresh device list")
        self.btn_refresh_dev.setObjectName("flat")
        self.btn_refresh_dev.clicked.connect(self._refresh_devices_and_ui)
        btn_dev_row.addWidget(self.btn_refresh_dev)
        col.addLayout(btn_dev_row)

        mute_row = QHBoxLayout()
        self.btn_mute = QPushButton("mute microphone")
        self.btn_mute.setCheckable(True)
        self.btn_mute.toggled.connect(self._on_mute_toggled)
        mute_row.addWidget(self.btn_mute)
        col.addLayout(mute_row)

        self.meter = LevelMeter()
        col.addWidget(self.meter)
        self.threshold_mark = QLabel()
        col.addWidget(self.threshold_mark)

        btn_row = QHBoxLayout()
        self.btn_test_mic = QPushButton("test mic (5s)")
        self.btn_test_mic.setObjectName("flat")
        self.btn_test_mic.clicked.connect(self._test_mic)
        self.btn_calibrate = QPushButton("calibrate")
        self.btn_calibrate.clicked.connect(self._start_calibration)
        btn_row.addWidget(self.btn_test_mic, 1)
        btn_row.addWidget(self.btn_calibrate, 1)
        col.addLayout(btn_row)
        self.calibration_label = QLabel("")
        self.calibration_label.setObjectName("subtitle")
        self.calibration_label.setWordWrap(True)
        col.addWidget(self.calibration_label)
        L.addWidget(panel)

        panel, col = section("detection")
        self.sl_sens = LabeledSlider("sensitivity", 0.0, 1.0,
                                     float(self._settings.get("audio.sensitivity", 0.5)))
        self.sl_sens.value_changed.connect(self._on_sensitivity)
        self.sl_threshold = LabeledSlider("rms threshold", 0.001, 0.3,
                                          float(self._settings.get("audio.rms_threshold", 0.02)),
                                          decimals=3)
        self.sl_threshold.value_changed.connect(self._on_threshold)
        self.sl_gate = LabeledSlider("noise gate", 0.0, 0.1,
                                     float(self._settings.get("audio.noise_gate", 0.005)),
                                     decimals=3)
        self.sl_gate.value_changed.connect(lambda v: self._set_and_save("audio.noise_gate", v))
        col.addWidget(self.sl_sens)
        col.addWidget(self.sl_threshold)
        col.addWidget(self.sl_gate)
        L.addWidget(panel)

        panel, col = section("timing")
        self.sl_attack = LabeledSlider("attack time", 1, 500,
                                       int(self._settings.get("audio.attack_ms", 30)), decimals=0, suffix="ms")
        self.sl_release = LabeledSlider("release time", 1, 1000,
                                        int(self._settings.get("audio.release_ms", 250)), decimals=0, suffix="ms")
        self.sl_silence = LabeledSlider("silence before idle", 1, 2000,
                                        int(self._settings.get("audio.silence_ms", 300)), decimals=0, suffix="ms")
        for sl in (self.sl_attack, self.sl_release, self.sl_silence):
            col.addWidget(sl)
        self.sl_attack.value_changed.connect(lambda v: self._set_and_save("audio.attack_ms", v))
        self.sl_release.value_changed.connect(lambda v: self._set_and_save("audio.release_ms", v))
        self.sl_silence.value_changed.connect(lambda v: self._set_and_save("audio.silence_ms", v))
        L.addWidget(panel)

    # ------------------------------------------------------------------ AN
    def _build_animation_tab(self, L: QVBoxLayout) -> None:
        panel, col = section("talk animation")
        self.sl_lift = LabeledSlider("talking lift", 0, 50,
                                     float(self._settings.get("animation.talking_lift_px", 10)), decimals=0, suffix="px")
        self.sl_bounce = LabeledSlider("bounce intensity", 0, 50,
                                       float(self._settings.get("animation.bounce_px", 12)), decimals=0, suffix="px")
        self.sl_duration = LabeledSlider("duration", 30, 500,
                                         float(self._settings.get("animation.duration_ms", 180)), decimals=0, suffix="ms")
        self.sl_speed = LabeledSlider("speed", 0.25, 3.0,
                                      float(self._settings.get("animation.speed", 1.0)))
        for sl in (self.sl_lift, self.sl_bounce, self.sl_duration, self.sl_speed):
            col.addWidget(sl)
        self.sl_lift.value_changed.connect(lambda v: self._set_and_save("animation.talking_lift_px", v))
        self.sl_bounce.value_changed.connect(lambda v: self._set_and_save("animation.bounce_px", v))
        self.sl_duration.value_changed.connect(lambda v: self._set_and_save("animation.duration_ms", v))
        self.sl_speed.value_changed.connect(lambda v: self._set_and_save("animation.speed", v))
        L.addWidget(panel)

        panel, col = section("idle & master")
        self.tg_anim = ToggleRow("enable animation",
                                 bool(self._settings.get("animation.enabled", True)))
        self.tg_breath = ToggleRow("idle breathing (off by default)",
                                   bool(self._settings.get("animation.breathing", False)))
        self.tg_anim.toggled.connect(lambda v: self._set_and_save("animation.enabled", v))
        self.tg_breath.toggled.connect(lambda v: self._set_and_save("animation.breathing", v))
        col.addWidget(self.tg_anim)
        col.addWidget(self.tg_breath)
        L.addWidget(panel)

    # ------------------------------------------------------------------ OV
    def _build_overlay_tab(self, L: QVBoxLayout) -> None:
        panel, col = section("overlay window")
        self.tg_on_top = ToggleRow("always on top",
                                   bool(self._settings.get("overlay.always_on_top", True)))
        self.tg_clickthrough = ToggleRow("click-through (disable while editing)",
                                         bool(self._settings.get("overlay.click_through", True)))
        self.tg_on_top.toggled.connect(lambda v: self._set_and_save("overlay.always_on_top", v))
        self.tg_clickthrough.toggled.connect(lambda v: self._set_and_save("overlay.click_through", v))
        col.addWidget(self.tg_on_top)
        col.addWidget(self.tg_clickthrough)
        L.addWidget(panel)

        panel, col = section("control")
        row = QHBoxLayout()
        self.btn_start_overlay = QPushButton("start overlay")
        self.btn_start_overlay.clicked.connect(self._start_overlay)
        self.btn_stop_overlay = QPushButton("stop overlay")
        self.btn_stop_overlay.setObjectName("danger")
        self.btn_stop_overlay.clicked.connect(self._stop_overlay)
        self.btn_toggle_preview = QPushButton("toggle preview state")
        self.btn_toggle_preview.setObjectName("flat")
        self.btn_toggle_preview.clicked.connect(self._toggle_preview_state)
        row.addWidget(self.btn_start_overlay, 1)
        row.addWidget(self.btn_stop_overlay, 1)
        col.addLayout(row)
        col.addWidget(self.btn_toggle_preview)
        L.addWidget(panel)

    # ------------------------------------------------------------------ AP
    def _build_app_tab(self, L: QVBoxLayout) -> None:
        panel, col = section("application")
        self.tg_tray = ToggleRow("minimize to tray",
                                 bool(self._settings.get("app.minimize_to_tray", True)))
        self.tg_startmin = ToggleRow("start minimized",
                                     bool(self._settings.get("app.start_minimized", False)))
        self.tg_autostart = ToggleRow("start with Windows",
                                      bool(self._settings.get("app.start_with_windows", False)))
        self.tg_tray.toggled.connect(lambda v: self._set_and_save("app.minimize_to_tray", v))
        self.tg_startmin.toggled.connect(lambda v: self._set_and_save("app.start_minimized", v))
        self.tg_autostart.toggled.connect(self._toggle_autostart)
        col.addWidget(self.tg_tray)
        col.addWidget(self.tg_startmin)
        col.addWidget(self.tg_autostart)
        L.addWidget(panel)

        panel, col = section("danger zone")
        self.btn_reset = QPushButton("reset all settings")
        self.btn_reset.setObjectName("danger")
        self.btn_reset.clicked.connect(self._reset_settings)
        col.addWidget(self.btn_reset)
        L.addWidget(panel)

    # ------------------------------------------------------------------ AI
    def _build_ai_assistant_tab(self, L: QVBoxLayout) -> None:
        from .assistant_settings_tab import AssistantSettingsTab
        if getattr(self, "_assistant", None) is None:
            L.addWidget(QLabel("AI companion not initialized"))
            return
        tab = AssistantSettingsTab(
            self._settings, self._assistant, self._assistant_contexts,
            self._assistant_creds, parent=self)
        tab.test_requested.connect(self._on_ai_test)
        tab.clear_history_requested.connect(self._on_ai_clear_history)
        tab.speak_test_requested.connect(self._on_ai_speak_test)
        tab.status_message.connect(
            lambda msg: self.statusBar().showMessage(msg, 3000))
        tab.context_widget.active_changed.connect(self._on_ai_context_changed)
        self.ai_tab = tab
        L.addWidget(tab)

    def _on_ai_test(self, what: str) -> None:
        if getattr(self, "_assistant", None) is None:
            return
        if hasattr(self, "ai_tab"):
            # typed credentials must reach the store BEFORE the test runs
            self.ai_tab.commit_keys()
            self.ai_tab.refresh_context_list()
        if what == "llm":
            self._assistant.test_llm()
        elif what == "stt":
            self._assistant.test_stt()
        elif what == "tts":
            self._assistant.test_tts()

    def _on_ai_clear_history(self, which: str) -> None:
        if getattr(self, "_assistant", None) is None:
            return
        if which == "current":
            ctx = self._assistant_contexts.active_context()
            self._assistant.clear_history(ctx.id)
            self.statusBar().showMessage(f"history cleared: {ctx.name}", 3000)
        else:
            btn = QMessageBox.question(
                self, "Clear history", "Clear ALL conversation history?")
            if btn == QMessageBox.Yes:
                self._assistant.clear_history(None)
                self.statusBar().showMessage("all history cleared", 3000)

    def _on_ai_speak_test(self, what: str) -> None:
        if what == "bubble_preview" and self._overlay is not None:
            bubble = self._overlay.ensure_bubble()
            bubble.show_text("Halo! Aku Hakuze, companion kamu~ hehe "
                             "preview bubble like ini yaa!")

    def _on_ai_context_changed(self) -> None:
        if getattr(self, "_assistant", None) is not None:
            self._assistant.context_changed()
        if getattr(self, "_assistant_contexts", None) is not None:
            self._assistant_contexts.save()

    def attach_assistant(self, assistant, contexts, credentials) -> None:
        """Inject the assistant stack (built by main) into this window."""
        self._assistant = assistant
        self._assistant_contexts = contexts
        self._assistant_creds = credentials
        # rebuild the AI tab if the window is already constructed
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "AI Assistant":
                self.tabs.removeTab(i)
                break
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(10, 14, 10, 10)
        page_layout.setSpacing(12)
        self._build_ai_assistant_tab(page_layout)
        page_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "AI Assistant")

    def poll_assistant_events(self) -> None:
        """Called from _on_poll: drain controller events into UI."""
        assistant = getattr(self, "_assistant", None)
        if assistant is None:
            return
        if hasattr(self, "ai_tab"):
            self.ai_tab.poll_log_lines()
        for event in assistant.poll_events():
            kind = event.get("event")
            if kind == "state":
                if hasattr(self, "ai_tab"):
                    self.ai_tab.set_assistant_state(event.get("state", "off"))
                hook = getattr(self, "assistant_state_hook", None)
                if hook is not None:
                    try:
                        hook(event.get("state"))
                    except Exception:  # noqa: BLE001
                        pass
                self.statusBar().showMessage(
                    f"assistant: {event.get('state', '')}", 2000)
            elif kind in ("status", "error"):
                self.statusBar().showMessage(event.get("message", ""), 4000)
            elif kind == "test_result":
                if hasattr(self, "ai_tab"):
                    self.ai_tab.show_test_result(
                        event.get("what", "?"), bool(event.get("ok")),
                        str(event.get("message", "")))
            elif kind in ("bubble_show", "bubble_delta", "bubble_done",
                          "bubble_cancel"):
                self._assistant_bubble_event(kind, event)

    def _assistant_bubble_event(self, kind: str, event: dict) -> None:
        if self._overlay is None:
            return
        cfg_enabled = bool(self._settings.get("ai.bubble_enabled", True))
        mode = str(self._settings.get("ai.output_mode", "text"))
        voice_bubble = bool(self._settings.get("ai.bubble_voice_mode", False))
        show = cfg_enabled and (
            mode in ("text", "both") or (mode == "voice" and voice_bubble))
        if not show and kind != "bubble_cancel":
            return
        bubble = self._overlay.ensure_bubble()
        if kind == "bubble_show":
            bubble.show_text("")
        elif kind == "bubble_delta":
            bubble.append_delta(str(event.get("text", "")))
        elif kind == "bubble_done":
            bubble.complete_text(str(event.get("text", "")))
        elif kind == "bubble_cancel":
            bubble.hide_immediately()

    # ================================================================= poll
    def _on_poll(self) -> None:
        sample = None if self._muted else self._engine.poll()
        if sample is not None:
            level, t_ms = sample
            sens = float(self._settings.get("audio.sensitivity", 0.5))
            eff = level * (1.0 + 3.0 * sens)
            self._controller.feed_level(eff, t_ms)
            self._calibration_sample(eff)
        self.meter.set_level(self._controller.meter)
        thr = float(self._settings.get("audio.rms_threshold", 0.02))
        self.threshold_mark.setText(f"threshold ~ {thr:.3f}")
        state = "TALKING" if self._controller.talking else "IDLE"
        if self.state_label.text() != f"STATE: {state}":
            self.state_label.setText(f"STATE: {state}")
            if self._overlay is not None and self._overlay.isVisible():
                self._overlay.set_state(self._controller.talking)
        self.poll_assistant_events()

    # ================================================================= misc
    def _set_and_save(self, key: str, value) -> None:
        self._settings.set(key, value)
        self._settings.save()
        self.statusBar().showMessage(f"{key} = {value}", 2000)

    def _pick_image(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PNG", "", "Images (*.png *.PNG)")
        if path:
            self._set_and_save(f"avatar.{key}", path)
            self._assets.reload()
            if self._overlay is not None:
                self._overlay.reload_assets()
                self._overlay.update_display_size()
            self._update_preview()
            if not self._assets.using_placeholder:
                self.placeholder_warning.setText("")

    def _refresh_devices(self) -> None:
        self.cmb_device.blockSignals(True)
        self.cmb_device.clear()
        self.cmb_device.addItem("system default", None)
        devices = AudioEngine.list_devices()
        current = self._settings.get("audio.device_index")
        for dev in devices:
            self.cmb_device.addItem(dev["name"], dev["index"])
        if current is not None:
            idx = self.cmb_device.findData(current)
            if idx >= 0:
                self.cmb_device.setCurrentIndex(idx)
        self.cmb_device.blockSignals(False)

    def _on_device_changed(self, index: int) -> None:
        dev_index = self.cmb_device.itemData(index)
        self._set_and_save("audio.device_index", dev_index)
        ok = self._engine.switch_device(dev_index)
        if not ok:
            self.statusBar().showMessage(f"failed to open device: {self._engine.last_error}")
            QMessageBox.warning(self, "Microphone",
                                f"Could not open microphone:\n{self._engine.last_error}")

    def _on_scale_changed(self, v: float) -> None:
        self._set_and_save("avatar.scale", v)
        if self._overlay is not None:
            self._overlay.refresh_look()

    def _on_grayscale_changed(self, v: float) -> None:
        self._set_and_save("avatar.grayscale_intensity", v)
        if self._overlay is not None:
            self._overlay.refresh_look()
        self._update_preview()

    def _update_preview(self) -> None:
        """Show the currently selected idle/talking art (or placeholder)."""
        from .avatar_overlay import pil_to_qpixmap
        from ..utils.image_utils import desaturate
        try:
            idle, talk = self._assets.get_images()
        except Exception:
            return
        gray = desaturate(idle, float(self._settings.get("avatar.grayscale_intensity", 0.85)))
        for img, label in ((gray, self.preview_idle_img), (talk, self.preview_talk_img)):
            pm = pil_to_qpixmap(img).scaled(
                150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pm)
        idle_src = self._settings.get("avatar.idle_image", "") or "placeholder"
        talk_src = self._settings.get("avatar.talking_image", "") or "placeholder"
        self.preview_idle.setText("IDLE\n" + _short_path(idle_src))
        self.preview_talk.setText("TALKING\n" + _short_path(talk_src))

    def _refresh_devices_and_ui(self) -> None:
        self._refresh_devices()
        self.statusBar().showMessage("device list refreshed", 2000)

    def _on_mute_toggled(self, muted: bool) -> None:
        self._muted = muted
        if muted:
            self._engine.stop()
            self.btn_mute.setText("unmute microphone")
            self.statusBar().showMessage("microphone muted", 2000)
        else:
            dev = self._settings.get("audio.device_index")
            ok = self._engine.start(dev)
            self.btn_mute.setText("mute microphone")
            self.statusBar().showMessage(
                "microphone live" if ok else f"mic error: {self._engine.last_error}",
                3000)

    def _on_sensitivity(self, v: float) -> None:
        self._set_and_save("audio.sensitivity", v)

    def _on_threshold(self, v: float) -> None:
        self._set_and_save("audio.rms_threshold", v)
        self._sync_detector()

    def _test_mic(self) -> None:
        self.statusBar().showMessage("listening for 5 seconds...")
        QTimer.singleShot(5000, lambda: self.statusBar().showMessage("ready", 2000))

    # calibration ------------------------------------------------------
    def _start_calibration(self) -> None:
        if self._muted:
            self.calibration_label.setText("unmute the microphone first")
            return
        if not self._engine.running:
            dev = self._settings.get("audio.device_index")
            self._engine.start(dev)
        if not self._engine.running:
            self.calibration_label.setText(
                f"no microphone: {self._engine.last_error}")
            return
        self._calibrator = Calibrator()
        self._calibration_phase = "noise"
        self.calibration_label.setText("calibrating: stay SILENT (measuring noise)...")

    def _calibration_sample(self, level: float) -> None:
        if self._calibrator is None or self._calibration_phase is None:
            return
        if self._calibration_phase == "noise":
            self._calibrator.add_noise(level)
            if len(self._calibrator.noise_samples) >= 150:  # ~3s @ 20ms
                self._calibration_phase = "speech"
                self.calibration_label.setText("calibrating: SPEAK normally now...")
        elif self._calibration_phase == "speech":
            self._calibrator.add_speech(level)
            if len(self._calibrator.speech_samples) >= 200:  # ~4s
                self._finish_calibration()

    def _finish_calibration(self) -> None:
        suggested = self._calibrator.suggest() if self._calibrator else None
        self._calibration_phase = None
        self._calibrator = None
        if suggested is None:
            self.calibration_label.setText(
                "calibration failed: speech and noise too similar - adjust manually")
            return
        self.sl_threshold.set_value(float(suggested))
        self._set_and_save("audio.rms_threshold", float(suggested))
        self._sync_detector()
        self.calibration_label.setText(
            f"calibrated: threshold {suggested:.3f} - tweak it if needed")

    # overlay ----------------------------------------------------------
    def _ensure_overlay(self) -> AvatarOverlay:
        if self._overlay is None:
            self._overlay = AvatarOverlay(self._assets, self._controller.animation,
                                          self._settings)
            self._overlay.state_changed.connect(lambda t: self.statusBar().showMessage(
                "avatar: " + ("talking" if t else "idle"), 1500))
        return self._overlay

    def _start_overlay(self) -> None:
        ov = self._ensure_overlay()
        ov._apply_window_flags()
        ov.show()
        ov.set_state(self._controller.talking)
        self.statusBar().showMessage("overlay started - capture it in OBS", 3000)

    def _stop_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.stop()
            self.statusBar().showMessage("overlay stopped", 2000)

    def _toggle_preview_state(self) -> None:
        ov = self._ensure_overlay()
        ov.set_state(not ov._talking)
        ov.show()

    def _toggle_edit_mode(self, on: bool) -> None:
        ov = self._ensure_overlay()
        ov.set_edit_mode(on)
        ov.show()
        self.statusBar().showMessage(
            "edit mode ON - drag the avatar" if on else "edit mode off", 3000)

    def _save_position(self) -> None:
        if self._overlay is not None:
            self._overlay.save_position()
            self._settings.save()
            self.statusBar().showMessage(
                f"position saved ({self._overlay.x()},{self._overlay.y()})", 2000)

    def _toggle_autostart(self, on: bool) -> None:
        from ..utils.platform_utils import set_windows_startup
        ok = set_windows_startup(on)
        if not ok and on:
            QMessageBox.information(self, "Autostart",
                                    "Autostart works on Windows only.")
        self._set_and_save("app.start_with_windows", on)

    def _reset_settings(self) -> None:
        btn = QMessageBox.question(self, "Reset", "Reset all settings to defaults?")
        if btn == QMessageBox.Yes:
            self._settings.reset_to_defaults()
            self._settings.save()
            QMessageBox.information(self, "Reset", "Settings reset. Restart the app.")

    # lifecycle ----------------------------------------------------------
    def start_audio(self) -> None:
        dev = self._settings.get("audio.device_index")
        if not self._engine.start(dev):
            self.statusBar().showMessage(
                f"audio: {self._engine.last_error}", 10000)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if bool(self._settings.get("overlay.show_on_start", False)):
            self._start_overlay()

    def closeEvent(self, event) -> None:
        if bool(self._settings.get("app.minimize_to_tray", True)):
            event.ignore()
            self.hide()
            self.closing_to_tray.emit()
            return
        self._poll.stop()
        self._engine.stop()
        if self._overlay is not None:
            self._overlay.stop()
        self._settings.save()
        super().closeEvent(event)

    def really_quit(self) -> None:
        """Tray Quit: request full app termination (main cleans up)."""
        self.really_quit_requested.emit()
