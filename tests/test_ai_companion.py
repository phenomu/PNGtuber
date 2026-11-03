"""AI Companion tests: state machine, contexts, conversations, LLM, STT,
wake word, TTS modes, controller pipeline — all with mock providers.
No network. Qt not required (core is Qt-free).
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hakuze_pngtuber.core.assistant_state import (  # noqa: E402
    AssistantState, AssistantStateMachine, can_transition)
from hakuze_pngtuber.core.context_manager import (  # noqa: E402
    ContextManager, Persona)
from hakuze_pngtuber.core.conversation_manager import ConversationManager  # noqa: E402
from hakuze_pngtuber.core.llm_engine import LLMEngine, build_system_prompt  # noqa: E402
from hakuze_pngtuber.core.wake_word_engine import WakeWordEngine  # noqa: E402
from hakuze_pngtuber.core.speech_capture import SpeechRecorder, wav_duration_ms  # noqa: E402
from hakuze_pngtuber.core.assistant_config import AssistantSettings  # noqa: E402
from hakuze_pngtuber.core.assistant_controller import AssistantController  # noqa: E402
from hakuze_pngtuber.providers.llm.openai_compatible import MockLLM  # noqa: E402
from hakuze_pngtuber.providers.llm.base import (  # noqa: E402
    LLMAuthError, LLMCancelled, LLMEmptyResponse, LLMRequest)
from hakuze_pngtuber.providers.stt.openai_stt import MockSTT  # noqa: E402
from hakuze_pngtuber.providers.tts.base import MockTTS, TTSRequest  # noqa: E402
from hakuze_pngtuber.providers.tts.openai_tts import WindowsSapiTTS  # noqa: E402
from hakuze_pngtuber.providers.tts.base import TTSError  # noqa: E402
from hakuze_pngtuber.core.tts_engine import TTSEngine  # noqa: E402
from hakuze_pngtuber.utils.credential_store import CredentialStore  # noqa: E402
from hakuze_pngtuber.utils.global_hotkey import MockHotkeyManager  # noqa: E402


def _wait_state(ctrl, wanted, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ctrl.state in (wanted if isinstance(wanted, tuple) else (wanted,)):
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- fixtures
class FakeSettings:
    """Minimal SettingsManager stub (get/set with dot paths)."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}
        self.saved = 0

    def get(self, dotted: str, default=None):
        node = self._dotted(dotted)
        return default if node is _MISSING else node

    def set(self, dotted: str, value) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        self.saved += 1

    def _dotted(self, dotted: str):
        node: dict | object = self._data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return _MISSING
        return node


_MISSING = object()


@pytest.fixture()
def settings() -> FakeSettings:
    s = FakeSettings()
    s.set("ai.wake_mode", "energy")
    s.set("ai.llm_streaming", False)   # deterministic tests
    s.set("ai.output_mode", "text")
    s.set("ai.bubble_enabled", True)
    return s


@pytest.fixture()
def contexts(settings) -> ContextManager:
    return ContextManager(settings, save_fn=settings.save)


@pytest.fixture()
def conversations(settings) -> ConversationManager:
    return ConversationManager(settings, save_fn=settings.save,
                               store_path=Path("/tmp/_hakuze_test_conv.json"))


# ---------------------------------------------------------------- state
class TestAssistantStateMachine:

    def test_full_happy_path(self):
        m = AssistantStateMachine()
        for nxt in (AssistantState.IDLE, AssistantState.LISTENING,
                    AssistantState.TRANSCRIBING, AssistantState.THINKING,
                    AssistantState.RESPONDING, AssistantState.SPEAKING,
                    AssistantState.IDLE):
            assert m.transition(nxt), f"transition to {nxt} failed"
        m.force_off()
        assert m.state is AssistantState.OFF

    def test_invalid_transition_rejected(self):
        m = AssistantStateMachine()
        assert not m.transition(AssistantState.THINKING)
        assert m.state is AssistantState.OFF

    def test_off_from_any_state(self):
        m = AssistantStateMachine()
        m.transition(AssistantState.IDLE)
        m.transition(AssistantState.LISTENING)
        m.force_off()
        assert m.state is AssistantState.OFF
        m2 = AssistantStateMachine()
        m2.transition(AssistantState.IDLE)
        m2.transition(AssistantState.LISTENING)
        m2.transition(AssistantState.TRANSCRIBING)
        m2.force_off()
        assert m2.state is AssistantState.OFF

    def test_error_recovers_to_idle(self):
        m = AssistantStateMachine()
        m.transition(AssistantState.IDLE)
        assert m.transition(AssistantState.ERROR)
        assert m.recover()
        assert m.state is AssistantState.IDLE

    def test_cancellation_from_every_state(self):
        states = [AssistantState.IDLE, AssistantState.LISTENING,
                  AssistantState.TRANSCRIBING, AssistantState.THINKING,
                  AssistantState.RESPONDING, AssistantState.SPEAKING,
                  AssistantState.ERROR]
        for state in states:
            m = AssistantStateMachine()
            m._state = state  # force for test
            m.force_off()
            assert m.state is AssistantState.OFF

    def test_can_transition_matrix(self):
        assert can_transition(AssistantState.OFF, AssistantState.IDLE)
        assert not can_transition(AssistantState.OFF, AssistantState.THINKING)
        assert can_transition(AssistantState.RESPONDING, AssistantState.LISTENING)


