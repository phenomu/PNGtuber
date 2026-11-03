"""TTS playback + synthesis orchestration (Qt-free).

Synthesis and playback happen on the assistant worker thread / a playback
thread — never the GUI thread and never the audio callback. Playback uses
sounddevice OutputStream writing chunk-wise so cancellation is honored
between chunks (sub-100 ms latency). Anti-self-trigger: `is_speaking()`
plus a hangover window the controller uses to gate wake detection.
"""
from __future__ import annotations

import io
import queue
import threading
import wave

import numpy as np

try:
    import sounddevice as _sd
    _SD_ERROR = None
except Exception as _exc:  # noqa: BLE001 - optional at import time
    _sd = None
    _SD_ERROR = str(_exc)

from ..providers.tts.base import BaseTTSProvider, TTSError, TTSCancelled, TTSRequest

_CHUNK_FRAMES = 2400  # 100 ms @ 24 kHz
_HANGOVER_MS = 350.0


def wav_to_pcm(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Parse WAV -> (float32 mono, sample_rate). Raises TTSError on junk."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
            frames = w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, OSError) as exc:
        raise TTSError(str(exc), "invalid TTS audio") from exc
    if width != 2:
        # convert via numpy where possible
        if width == 1:
            data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            data = (data - 128.0) / 128.0
        else:
            raise TTSError(f"width {width}", "unsupported TTS audio format")
    else:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


class PlaybackStream:
    """One utterance playback with cooperative cancellation."""

    def __init__(self, pcm: np.ndarray, rate: int, volume: float,
                 cancel_event: threading.Event, done_callback=None,
                 device: int | None = None):
        self.pcm = pcm
        self.rate = rate
        self.volume = max(0.0, min(1.0, volume))
        self.cancel_event = cancel_event
        self.done_callback = done_callback
        self.device = device
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="hakuze-tts-play", daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    def _run(self) -> None:
        if _sd is None:
            # No audio backend (headless dev): simulate duration-scaled wait
            duration = len(self.pcm) / max(1, self.rate)
            steps = int(duration / 0.05)
            for _ in range(steps):
                if self.cancel_event.is_set():
                    break
                threading.Event().wait(0.05)
            self._finish()
            return
        try:
            stream = _sd.OutputStream(
                samplerate=self.rate, channels=1, dtype="float32",
                device=self.device, blocksize=1024)
            stream.start()
            try:
                gain = self.volume
                for start in range(0, len(self.pcm), _CHUNK_FRAMES):
                    if self.cancel_event.is_set():
                        break
                    chunk = self.pcm[start:start + _CHUNK_FRAMES] * gain
                    stream.write(chunk.astype(np.float32))
                # drain buffered audio quickly on cancel: stop stream
            finally:
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 - playback must not crash
            raise TTSError(str(exc), "audio playback failed") from None
        finally:
            self._finish()

    def _finish(self) -> None:
        if self.done_callback is not None:
            try:
                self.done_callback(self.cancel_event.is_set())
            except Exception:  # noqa: BLE001
                pass


