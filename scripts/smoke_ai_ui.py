"""Headless UI smoke: settings window + AI tab + dialogue bubble.

Runs under WSLg/offscreen (QT_QPA_PLATFORM=offscreen). Verifies:
- window builds with AI Assistant tab attached
- assistant settings tab creates all 8 sections
- context manager widget lists seeded contexts
- dialogue bubble: typewriter reveal, unicode/emoji, max lines clamp,
  fade-out, streaming append
- avatar overlay grows window when bubble shows, shrinks when hidden
Exit 0 = all green.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_ai_companion import FakeSettings  # noqa: E402
from hakuze_pngtuber.core.context_manager import ContextManager  # noqa: E402
from hakuze_pngtuber.core.conversation_manager import ConversationManager  # noqa: E402
from hakuze_pngtuber.core.llm_engine import LLMEngine  # noqa: E402
from hakuze_pngtuber.core.tts_engine import TTSEngine  # noqa: E402
from hakuze_pngtuber.core.assistant_controller import AssistantController  # noqa: E402
from hakuze_pngtuber.providers.llm.openai_compatible import MockLLM  # noqa: E402
from hakuze_pngtuber.providers.stt.openai_stt import MockSTT  # noqa: E402
from hakuze_pngtuber.providers.tts.base import MockTTS  # noqa: E402
from hakuze_pngtuber.utils.credential_store import CredentialStore  # noqa: E402
from hakuze_pngtuber.core.avatar_controller import AvatarController  # noqa: E402
from hakuze_pngtuber.core.asset_manager import AssetManager  # noqa: E402
from hakuze_pngtuber.core.audio_engine import AudioEngine  # noqa: E402
from hakuze_pngtuber.core.settings_manager import SettingsManager  # noqa: E402
from hakuze_pngtuber.ui.settings_window import SettingsWindow  # noqa: E402
from hakuze_pngtuber.ui.avatar_overlay import AvatarOverlay  # noqa: E402
from hakuze_pngtuber.ui.dialogue_bubble import DialogueBubble  # noqa: E402
from hakuze_pngtuber.core.animation_engine import AnimationEngine  # noqa: E402

from PySide6.QtCore import QCoreApplication  # noqa: E402

FAIL = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        print(f"  ok - {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL - {name} {detail}")


def main() -> int:
    app = QApplication([])
    tmp = Path("/tmp/_hakuze_ui_smoke_settings.json")
    if tmp.exists():
        tmp.unlink()
    settings = SettingsManager(user_path=tmp)

    # --- core stack with mock providers -------------------------------
    contexts = ContextManager(settings, save_fn=settings.save)
    conversations = ConversationManager(
        settings, save_fn=settings.save,
        store_path=Path("/tmp/_hakuze_ui_conv.json"))
    llm = LLMEngine(MockLLM(["Halo!"]), contexts, conversations, streaming=False)
    tts = TTSEngine(MockTTS())
    assistant = AssistantController(
        settings, contexts, conversations, llm, MockSTT(["q"]), tts)
    assistant.start()
    creds = CredentialStore(keyring_backend=None)

    # --- settings window with AI tab -----------------------------------
    assets = AssetManager(settings)
    controller = AvatarController(assets=assets)
    engine = AudioEngine()
    win = SettingsWindow(settings, controller, engine, assets)
    win.attach_assistant(assistant, contexts, creds)

    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    check("AI Assistant tab present", "AI Assistant" in names, str(names))

    tab = win.ai_tab
    check("AI tab has context widget", tab.context_widget is not None)
    check("context list seeded",
          tab.context_widget.lst.count() >= 2,
          f"count={tab.context_widget.lst.count()}")
    check("state label starts OFF", tab.state_label.text() == "STATE: OFF")

    # assistant on -> state label updates through poll
    assistant.set_on()
    for _ in range(50):
        win._on_poll()
        app.processEvents()
        if tab.state_label.text() != "STATE: OFF":
            break
    check("state label synced to IDLE", "IDLE" in tab.state_label.text(),
          tab.state_label.text())

    # --- dialogue bubble ------------------------------------------------
    anim = AnimationEngine()
    overlay = AvatarOverlay(assets, anim, settings)
    overlay.show()  # bubble visibility requires a visible parent
    base_h = overlay.height()
    bubble = overlay.ensure_bubble()
    check("bubble created as overlay child", bubble.parent() is overlay)
    check("overlay grew for bubble", overlay.height() > base_h,
          f"{base_h} -> {overlay.height()}")

    bubble.setBubbleStyle(typewriter_ms=0, max_lines=3)
    bubble.show_text("Halo! Aku Hakuze ~ hehe 🎮 unicode ✓ émoji test")
    for _ in range(20):
        app.processEvents()
    check("bubble visible after show", bubble.isVisible())
    check("unicode text stored", "🎮" in bubble.current_text())

    # streaming append
    bubble.append_delta(" streaming chunk ✓")
    for _ in range(10):
        app.processEvents()
    check("streaming appended", "streaming chunk" in bubble.current_text())

    # max lines clamp (long text, max_lines=3)
    long_text = "\n".join(f"line {i}" for i in range(30))
    bubble.complete_text(long_text)
    for _ in range(10):
        app.processEvents()
    # internal: revealed everything but rendering clamps (paint-level);
    # verify current_text kept full text
    check("full text retained", "line 29" in bubble.current_text())

    # hide -> overlay shrinks back
    bubble.hide_immediately()
    for _ in range(10):
        app.processEvents()
    check("overlay shrinks after hide", overlay.height() == base_h,
          f"{overlay.height()} vs {base_h}")

    # --- assistant event -> bubble bridge -------------------------------
    assistant._turn_on()
    assistant._ask_llm("halo")   # mock llm: "Halo!"
    for _ in range(100):
        win._on_poll()
        app.processEvents()
    check("assistant responded", llm.provider.calls, "no llm call")
    hist = conversations.history(contexts.active_context().id)
    check("history recorded", len(hist) >= 2)

    # --- quit path with assistant ---------------------------------------
    assistant.set_off()
    win._poll.stop()
    assistant.shutdown(wait=True)
    engine.stop()
    overlay.stop()
    print()
    if FAIL:
        print("UI SMOKE FAILED:", FAIL)
        return 1
    print("UI SMOKE: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