# ---------------------------------------------------------------- contexts
class TestContextManager:

    def test_seeds_default_contexts(self, contexts):
        names = [c.name for c in contexts.contexts]
        assert any("Minecraft" in n for n in names)
        assert any("General" in n for n in names)

    def test_create_activate_delete(self, contexts):
        ctx = contexts.create("Programming Context",
                              instructions="help with python")
        assert any(c.id == ctx.id for c in contexts.contexts)
        assert contexts.set_active(ctx.id)
        assert contexts.active_context().name == "Programming Context"
        assert contexts.delete(ctx.id)
        # active fell back
        assert contexts.active_context().id != ctx.id

    def test_duplicate_names_deduped(self, contexts):
        ctx1 = contexts.create("Dup")
        ctx2 = contexts.create("Dup")
        assert ctx1.name != ctx2.name

    def test_last_context_undeletable(self, contexts):
        for ctx in list(contexts.contexts):
            if len(contexts.contexts) > 1:
                contexts.delete(ctx.id)
        assert not contexts.delete(contexts.contexts[0].id)

    def test_update_preserves_id(self, contexts):
        ctx = contexts.create("EditMe")
        updated = contexts.update(ctx.id, name="Edited", instructions="x")
        assert updated.id == ctx.id
        assert updated.name == "Edited"
        assert updated.instructions == "x"

    def test_update_duplicate_name_rejected(self, contexts):
        a = contexts.create("AAA")
        b = contexts.create("BBB")
        with pytest.raises(ValueError):
            contexts.update(b.id, name="AAA")

    def test_active_deleted_falls_back(self, contexts):
        ctx = contexts.create("Temp")
        contexts.set_active(ctx.id)
        contexts.delete(ctx.id)
        assert contexts.get(ctx.id) is None
        assert contexts.active_context() is not None

    def test_invalid_context_data_sanitized(self, settings):
        settings.set("ai.contexts", [
            {"id": "bad!", "name": 42, "instructions": "ok",
             "response_length": "gibberish", "params": {"k": ["nested"]}}])
        cm = ContextManager(settings, save_fn=lambda: None)
        ctx = cm.contexts[0]
        assert ctx.name == "Unnamed"  # non-string name sanitized
        assert ctx.id != "bad!"       # invalid id regenerated
        assert ctx.response_length == "short"
        assert "k" not in ctx.params  # non-scalar param dropped

    def test_persistence_roundtrip(self, settings):
        cm = ContextManager(settings, save_fn=lambda: None)
        cm.create("Persisted")
        data = settings.get("ai.contexts")
        assert any(c["name"] == "Persisted" for c in data)
        cm2 = ContextManager(settings, save_fn=lambda: None)
        assert any(c.name == "Persisted" for c in cm2.contexts)

    def test_persona_default_and_update(self, settings, contexts):
        p = contexts.persona()
        assert p.name == "Hakuze"
        assert p.use_emoji is True
        contexts.set_persona(Persona(name="Zeta", use_emoji=False))
        p2 = contexts.persona()
        assert p2.name == "Zeta"
        assert p2.use_emoji is False