class TTSEngine:
    """Synthesize (provider) + play (PlaybackStream) with cancel support.

    Streaming mode: `flush_stream_sentences` feeds the growing response
    text; each COMPLETE sentence is synthesized on a dedicated queue
    thread and played IN ORDER, so the voice starts while the text is
    still streaming/typing instead of after everything finished."""

    def __init__(self, provider: BaseTTSProvider, volume: float = 1.0,
                 device_index: int | None = None):
        self.provider = provider
        self.volume = volume
        self.device_index = device_index
        self._lock = threading.Lock()
        self._current: PlaybackStream | None = None
        self._cancel = threading.Event()
        self._speaking_since_ms: float | None = None
        self._hangover_until_ms: float | None = None
        self.on_playback_done = None  # callable(cancelled: bool)
        self.on_speaking_changed = None  # callable(bool)
        # streaming sentence queue
        self._sentence_q: "queue.Queue[str | None]" = queue.Queue()
        self._stream_thread: threading.Thread | None = None
        self._stream_done = threading.Event()
        self._buffer = ""
        self._speaking_state = threading.Event()

    # ------------------------------------------------- streaming pipeline
    _SENTENCE_ENDS = ".!?\n"

    def _start_stream_thread(self, voice, speed) -> None:
        if self._stream_thread is not None and \
                self._stream_thread.is_alive():
            return

        def _worker():
            import time
            while True:
                item = self._sentence_q.get()
                if item is None:
                    self._sentence_q.task_done()
                    break
                self._speaking_state.set()
                try:
                    wav = self.provider.synthesize(
                        TTSRequest(text=item, voice=voice, speed=speed,
                                   cancel_event=self._cancel))
                    self.play_wav(wav)
                    # wait for this utterance to finish before the next
                    # one (play_pcm starts playback asynchronously)
                    deadline = time.monotonic() + 120.0
                    while (self.is_speaking_locked()
                           and not self._cancel.is_set()
                           and time.monotonic() < deadline):
                        time.sleep(0.05)
                except TTSError:
                    pass  # skip failed sentence; keep the stream alive
                finally:
                    self._sentence_q.task_done()
            self._speaking_state.clear()

        self._stream_thread = threading.Thread(
            target=_worker, name="hakuze-tts-stream", daemon=True)
        self._stream_thread.start()

    def flush_stream_sentences(self, delta: str = "",
                               voice: str | None = None,
                               speed: float = 1.0) -> None:
        """Feed one streamed delta; enqueue every COMPLETE sentence."""
        self._buffer += delta
        self._start_stream_thread(voice, speed)
        while True:
            cut = _sentence_end(self._buffer)
            if cut <= 0:
                break
            sentence = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:]
            if sentence:
                self._sentence_q.put(sentence)

    def flush_stream_final(self, voice: str | None = None,
                           speed: float = 1.0) -> None:
        """Stream ended: flush the trailing partial as the last sentence."""
        self.flush_stream_sentences("", voice, speed)
        rest = self._buffer.strip()
        self._buffer = ""
        if rest:
            self._sentence_q.put(rest)
        self._sentence_q.put(None)   # sentinel: stream finished
        self._stream_done.set()

    def is_speaking_or_pending(self) -> bool:
        """True while sentences remain queued, synthesizing, or playing."""
        with self._lock:
            playing = self.is_speaking_locked()
        pending = not self._sentence_q.empty() or self._speaking_state.is_set()
        worker_alive = self._stream_thread is not None \
            and self._stream_thread.is_alive()
        return playing or (pending and worker_alive)

    def _reset_stream(self) -> None:
        self._buffer = ""
        # drain any leftover queue without processing
        try:
            while True:
                self._sentence_q.get_nowait()
        except queue.Empty:
            pass
        self._stream_done.clear()

    # ---------------------------------------------------------------- state
    def is_speaking(self) -> bool:
        with self._lock:
            return self._current is not None \
                and self._current._thread is not None \
                and self._current._thread.is_alive()

    def is_speaking_or_hangover(self) -> bool:
        """Anti-self-trigger: True while playing OR shortly after."""
        import time
        with self._lock:
            if self.is_speaking_locked():
                return True
            now = time.monotonic() * 1000.0
            return self._hangover_until_ms is not None \
                and now < self._hangover_until_ms

    def is_speaking_locked(self) -> bool:
        return self._current is not None and self._current._thread is not None \
            and self._current._thread.is_alive()

    # ---------------------------------------------------------------- api
    def speak_text(self, text: str, voice: str | None = None,
                   speed: float = 1.0) -> bool:
        """Synthesize and start async playback. Interrupts current audio.
        Returns False when synthesis fails (error raised by caller reading
        last_error)."""
        self.stop()
        request = TTSRequest(text=text, voice=voice, speed=speed,
                             cancel_event=self._cancel)
        wav = self.provider.synthesize(request)   # worker thread context
        return self.play_wav(wav)

    def play_wav(self, wav_bytes: bytes) -> bool:
        pcm, rate = wav_to_pcm(wav_bytes)
        return self.play_pcm(pcm, rate)

    def play_pcm(self, pcm: np.ndarray, rate: int) -> bool:
        import time
        # interrupt any current utterance WITHOUT draining the streaming
        # sentence queue (the stream worker calls this per sentence)
        self._interrupt_current()
        self._cancel.clear()
        with self._lock:
            self._speaking_since_ms = time.monotonic() * 1000.0
            stream = PlaybackStream(
                pcm, rate, self.volume, self._cancel,
                done_callback=self._on_done, device=self.device_index)
            self._current = stream
            self._hangover_until_ms = None
        stream.start()
        if self.on_speaking_changed:
            self.on_speaking_changed(True)
        return True

    def _interrupt_current(self) -> None:
        """Cancel only the current playback; queue stays intact."""
        self._cancel.set()
        with self._lock:
            current = self._current
        if current is not None:
            current.wait(timeout=1.0)
        self._cancel.clear()

    def _on_done(self, cancelled: bool) -> None:
        import time
        with self._lock:
            self._hangover_until_ms = time.monotonic() * 1000.0 + _HANGOVER_MS
            self._current = None
        if self.on_speaking_changed:
            self.on_speaking_changed(False)
        if self.on_playback_done is not None:
            try:
                self.on_playback_done(cancelled)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        """Cancel current playback immediately (user interrupt / END)."""
        self._cancel.set()
        self._reset_stream()
        with self._lock:
            current = self._current
        if current is not None:
            current.wait(timeout=1.0)
        self._cancel.clear()

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, float(volume)))

    def set_device(self, device_index: int | None) -> None:
        self.device_index = device_index

    @staticmethod
    def playback_backend_available() -> tuple[bool, str]:
        if _sd is None:
            return False, f"audio backend unavailable: {_SD_ERROR}"
        return True, "sounddevice playback ok"


def _sentence_end(text: str) -> int:
    """Index just past the first sentence terminator (0 = none yet)."""
    for i, ch in enumerate(text):
        if ch in ".!?":
            j = i + 1
            while j < len(text) and text[j] in " \u201d'\")\n":
                j += 1
            return j
    if "\n" in text:
        return text.index("\n") + 1
    return 0
