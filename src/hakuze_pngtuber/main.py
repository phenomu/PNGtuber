"""Application entry point: wires settings, audio, controller, overlay, tray."""
from __future__ import annotations

import signal
import sys

from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .core.asset_manager import AssetManager
from .core.audio_engine import AudioEngine
from .core.avatar_controller import AvatarController
from .core.settings_manager import SettingsManager
from .ui.settings_window import SettingsWindow
from .utils.platform_utils import config_dir


def _app_icon() -> QIcon:
    # simple generated icon: cyan dot on dark rounded square
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(11, 14, 23, 255))
    p.setPen(QColor(33, 230, 255, 255))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor(185, 107, 255, 255))
    p.drawEllipse(20, 20, 24, 24)
    p.end()
    return QIcon(pm)


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl-C works while Qt loop runs

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray owns the lifetime
    app.setApplicationName("Hakuze PNGtuber")
    app.setApplicationDisplayName("Hakuze PNGtuber")
    icon = _app_icon()
    app.setWindowIcon(icon)

    try:
        settings = SettingsManager(user_path=config_dir() / "settings.json")
    except Exception as exc:  # noqa: BLE001 - fatal, must be readable
        print(f"Fatal: cannot load settings: {exc}", file=sys.stderr)
        return 2

    assets = AssetManager(settings)
    controller = AvatarController(assets=assets)
    engine = AudioEngine()

    # --- AI companion stack (failures never break the PNGtuber core) ------
    assistant = None
    contexts = None
    credentials = None
    hotkeys = None
    try:
        from .core.assistant_controller import AssistantController
        from .core.context_manager import ContextManager
        from .core.conversation_manager import ConversationManager
        from .core.llm_engine import LLMEngine
        from .core.tts_engine import TTSEngine
        from .providers.llm.openai_compatible import OpenAICompatibleLLM
        from .providers.stt.openai_stt import OpenAISTT
        from .providers.tts.base import MockTTS
        from .providers.tts.openai_tts import OpenAITTS, WindowsSapiTTS
        from .core.assistant_config import AssistantSettings
        from .utils.credential_store import CredentialStore
        from .utils.global_hotkey import HotkeyManager

        credentials = CredentialStore()
        contexts = ContextManager(settings, save_fn=settings.save)
        conversations = ConversationManager(
            settings, save_fn=settings.save)

        ai_cfg = AssistantSettings.from_settings(settings)
        llm_provider = OpenAICompatibleLLM(
            api_key=credentials.get("llm_api_key"),
            base_url=ai_cfg.llm_base_url or None,
            default_model=ai_cfg.llm_model,
            timeout_s=ai_cfg.llm_timeout_s)
        llm = LLMEngine(
            provider=llm_provider, contexts=contexts,
            conversations=conversations,
            temperature=ai_cfg.llm_temperature,
            max_tokens=ai_cfg.llm_max_tokens,
            timeout_s=ai_cfg.llm_timeout_s,
            streaming=ai_cfg.llm_streaming)

        stt_provider = OpenAISTT(
            api_key=credentials.get("openai_api_key"),
            model=ai_cfg.stt_model)

        if ai_cfg.tts_provider == "openai":
            tts_provider = OpenAITTS(
                api_key=credentials.get("openai_api_key"),
                model=ai_cfg.tts_openai_model)
        else:
            tts_provider = WindowsSapiTTS(voice=ai_cfg.tts_voice or None)
        tts = TTSEngine(provider=tts_provider, volume=ai_cfg.tts_volume,
                        device_index=ai_cfg.tts_output_device)

        assistant = AssistantController(
            settings=settings, contexts=contexts,
            conversations=conversations, llm_engine=llm,
            stt_provider=stt_provider, tts_engine=tts,
            credentials=credentials)
        assistant.start()
        # raw mic tap: enabled/disabled by the controller itself (ON/OFF)
        engine.set_tap(assistant.feed_audio_block)
    except Exception as exc:  # noqa: BLE001 - core app must survive
        print(f"AI companion unavailable: {exc}", file=sys.stderr)
        assistant = None

    win = SettingsWindow(settings, controller, engine, assets)
    win.setWindowIcon(icon)
    win.start_audio()
    if assistant is not None:
        win.attach_assistant(assistant, contexts, credentials)

    # --- global hotkey (END) ----------------------------------------------
    if assistant is not None:
        hotkeys = HotkeyManager()
        hotkey_key = str(settings.get("ai.hotkey", "END"))
        ok = hotkeys.register(hotkey_key, assistant.toggle)
        if not ok:
            print(f"Hotkey {hotkey_key} not registered: {hotkeys.last_error}",
                  file=sys.stderr)

    # tray ------------------------------------------------------------
    tray = QSystemTrayIcon(icon, app)
    tray_menu = QMenu()
    act_show = QAction("Open settings", tray_menu)
    act_show.triggered.connect(win.showNormal)

    # AI toggle + quick context switcher in the tray
    if assistant is not None:
        act_ai = QAction("AI companion: OFF", tray_menu)
        act_ai.setCheckable(True)

        def _sync_ai_label(state=None):
            on = assistant.is_on
            act_ai.setChecked(on)
            act_ai.setText(f"AI companion: {'ON' if on else 'OFF'}")

        act_ai.triggered.connect(lambda checked: assistant.toggle())
        tray_menu.addAction(act_show)
        tray_menu.addAction(act_ai)
        tray_menu.addSeparator()

        ctx_menu = QMenu("Active context", tray_menu)

        def _rebuild_ctx_menu():
            ctx_menu.clear()
            for ctx in contexts.contexts:
                act = QAction(ctx.name, ctx_menu)
                act.setCheckable(True)
                act.setChecked(ctx.id == contexts.active_id)

                def _pick(checked=False, _id=ctx.id):
                    if contexts.set_active(_id):
                        contexts.save()
                        assistant.context_changed()
                        _rebuild_ctx_menu()

                act.triggered.connect(_pick)
                ctx_menu.addAction(act)

        _rebuild_ctx_menu()
        tray_menu.addMenu(ctx_menu)
        tray_menu.addSeparator()

        def _on_state_event(state: str):
            # invoked via poll of assistant events in win; keep tray synced
            _sync_ai_label()

    act_quit = QAction("Quit", tray_menu)
    act_quit.triggered.connect(win.really_quit)
    tray_menu.addAction(act_quit)
    tray.setContextMenu(tray_menu)
    tray.setToolTip("Hakuze PNGtuber")
    tray.activated.connect(lambda reason: win.showNormal()
                            if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()

    win.closing_to_tray.connect(lambda: tray.showMessage(
        "Hakuze PNGtuber", "Minimized to tray - double-click to reopen",
        QSystemTrayIcon.Information, 2500))

    def _full_quit() -> None:
        """Tray Quit: stop everything and exit the event loop for real."""
        win._poll.stop()
        if assistant is not None:
            try:
                assistant.shutdown(wait=True)
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
        if hotkeys is not None:
            hotkeys.shutdown()
        engine.stop()
        if win._overlay is not None:
            win._overlay.stop()
        settings.save()
        if assistant is not None:
            try:
                assistant_shutdown_contexts = conversations  # noqa: F841
                conversations.shutdown()
            except Exception:  # noqa: BLE001
                pass
        tray.hide()
        QApplication.quit()

    win.really_quit_requested.connect(_full_quit)

    if not bool(settings.get("app.start_minimized", False)):
        win.show()

    # start the assistant automatically when configured
    if assistant is not None and bool(settings.get("ai.start_on_startup", False)):
        assistant.set_on()

    # keep the tray AI label synced: window poll drains events (single path)
    if assistant is not None:
        win.assistant_state_hook = _sync_ai_label

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