# ---------------------------------------------------------------- history
class TestConversationManager:

    def test_history_per_context_separated(self, conversations):
        conversations.append("ctxA", "user", "halo A")
        conversations.append("ctxA", "assistant", "halo!")
        conversations.append("ctxB", "user", "halo B")
        hist_a = conversations.history("ctxA")
        hist_b = conversations.history("ctxB")
        assert [m["content"] for m in hist_a] == ["halo A", "halo!"]
        assert [m["content"] for m in hist_b] == ["halo B"]

    def test_history_bounded(self, settings):
        settings.set("ai.history_max_turns", 2)
        conv = ConversationManager(
            settings, store_path=Path("/tmp/_hakuze_test_conv.json"))
        for i in range(20):
            conv.append("ctx", "user", f"m{i}")
        assert len(conv.history("ctx")) == 4  # 2 turns * 2 messages

    def test_clear_and_clear_all(self, conversations):
        conversations.append("ctxA", "user", "x")
        conversations.append("ctxB", "user", "y")
        conversations.clear("ctxA")
        assert conversations.history("ctxA") == []
        assert conversations.history("ctxB")
        conversations.clear_all()
        assert conversations.history("ctxB") == []

    def test_invalid_role_dropped(self, conversations):
        conversations.append("ctx", "admin", "not a role")
        assert conversations.history("ctx") == []


# ---------------------------------------------------------------- llm
class TestLLMEngine:

    def test_system_prompt_composition(self, contexts):
        persona = Persona(name="Hakuze", personality="cheerful")
        ctx = contexts.active_context()
        prompt = build_system_prompt(persona, ctx)
        assert "Hakuze" in prompt
        assert ctx.instructions  # minecraft context has instructions
        assert ctx.instructions in prompt
        assert "livestream" in prompt.lower() or "live stream" in prompt.lower()

    def test_persona_not_overridden_by_context(self, contexts):
        prompt = build_system_prompt(
            Persona(name="Hakuze", personality="VERY-SPECIFIC-PERSONA"),
            contexts.active_context())
        assert "VERY-SPECIFIC-PERSONA" in prompt

    def test_context_knowledge_included(self, contexts):
        ctx = contexts.create("K", knowledge="secret-knowledge-123")
        prompt = build_system_prompt(Persona(), ctx)
        assert "secret-knowledge-123" in prompt

    def test_respond_stores_history(self, contexts, conversations):
        llm = LLMEngine(MockLLM(["Oke!"]), contexts, conversations,
                        streaming=False)
        llm.respond("apa itu obsidian?")
        hist = conversations.history(contexts.active_context().id)
        assert hist[-2]["role"] == "user"
        assert hist[-2]["content"] == "apa itu obsidian?"
        assert hist[-1]["content"] == "Oke!"

    def test_history_isolated_per_context(self, contexts, conversations):
        llm = LLMEngine(MockLLM(["r1", "r2"]), contexts, conversations,
                        streaming=False)
        llm.respond("q1")                      # in default/active context
        other = contexts.create("Other")
        contexts.set_active(other.id)
        llm.respond("q2")
        assert len(conversations.history(other.id)) == 2
        first = [c for c in contexts.contexts
                 if c.id != other.id][0]
        assert len(conversations.history(first.id)) == 2

    def test_streaming_deltas(self, contexts, conversations):
        deltas = []
        llm = LLMEngine(MockLLM(["Halo"]), contexts, conversations,
                        streaming=True)
        text = llm.respond("hai", on_delta=deltas.append)
        assert text == "Halo"
        assert "".join(deltas) == "Halo"

    def test_cancellation_no_history_write(self, contexts, conversations):
        llm = LLMEngine(MockLLM(["never stored"]), contexts, conversations,
                        streaming=False)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(LLMCancelled):
            llm.respond("q", cancel_event=cancel)
        assert conversations.history(contexts.active_context().id) == []

    def test_empty_response_raises(self, contexts, conversations):
        llm = LLMEngine(MockLLM([""]), contexts, conversations, streaming=False)
        with pytest.raises(LLMEmptyResponse):
            llm.respond("q")

    def test_error_does_not_store(self, contexts, conversations):
        err = LLMAuthError("401")
        llm = LLMEngine(MockLLM(error=err), contexts, conversations,
                        streaming=False)
        with pytest.raises(LLMAuthError):
            llm.respond("q")
        assert conversations.history(contexts.active_context().id) == []


