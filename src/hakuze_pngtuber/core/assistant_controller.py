"""AssistantController: state machine + pipeline orchestrator (Qt-free).

Single worker thread consumes commands (audio blocks, toggles, API calls)
from one queue — no concurrent pipeline logic. Events are emitted to a
thread-safe deque the UI layer polls (plus an optional direct callback).

Pipeline: wake (energy/phrase/manual) -> record (VAD endpointing) ->
OpenAI STT -> phrase strip -> LLM (streaming) -> bubble events ->
optional TTS -> IDLE. END (toggle off) cancels everything: STT/LLM
requests get their cancel events set, TTS is stopped, state -> OFF.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Callable

import numpy as np

from .assistant_config import AssistantSettings
from .assistant_state import AssistantState, AssistantStateMachine
from .context_manager import ContextManager
from .conversation_manager import ConversationManager
from .llm_engine import LLMEngine
from .speech_capture import SpeechRecorder
from .tts_engine import TTSEngine
from .wake_word_engine import WakeWordEngine
from ..providers.llm.base import LLMCancelled, LLMError
from ..providers.stt.base import STTCancelled, STTError, STTRequest
from ..providers.tts.base import TTSError
from ..utils.credential_store import CredentialStore

_AUDIO_CMD = "audio"
_RATE = 48000


class AssistantController:
    """Owns the assistant worker thread. Thread-safe public API."""

    def __init__(self, settings, contexts: ContextManager,
                 conversations: ConversationManager,
                 llm_engine: LLMEngine, stt_provider,
                 tts_engine: TTSEngine,
                 credentials: CredentialStore | None = None,
                 event_callback: Callable[..., None] | None = None):
        self._settings = settings
        self._contexts = contexts
        self._conversations = conversations
        self._llm = llm_engine
        self._stt = stt_provider
        self._tts = tts_engine
        self._credentials = credentials or CredentialStore()
        self.fsm = AssistantStateMachine(listener=self._on_fsm_change)
        self._wake = WakeWordEngine()
        self._recorder: SpeechRecorder | None = None
        self._question_pending = False   # phrase-verify: wake heard, awaiting question
        self._cancel_turn = threading.Event()
        self._interrupt_blocks = 0

        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._events: deque = deque(maxlen=512)
        self._event_cb = event_callback
        self._worker: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._lock = threading.Lock()
        self._audio_tap_enabled = False
        self.last_error: str | None = None

        self._cfg = AssistantSettings.from_settings(settings)

    # ================================================================ events
    def emit(self, event: str, **data) -> None:
        """Thread-safe event emission for the UI bridge to poll."""
        entry = {"event": event, "t": time.monotonic(), **data}
        with self._lock:
            self._events.append(entry)
        if self._event_cb is not None:
            try:
                self._event_cb(entry)
            except Exception:  # noqa: BLE001 - UI callback isolated
                pass

    def poll_events(self, limit: int = 64) -> list[dict]:
        """Drain events (called from the GUI poll timer)."""
        out: list[dict] = []
        with self._lock:
            while self._events and len(out) < limit:
                out.append(self._events.popleft())
        return out

    # ================================================================ public
    @property
    def state(self) -> AssistantState:
        return self.fsm.state

    @property
    def is_on(self) -> bool:
        return self.fsm.is_on()

    def start(self) -> None:
        """Start the worker thread (idempotent)."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._shutdown.clear()
        self._worker = threading.Thread(
            target=self._run, name="hakuze-assistant", daemon=True)
        self._worker.start()

    def shutdown(self, wait: bool = True) -> None:
        """END-of-app teardown: cancel everything, stop worker."""
        self._cancel_turn.set()
        self._shutdown.set()
        self._tts.stop()
        if self._worker is not None and wait:
            self._worker.join(timeout=3.0)
        self._worker = None
        self.fsm.reset()

    def toggle(self) -> None:
        """END hotkey: ON<->OFF."""
        self._cmd("toggle")

    def set_on(self) -> None:
        if not self.is_on:
            self.toggle()

    def set_off(self) -> None:
        if self.is_on:
            self.toggle()

    def manual_listen(self) -> None:
        """Manual trigger: start listening now (fallback path)."""
        self._cmd("manual_listen")

    def cancel_response(self) -> None:
        """UI 'cancel response' button: abort current turn, stay ON."""
        self._cmd("cancel_response")

    def clear_history(self, context_id: str | None = None) -> None:
        if context_id:
            self._conversations.clear(context_id)
        else:
            self._conversations.clear_all()
        self.emit("history_cleared")

    def context_changed(self) -> None:
        """Active context switched: reset transient pipeline state."""
        self._cmd("context_changed")

    def settings_changed(self) -> None:
        self._cmd("settings_changed")

    # ---------------------------------------------------------- providers
    def _refresh_providers(self) -> None:
        """Reload settings + credentials into the live providers.

        Providers keep a startup snapshot otherwise — keys/models/voices
        typed later in the UI would never reach them (root cause of false
        'invalid API key' / 'model unavailable' test failures).
        """
        self._cfg = AssistantSettings.from_settings(self._settings)
        creds = self._credentials

        llm = self._llm.provider
        if hasattr(llm, "reconfigure"):
            llm.reconfigure(
                api_key=creds.get("llm_api_key"),
                base_url=self._cfg.llm_base_url or None,
                default_model=self._cfg.llm_model,
                timeout_s=self._cfg.llm_timeout_s)

        if hasattr(self._stt, "reconfigure"):
            self._stt.reconfigure(
                api_key=creds.get("openai_api_key"),
                model=self._cfg.stt_model)

        tts = self._tts
        current = getattr(tts.provider, "name", "")
        if current in ("openai-tts", "windows-sapi"):
            # only swap between our concrete providers; anything else is a
            # deliberately injected provider (tests/dev) — leave it alone
            if self._cfg.tts_provider == "openai" and current != "openai-tts":
                from ..providers.tts.openai_tts import OpenAITTS
                tts.provider = OpenAITTS(
                    api_key=creds.get("openai_api_key"),
                    model=self._cfg.tts_openai_model)
            elif self._cfg.tts_provider == "windows" and \
                    current != "windows-sapi":
                from ..providers.tts.openai_tts import WindowsSapiTTS
                tts.provider = WindowsSapiTTS(
                    voice=self._cfg.tts_voice or None)
            elif hasattr(tts.provider, "reconfigure"):
                if self._cfg.tts_provider == "openai":
                    tts.provider.reconfigure(
                        api_key=creds.get("openai_api_key"),
                        model=self._cfg.tts_openai_model)
                else:
                    tts.provider.reconfigure(
                        voice=self._cfg.tts_voice or None)
        tts.set_volume(self._cfg.tts_volume)
        tts.set_device(self._cfg.tts_output_device)

        self._llm.apply_settings(
            temperature=self._cfg.llm_temperature,
            max_tokens=self._cfg.llm_max_tokens,
            timeout_s=self._cfg.llm_timeout_s,
            streaming=self._cfg.llm_streaming)

    def tts_voices(self) -> list[str]:
        """Voice names from the ACTIVE provider (for the settings combo)."""
        try:
            return list(self._tts.provider.list_voices())
        except Exception:  # noqa: BLE001 - never break UI for a list
            return []

    def test_llm(self) -> None:
        self._cmd("test_llm")

    def test_stt(self) -> None:
        self._cmd("test_stt")

    def test_tts(self, text: str = "Halo! Aku Hakuze.") -> None:
        self._cmd("test_tts", text=text)

    def speak_text_now(self, text: str) -> None:
        """Preview/speak arbitrary text through the TTS pipeline."""
        self._cmd("speak", text=text)

    def feed_audio_block(self, block) -> None:
        """Called by AudioEngine tap (audio callback context — cheap).

        Copies the block (PortAudio reuses the buffer) and queues it.
        Enabled only while the assistant is ON (set_audio_tap flag).
        """
        if not self._audio_tap_enabled:
            return
        try:
            copy = np.array(block, dtype=np.float32, copy=True).reshape(-1)
            self._q.put_nowait((_AUDIO_CMD, copy))
        except queue.Full:
            pass  # freshness over completeness

    def set_audio_tap(self, enabled: bool) -> None:
        self._audio_tap_enabled = bool(enabled)

    def _cmd(self, kind: str, **payload) -> None:
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            self.emit("error", message="assistant command queue full")

    # ================================================================ worker
    def _run(self) -> None:
        while not self._shutdown.is_set():
            try:
                kind, payload = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if kind == _AUDIO_CMD:
                    self._handle_audio(payload)
                elif kind == "toggle":
                    self._handle_toggle()
                elif kind == "manual_listen":
                    self._handle_manual_listen()
                elif kind == "cancel_response":
                    self._cancel_current_turn()
                elif kind == "context_changed":
                    self._reset_pipeline(keep_on=True)
                elif kind == "settings_changed":
                    self._refresh_providers()
                elif kind == "test_llm":
                    self._do_test_llm()
                elif kind == "test_stt":
                    self._do_test_stt()
                elif kind == "test_tts":
                    self._do_test_tts(str(payload.get("text", "")))
                elif kind == "speak":
                    self._do_speak(str(payload.get("text", "")))
            except Exception as exc:  # noqa: BLE001 - worker never dies
                self._fail(str(exc))

    # ================================================================ toggle
    def _handle_toggle(self) -> None:
        if self.fsm.is_on():
            self._turn_off()
        else:
            self._turn_on()

    def _turn_on(self) -> None:
        self._refresh_providers()
        if not self.fsm.transition(AssistantState.IDLE):
            self.fsm.force_off()
            return
        self._wake = WakeWordEngine(
            mode=self._cfg.wake_mode, phrase=self._cfg.wake_phrase,
            sensitivity=self._cfg.wake_sensitivity)
        self._reset_pipeline(keep_on=True)
        self._audio_tap_enabled = True
        self.emit("assistant_on", mode=self._cfg.wake_mode)
        if self._cfg.wake_mode == "manual":
            self.emit("status", message="assistant ON - use manual listen")

    def _turn_off(self) -> None:
        self._cancel_current_turn()
        self._audio_tap_enabled = False
        self._tts.stop()
        self.fsm.force_off()
        self.emit("assistant_off")

    def _reset_pipeline(self, keep_on: bool) -> None:
        self._cancel_current_turn()
        self._recorder = None
        self._question_pending = False
        self._interrupt_blocks = 0
        if keep_on and self.fsm.state not in (
                AssistantState.IDLE, AssistantState.OFF):
            if self.fsm.state is AssistantState.ERROR:
                self.fsm.recover()
            else:
                self.fsm.transition(AssistantState.IDLE)

    def _cancel_current_turn(self) -> None:
        self._cancel_turn.set()
        self._tts.stop()
        self._recorder = None
        self._question_pending = False
        self._interrupt_blocks = 0

    def _fail(self, message: str, user_message: str | None = None) -> None:
        self.last_error = message
        self.emit("error", message=user_message or "assistant error")
        if self.fsm.is_on():
            self.fsm.transition(AssistantState.ERROR)
            self.fsm.recover()

    # ================================================================ audio
    def _block_rms(self, block) -> float:
        if block is None or getattr(block, "size", 0) == 0:
            return 0.0
        arr = np.asarray(block, dtype=np.float32).reshape(-1)
        return float(np.sqrt(np.mean(np.square(arr))))

    def _handle_audio(self, block) -> None:
        if not self.fsm.is_on():
            return
        state = self.fsm.state
        tts_busy = self._tts.is_speaking_or_hangover()
        rms = self._block_rms(block)

        # --- barge-in: user speech while SPEAKING/RESPONDING ---------------
        # Elevated threshold (2.5x wake): headset users' own voice clears it
        # easily while TTS leakage stays below. Speaker setups may false-
        # trigger -> user can set interruption policy to "finish first".
        if state in (AssistantState.SPEAKING, AssistantState.RESPONDING) \
                and self._cfg.interrupt_allow:
            if rms > self._interrupt_threshold():
                self._interrupt_blocks += 1
            else:
                self._interrupt_blocks = 0
            if self._interrupt_blocks >= 3:
                self.emit("status", message="user interrupt")
                self._cancel_current_turn()
                self.fsm.transition(AssistantState.LISTENING)
                self._start_recording()
                self._recorder_feed(block)
                return

        # --- SPEAKING: absorb blocks while playing -------------------------
        if state is AssistantState.SPEAKING:
            return

        # --- LISTENING: feed the recorder ----------------------------------
        if state is AssistantState.LISTENING:
            if self._recorder is None:
                self._start_recording()
            still = self._recorder_feed(block)
            if not still:
                self._finish_utterance()
            return

        # --- IDLE (and ERROR recovered): wake stage ------------------------
        if state is AssistantState.IDLE and not tts_busy:
            mode = self._wake.mode
            if mode in ("energy", "phrase-verify"):
                threshold = self._wake.energy_threshold()
                if rms >= threshold:
                    if self._question_pending:
                        # phrase-verify already consumed the wake utterance
                        self.fsm.transition(AssistantState.LISTENING)
                        self._start_recording()
                        self._recorder_feed(block)
                        return
                    if mode == "phrase-verify":
                        if self.fsm.transition(AssistantState.LISTENING):
                            self._start_recording()
                            self._recorder_feed(block)
                    else:
                        if self.fsm.transition(AssistantState.LISTENING):
                            self.emit("status", message="listening...")
                            self._start_recording()
                            self._recorder_feed(block)

    def _interrupt_threshold(self) -> float:
        base = self._wake.energy_threshold()
        return max(0.05, base * 2.5)

    def _start_recording(self) -> None:
        self._cfg = AssistantSettings.from_settings(self._settings)
        self._recorder = SpeechRecorder(
            source_rate=_RATE,
            start_threshold=self._wake.energy_threshold(),
            stop_threshold=self._wake.energy_threshold() * 0.55,
            endpoint_silence_ms=800,
            min_utterance_ms=300,
        )
        self._cancel_turn.clear()

    def _recorder_feed(self, block) -> bool:
        if self._recorder is None:
            return False
        still = self._recorder.feed(np.asarray(
            block, dtype=np.float32).reshape(-1))
        return still

    # ================================================================ stt
    def _finish_utterance(self) -> None:
        recorder = self._recorder
        self._recorder = None
        if recorder is None or not recorder.had_speech():
            # too short / no speech -> back to idle silently
            self.fsm.transition(AssistantState.IDLE)
            return
        wav = recorder.result()
        self.fsm.transition(AssistantState.TRANSCRIBING)
        self.emit("status", message="transcribing...")
        self._cfg = AssistantSettings.from_settings(self._settings)
        request = STTRequest(
            audio=wav, model=self._cfg.stt_model,
            language=self._cfg.stt_language or None,
            timeout_s=self._cfg.stt_timeout_s,
            cancel_event=self._cancel_turn)
        try:
            transcript = self._stt.transcribe(request)
        except STTCancelled:
            self.fsm.transition(AssistantState.IDLE)
            return
        except STTError as exc:
            self._fail(exc.user_message)
            return
        if self._cancel_turn.is_set():
            self.fsm.transition(AssistantState.IDLE)
            return

        wake_mode = self._wake.mode
        if wake_mode == "phrase-verify":
            if not self._wake.phrase_matches(transcript):
                # not addressed to the assistant -> ignore
                self.fsm.transition(AssistantState.IDLE)
                return
            question = self._wake.strip_phrase(transcript)
            if question:
                self._ask_llm(question)
                return
            # only the wake phrase was said -> await the actual question
            self._question_pending = True
            self.fsm.transition(AssistantState.WAKE_WORD_DETECTED)
            self.emit("ack", message=self._wake.phrase)
            self.fsm.transition(AssistantState.IDLE)
            return
        # energy / manual modes: whole utterance is the question
        self._ask_llm(transcript)

    # ================================================================ llm
    def _ask_llm(self, question: str) -> None:
        question = question.strip()
        if not question:
            self.fsm.transition(AssistantState.IDLE)
            return
        self._question_pending = False
        self._cancel_turn.clear()   # fresh turn: cancel state from previous
        self._cfg = AssistantSettings.from_settings(self._settings)
        self._llm.apply_settings(
            temperature=self._cfg.llm_temperature,
            max_tokens=self._cfg.llm_max_tokens,
            timeout_s=self._cfg.llm_timeout_s,
            streaming=self._cfg.llm_streaming)
        self.fsm.transition(AssistantState.THINKING)
        self.emit("status", message="thinking...")
        show_bubble = self._cfg.bubble_enabled and (
            self._cfg.output_mode in ("text", "both")
            or (self._cfg.output_mode == "voice"
                and self._cfg.bubble_voice_mode))
        if show_bubble:
            self.emit("bubble_show")
        try:
            text = self._llm.respond(
                question,
                on_delta=(lambda delta: self.emit("bubble_delta", text=delta)
                          if show_bubble else None),
                cancel_event=self._cancel_turn)
        except LLMCancelled:
            self.emit("bubble_cancel")
            self.fsm.transition(AssistantState.IDLE)
            return
        except LLMError as exc:
            self.emit("bubble_cancel")
            self._fail(exc.user_message)
            return
        if self._cancel_turn.is_set():
            self.emit("bubble_cancel")
            self.fsm.transition(AssistantState.IDLE)
            return

        self.fsm.transition(AssistantState.RESPONDING)
        if show_bubble:
            self.emit("bubble_done", text=text)
        if self._cfg.output_mode in ("voice", "both"):
            self._speak_response(text)
        else:
            self.fsm.transition(AssistantState.IDLE)

    def _speak_response(self, text: str) -> None:
        self.fsm.transition(AssistantState.SPEAKING)
        self.emit("status", message="speaking...")
        try:
            ok = self._tts.speak_text(text, voice=self._cfg.tts_voice or None,
                                      speed=self._cfg.tts_speed)
        except TTSError as exc:
            self._fail(exc.user_message)
            return
        if not ok:
            self._fail("tts failed")
            return
        # wait for playback (cancellation handled via _tts.stop())
        deadline = time.monotonic() + 300.0
        while (self._tts.is_speaking() and not self._shutdown.is_set()
               and time.monotonic() < deadline):
            time.sleep(0.05)
        self.fsm.transition(AssistantState.IDLE)
        self.emit("speech_done")

    # ================================================================ tests
    def _do_test_llm(self) -> None:
        self._refresh_providers()
        ok, message = self._llm.test_connection()
        self.emit("test_result", what="llm", ok=ok, message=message)

    def _do_test_stt(self) -> None:
        self._refresh_providers()
        ok, message = self._stt.test_connection()
        self.emit("test_result", what="stt", ok=ok, message=message)

    def _do_test_tts(self, text: str) -> None:
        if not text:
            text = "Halo! Aku Hakuze."
        self._refresh_providers()
        voice = self._cfg.tts_voice
        if voice:
            try:
                known = self._tts.provider.list_voices()
            except Exception:  # noqa: BLE001
                known = []
            if known and voice not in known:
                self.emit("status",
                          message=f"voice '{voice}' not found - using default")
        try:
            self._tts.speak_text(text, voice=self._cfg.tts_voice or None,
                                 speed=self._cfg.tts_speed)
            self.emit("test_result", what="tts", ok=True, message="playing")
        except TTSError as exc:
            self.emit("test_result", what="tts", ok=False,
                      message=exc.user_message)

    def _do_speak(self, text: str) -> None:
        try:
            self._tts.speak_text(text, voice=self._cfg.tts_voice or None,
                                 speed=self._cfg.tts_speed)
        except TTSError as exc:
            self._fail(exc.user_message)

    # ================================================================ fsm
    def _on_fsm_change(self, old: AssistantState, new: AssistantState) -> None:
        self.emit("state", state=new.value, old=old.value)

    # manual listen ---------------------------------------------------------
    def _handle_manual_listen(self) -> None:
        if not self.fsm.is_on():
            return
        if self.fsm.state in (AssistantState.SPEAKING, AssistantState.RESPONDING):
            self._cancel_current_turn()
        if self.fsm.transition(AssistantState.LISTENING):
            self._start_recording()
            self.emit("status", message="listening (manual)...")
        else:
            self._fail("cannot listen from current state")