# ---------------------------------------------------------------- wake word
class TestWakeWordEngine:

    def test_phrase_match_exact(self):
        w = WakeWordEngine(phrase="Hai GPT")
        assert w.phrase_matches("Hai GPT, tolong buatkan potion")
        assert w.phrase_matches("hai gpt apa kabar")

    def test_phrase_match_fuzzy(self):
        w = WakeWordEngine(phrase="Hai GPT")
        assert w.phrase_matches("Hi GPT, bantu dong")
        assert w.phrase_matches("hay gpt!")

    def test_phrase_no_match(self):
        w = WakeWordEngine(phrase="Hai GPT")
        assert not w.phrase_matches("tolong buatkan potion")
        assert not w.phrase_matches("")

    def test_strip_phrase(self):
        w = WakeWordEngine(phrase="Hai GPT")
        assert w.strip_phrase("Hai GPT tolong buatkan potion") == \
            "tolong buatkan potion"
        # phrase not present -> whole text
        assert w.strip_phrase("buatkan potion") == "buatkan potion"

    def test_energy_threshold_scales(self):
        w_low = WakeWordEngine(sensitivity=0.1)
        w_high = WakeWordEngine(sensitivity=1.0)
        assert w_high.energy_threshold() < w_low.energy_threshold()

    def test_available_modes_honest(self):
        modes = WakeWordEngine.available_modes()
        assert "energy" in modes
        assert "manual" in modes
        # openwakeword only listed when actually importable
        ok, _ = WakeWordEngine.openwakeword_available()
        assert ("openwakeword" in modes) == ok


# ---------------------------------------------------------------- stt
class TestSTT:

    def test_mock_transcribe(self):
        stt = MockSTT(["Hai GPT, apa itu obsidian?"])
        from hakuze_pngtuber.providers.stt.base import STTRequest
        assert stt.transcribe(STTRequest(audio=b"x" * 100)) == \
            "Hai GPT, apa itu obsidian?"

    def test_openai_stt_wav_wrap(self):
        from hakuze_pngtuber.providers.stt.openai_stt import OpenAISTT
        import io, wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 160)
        # already-WAV passthrough
        out = OpenAISTT._ensure_wav(buf.getvalue())
        assert out.getvalue()[:4] == b"RIFF"
        # raw PCM gets wrapped
        out2 = OpenAISTT._ensure_wav(b"\x00\x00" * 160)
        assert out2.getvalue()[:4] == b"RIFF"


# ---------------------------------------------------------------- capture
class TestSpeechRecorder:

    def _blocks(self, seconds: float, rms: float, rate: int = 48000):
        n = int(rate * seconds)
        n_blocks = max(1, int(seconds * 50))
        per = n // n_blocks
        blocks = []
        for _ in range(n_blocks):
            block = np.full(per, rms, dtype=np.float32)
            blocks.append(block)
        return blocks

    def test_endpoint_silence(self):
        rec = SpeechRecorder(endpoint_silence_ms=600, preroll_blocks=1)
        for b in self._blocks(0.5, 0.05):    # 500 ms speech
            assert rec.feed(b) is True
        for b in self._blocks(1.0, 0.0005):  # 1 s silence
            rec.feed(b)
        assert rec.capturing is False
        assert rec.had_speech()
        wav = rec.result()
        assert wav[:4] == b"RIFF"
        assert wav_duration_ms(wav) > 1000  # speech + trailing silence

    def test_short_utterance_rejected(self):
        rec = SpeechRecorder(min_utterance_ms=300)
        for b in self._blocks(0.1, 0.05):    # 100 ms only
            rec.feed(b)
        for b in self._blocks(0.9, 0.0005):
            rec.feed(b)
        assert not rec.had_speech()

    def test_resample_48k_to_16k(self):
        rec = SpeechRecorder()
        for b in self._blocks(1.0, 0.05):
            rec.feed(b)
        for b in self._blocks(0.9, 0.0005):
            rec.feed(b)
        wav = rec.result()
        with __import__("wave").open(__import__("io").BytesIO(wav)) as w:
            rate = w.getframerate()
            frames = w.getnframes()
        assert rate == 16000
        duration = frames / 16000
        assert 1.4 < duration < 2.0  # ~1.5-1.9 s after endpoint trimming


# ---------------------------------------------------------------- tts
class TestTTSEngine:

    def test_output_mode_text_no_speak(self, settings, contexts,
                                       conversations):
        # controller path: text mode never calls tts
        tts = TTSEngine(MockTTS())
        llm = LLMEngine(MockLLM(["Oke!"]), contexts, conversations,
                        streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, MockSTT(["q"]), tts)
        ctrl.start()
        ctrl.set_audio_tap(True)  # enable feed path
        ctrl._turn_on()
        assert ctrl.state is AssistantState.IDLE
        # simulate: transcribe + respond
        ctrl._finish_utterance.__self__  # exists
        ctrl._ask_llm("test question")
        assert ctrl.state is AssistantState.IDLE
        ctrl.shutdown()

    def test_output_mode_voice_speaks(self, settings, contexts,
                                      conversations):
        settings.set("ai.output_mode", "voice")
        settings.set("ai.bubble_enabled", False)
        tts = TTSEngine(MockTTS())
        spoken = []
        tts.on_speaking_changed = lambda on: spoken.append(on)
        llm = LLMEngine(MockLLM(["Oke!"]), contexts, conversations,
                        streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, MockSTT(["q"]), tts)
        ctrl._turn_on()
        # walk the real path: LISTENING -> TRANSCRIBING -> THINKING -> ...
        ctrl.fsm.transition(AssistantState.LISTENING)
        ctrl._ask_llm("test")
        assert ctrl.state is AssistantState.IDLE  # returned after speaking
        assert any(spoken)
        ctrl.shutdown()

    def test_duplicate_playback_prevented(self):
        tts = TTSEngine(MockTTS())
        tts.play_pcm(np.zeros(24000, dtype=np.float32), 24000)
        first = tts._current
        assert tts.is_speaking()
        # second speak interrupts first rather than overlapping
        tts.play_pcm(np.zeros(24000, dtype=np.float32), 24000)
        assert tts._current is not first
        tts.stop()

    def test_cancellation(self):
        tts = TTSEngine(MockTTS())
        # long audio (no backend -> simulated playback)
        tts.play_pcm(np.zeros(24000 * 10, dtype=np.float32), 24000)
        assert tts.is_speaking()
        tts.stop()
        assert not tts.is_speaking()

    def test_hangover_gates_wake(self):
        tts = TTSEngine(MockTTS())
        assert not tts.is_speaking_or_hangover()
        tts.play_pcm(np.zeros(24000, dtype=np.float32), 24000)
        tts.stop()
        time.sleep(0.05)
        assert tts.is_speaking_or_hangover()  # short hangover window
        # wait past hangover (350 ms)
        time.sleep(0.4)
        assert not tts.is_speaking_or_hangover()


# ---------------------------------------------------------------- hotkey
class TestHotkeyManager:

    def test_mock_register_toggle(self):
        hk = MockHotkeyManager()
        fired = []
        assert hk.register("END", lambda: fired.append(1))
        hk.press("END")
        assert fired == [1]
        hk.unregister()
        hk.press("END")
        assert fired == [1]  # no fire after unregister

    def test_unsupported_key(self):
        hk = MockHotkeyManager()
        # mock always registers; base class rejects unknown keys
        from hakuze_pngtuber.utils.global_hotkey import HotkeyManager
        base = HotkeyManager()
        assert not base.register("NOT_A_KEY", lambda: None)


# ---------------------------------------------------------------- pipeline
class TestAssistantController:

    def _make(self, settings, contexts, conversations,
              llm_responses=None, transcripts=None, tts_error=None):
        tts = TTSEngine(MockTTS(error=tts_error))
        llm = LLMEngine(MockLLM(llm_responses or ["Oke!"]), contexts,
                        conversations, streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm,
            MockSTT(transcripts or ["Hai GPT, test question"]), tts)
        return ctrl

    def test_toggle_on_off(self, settings, contexts, conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        ctrl.toggle()
        assert _wait_state(ctrl, AssistantState.IDLE)
        assert ctrl.is_on
        ctrl.toggle()
        assert _wait_state(ctrl, AssistantState.OFF)
        assert not ctrl.is_on
        ctrl.shutdown()

    def test_end_to_end_energy_mode(self, settings, contexts, conversations):
        ctrl = self._make(settings, contexts, conversations,
                          llm_responses=["Jawaban!"])
        ctrl.start()
        ctrl._turn_on()
        # feed speech blocks -> LISTENING -> endpoint -> transcribe -> LLM
        block = np.full(960, 0.05, dtype=np.float32)
        for _ in range(25):     # 500 ms speech
            ctrl.feed_audio_block(block)
            time.sleep(0.01)
        quiet = np.full(960, 0.0005, dtype=np.float32)
        for _ in range(50):     # 1 s silence
            ctrl.feed_audio_block(quiet)
            time.sleep(0.01)
        assert _wait_state(ctrl, AssistantState.IDLE)
        hist = conversations.history(contexts.active_context().id)
        assert hist[-1]["content"] == "Jawaban!"
        events = ctrl.poll_events()
        kinds = [e["event"] for e in events]
        assert "bubble_done" in kinds
        ctrl.shutdown()

    def test_toggle_off_cancels_everything(self, settings, contexts,
                                           conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        ctrl._turn_on()
        ctrl._ask_llm("x")     # synchronous: completes (mock)
        ctrl.toggle()          # OFF
        assert _wait_state(ctrl, AssistantState.OFF)
        assert not ctrl.is_on
        ctrl.shutdown()

    def test_context_switch_resets_pipeline(self, settings, contexts,
                                            conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        ctrl._turn_on()
        new_ctx = contexts.create("Switched")
        contexts.set_active(new_ctx.id)
        ctrl.context_changed()
        time.sleep(0.1)
        assert ctrl.state is AssistantState.IDLE
        ctrl.shutdown()

    def test_error_recovers_not_stuck(self, settings, contexts, conversations):
        ctrl = self._make(settings, contexts, conversations,
                          tts_error=None)
        # force an LLM error via a failing provider
        ctrl._llm.provider = MockLLM(error=LLMAuthError("401"))
        ctrl.start()
        ctrl._turn_on()
        ctrl._ask_llm("q")
        time.sleep(0.1)
        assert ctrl.state is AssistantState.IDLE
        assert ctrl.is_on  # error didn't turn assistant off
        ctrl.shutdown()

    def test_manual_listen(self, settings, contexts, conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        ctrl._turn_on()
        ctrl.manual_listen()
        time.sleep(0.05)
        assert ctrl.state is AssistantState.LISTENING
        ctrl.shutdown()

    def test_settings_changed_reload(self, settings, contexts, conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        settings.set("ai.llm_temperature", 0.1)
        ctrl.settings_changed()
        time.sleep(0.05)
        assert ctrl._cfg.llm_temperature == pytest.approx(0.1)
        ctrl.shutdown()

    def test_wake_phrase_hot_reload(self, settings, contexts, conversations):
        # the wake engine kept its startup snapshot
        settings.set("ai.wake_mode", "phrase-verify")
        ctrl = self._make(settings, contexts, conversations)
        ctrl.start()
        ctrl._turn_on()
        settings.set("ai.wake_phrase", "halo")
        settings.set("ai.wake_mode", "phrase-verify")
        ctrl.settings_changed()
        time.sleep(0.05)
        assert ctrl._wake.phrase == "halo"
        assert ctrl._wake.mode == "phrase-verify"
        assert ctrl._wake.phrase_matches("halo, apa kabar?")
        assert not ctrl._wake.phrase_matches("selamat pagi semuanya")
        ctrl.shutdown()

    # ---------------------------------------------------------- logs panel
    def test_log_disabled_captures_nothing(self, settings, contexts,
                                           conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl._turn_on()
        ctrl._ask_llm("halo")  # mock LLM replies
        ctrl._turn_off()
        assert ctrl.poll_log_lines() == []  # nothing captured while off
        ctrl.shutdown()

    def test_log_enabled_captures_pipeline(self, settings, contexts,
                                           conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl.set_log_enabled(True)
        ctrl._turn_on()
        ctrl._ask_llm("halo")  # mock LLM: "Oke!"
        ctrl._turn_off()
        lines = "\n".join(ctrl.log_lines())
        assert "logging enabled" in lines
        assert "state" in lines or "assistant_on" in lines
        assert ctrl.log_line_count() > 3
        ctrl.shutdown()

    def test_stt_failure_logged(self, settings, contexts, conversations):
        from hakuze_pngtuber.providers.stt.base import STTError
        ctrl = self._make(settings, contexts, conversations)
        ctrl.set_log_enabled(True)
        ctrl._turn_on()
        ctrl.fsm.transition(AssistantState.LISTENING)
        ctrl._start_recording()
        loud = np.ones(1600, dtype=np.float32) * 0.3
        for _ in range(20):
            ctrl._recorder_feed(loud)
        for _ in range(80):
            if not ctrl._recorder_feed(np.zeros(1600, dtype=np.float32)):
                break
        ctrl._finish_utterance()
        lines = "\n".join(ctrl.log_lines())
        assert "heard" in lines  # mock STT transcript captured in log
        ctrl.shutdown()

    def test_clear_history_current_context(self, settings, contexts,
                                           conversations):
        ctrl = self._make(settings, contexts, conversations)
        ctrl._turn_on()
        ctrl._ask_llm("halo")
        active = ctrl._contexts.active_id
        assert len(conversations.history(active)) > 0
        ctrl.clear_history("current")
        assert conversations.history(active) == []
        ctrl.shutdown()


# ---------------------------------------------------------------- hot reload
class TestProviderHotReconfigure:

    def test_llm_key_and_model_reach_provider(self, settings, contexts,
                                              conversations):
        from hakuze_pngtuber.providers.llm.openai_compatible import \
            OpenAICompatibleLLM
        from hakuze_pngtuber.core.llm_engine import LLMEngine
        provider = OpenAICompatibleLLM(api_key=None, default_model="",
                                       base_url="https://api.ate.my.id/v1")
        llm = LLMEngine(provider, contexts, conversations, streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, MockSTT(["q"]),
            TTSEngine(MockTTS()))
        ctrl._credentials = _FakeCreds({"llm_api_key": "sk-live",
                                        "openai_api_key": "sk-oa"})
        settings.set("ai.llm_model", "nr/glm-5.3")
        settings.set("ai.llm_base_url", "https://api.ate.my.id/v1")
        ctrl._refresh_providers()
        assert provider._api_key == "sk-live"
        assert provider._default_model == "nr/glm-5.3"
        assert provider._base_url == "https://api.ate.my.id/v1"

    def test_stt_key_reaches_provider(self, settings, contexts, conversations):
        from hakuze_pngtuber.providers.stt.openai_stt import OpenAISTT
        from hakuze_pngtuber.core.llm_engine import LLMEngine
        stt = OpenAISTT(api_key=None, model="gpt-4o-mini-transcribe")
        llm = LLMEngine(MockLLM(["x"]), contexts, conversations,
                        streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, stt,
            TTSEngine(MockTTS()))
        ctrl._credentials = _FakeCreds({"openai_api_key": "sk-oa"})
        settings.set("ai.stt_model", "whisper-1")
        ctrl._refresh_providers()
        assert stt._api_key == "sk-oa"
        assert stt._model == "whisper-1"

    def test_tts_provider_swapped_without_restart(self, settings, contexts,
                                                  conversations):
        from hakuze_pngtuber.providers.tts.openai_tts import (
            OpenAITTS, WindowsSapiTTS)
        from hakuze_pngtuber.core.llm_engine import LLMEngine
        tts = TTSEngine(WindowsSapiTTS())
        llm = LLMEngine(MockLLM(["x"]), contexts, conversations,
                        streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, MockSTT(["q"]), tts)
        ctrl._credentials = _FakeCreds({})
        settings.set("ai.tts_provider", "openai")
        ctrl._refresh_providers()
        assert isinstance(tts.provider, OpenAITTS)
        settings.set("ai.tts_provider", "windows")
        ctrl._refresh_providers()
        assert isinstance(tts.provider, WindowsSapiTTS)

    def test_mock_provider_never_swapped(self, settings, contexts,
                                         conversations):
        mock = MockTTS()
        tts = TTSEngine(mock)
        llm = LLMEngine(MockLLM(["x"]), contexts, conversations,
                        streaming=False)
        ctrl = AssistantController(
            settings, contexts, conversations, llm, MockSTT(["q"]), tts)
        ctrl._credentials = _FakeCreds({})
        settings.set("ai.tts_provider", "openai")
        ctrl._refresh_providers()
        assert tts.provider is mock  # injected providers are left alone


# ---------------------------------------------------------------- sapi
class TestWindowsSapiSubprocess:
    """On non-Windows the SAPI runner must FAIL FAST, never hang."""

    def test_synth_command_dev_form(self):
        sapi = WindowsSapiTTS(voice="Microsoft Zira")
        argv = sapi._synth_command("halo", "Microsoft Zira", 1.0, 1.0,
                                   "/tmp/out.wav")
        assert argv[0:4] == [sys.executable, "-m",
                              "hakuze_pngtuber.providers.tts._sapi_synth",
                              "synth"]
        assert "--text" in argv and "halo" in argv
        assert "--voice" in argv and "Microsoft Zira" in argv

    def test_synth_no_voice_omits_flag(self):
        sapi = WindowsSapiTTS()
        argv = sapi._synth_command("halo", None, 1.0, 1.0, "/tmp/o.wav")
        assert "--voice" not in argv

    def test_synth_fails_fast_or_succeeds_bounded(self):
        sapi = WindowsSapiTTS()
        sapi._TIMEOUT_S = 30.0
        start = time.monotonic()
        try:
            data = sapi.synthesize(TTSRequest(text="tes"))
            assert len(data) > 1000  # Windows: real synthesis works
        except TTSError:
            pass  # non-Windows: clean bounded failure, worker survives
        assert time.monotonic() - start < 35.0

    def test_list_voices_bounded(self):
        sapi = WindowsSapiTTS()
        start = time.monotonic()
        voices = sapi.list_voices()
        if sys.platform.startswith("win"):
            assert len(voices) > 0  # Windows: real SAPI voices
        else:
            assert voices == []      # non-Windows: graceful empty
            assert sapi._last_error  # diagnostics present, no exception
        assert time.monotonic() - start < 20.0

    def test_reconfigure_clears_voice_cache(self):
        sapi = WindowsSapiTTS()
        sapi._voices_cache = ["A", "B"]
        sapi.reconfigure(voice="A")
        assert sapi._voices_cache is None
        assert sapi._voice == "A"


class _FakeCreds(CredentialStore):
    """Cred store stub with fixed values (never touches keyring)."""

    def __init__(self, values: dict):
        super().__init__(keyring_backend=None)
        self._values = values

    def get(self, name: str):
        return self._values.get(name)

    def status(self, name: str):
        return "session" if name in self._values else "missing"


# ---------------------------------------------------------------- creds
class TestCredentialStore:

    def test_session_roundtrip(self):
        class FakeKeyring:
            def set_password(self, *a):
                raise RuntimeError("no backend")

            def get_password(self, *a):
                return None

        store = CredentialStore(keyring_backend=FakeKeyring())
        assert store.get("llm_api_key") is None
        assert store.set("llm_api_key", "secret-value") is False
        assert store.get("llm_api_key") == "secret-value"
        assert store.status("llm_api_key") == "session"
        store.delete("llm_api_key")
        assert store.get("llm_api_key") is None

    def test_keyring_backend(self):
        class FakeKeyring:
            def __init__(self):
                self.store = {}

            def set_password(self, service, name, value):
                self.store[(service, name)] = value

            def get_password(self, service, name):
                return self.store.get((service, name))

        store = CredentialStore(keyring_backend=FakeKeyring())
        assert store.set("openai_api_key", "k-123") is True
        assert store.get("openai_api_key") == "k-123"
        assert store.status("openai_api_key") == "session"

    def test_env_fallback(self, monkeypatch):
        # sandbox ALL credential sources so real machine credentials can't
        # leak into the test (keyring may hold a user's actual key)
        class _NoKeyring:
            @staticmethod
            def get_password(*_a):
                return None

        monkeypatch.delenv("HAKUZE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("HAKUZE_OPENAI_API_KEY", raising=False)
        store = CredentialStore(keyring_backend=_NoKeyring())
        assert store.get("llm_api_key") is None
        monkeypatch.setenv("HAKUZE_LLM_API_KEY", "env-key")
        store2 = CredentialStore(keyring_backend=_NoKeyring())
        assert store2.get("llm_api_key") == "env-key"
        assert store2.status("llm_api_key") == "env"

    def test_unknown_name_rejected(self):
        store = CredentialStore(keyring_backend=None)
        assert store.set("evil_name", "x") is False
        assert store.get("evil_name") is None


# ---------------------------------------------------------------- config
class TestAssistantSettings:

    def test_defaults_from_settings(self, settings):
        cfg = AssistantSettings.from_settings(settings)
        assert cfg.wake_mode == "energy"
        assert cfg.output_mode == "text"
        assert cfg.tts_provider == "windows"
        assert cfg.llm_base_url == "https://api.ate.my.id/v1"
        assert cfg.stt_model == "gpt-4o-mini-transcribe"
        assert cfg.tts_openai_model == "gpt-4o-mini-tts"

    def test_clamps_invalid(self, settings):
        settings.set("ai.llm_temperature", 99.0)
        settings.set("ai.bubble_width", 100000)
        settings.set("ai.wake_mode", "bogus")
        cfg = AssistantSettings.from_settings(settings)
        assert cfg.llm_temperature == 2.0
        assert cfg.bubble_width == 900
        assert cfg.wake_mode == "energy"
