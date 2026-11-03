# Changelog

## [0.2.0] — AI Companion Mode (beta)

### Added
- AI Companion: voice-driven assistant (END hotkey toggle)
- State machine: OFF/IDLE/LISTENING/TRANSCRIBING/THINKING/RESPONDING/SPEAKING/ERROR
- Direct OpenAI STT (gpt-4o-mini-transcribe default, configurable)
- OpenAI-compatible LLM (9Router default base URL, configurable model)
- TTS providers: Windows local SAPI + OpenAI TTS, switchable at runtime
- Output modes: text / voice / both
- Animated dialogue bubble: typewriter, streaming append, unicode/emoji,
  max-lines clamp, screen-edge aware, never renders HTML
- Global persona (independent of contexts) + dynamic Context Manager with
  per-context instructions/knowledge/history; quick switch via tray
- Wake modes: energy / phrase-verify / manual listen
- Barge-in interruption (configurable policy)
- Credentials: Windows Credential Manager via keyring (env/session fallback)
- AI Assistant settings tab (control/STT/LLM/TTS/persona/contexts/bubble/
  conversation sections)
- 60 new tests (131 total) + headless UI smoke + Windows AI smoke scripts

## [0.1.0] — Initial release

- Microphone-driven idle/talking avatar switching (RMS + hysteresis)
- Transparent click-through overlay, OBS-ready
- 2-phase calibration, cyberpunk settings GUI, system tray
- PyInstaller one-folder Windows build


All notable changes to Hakuze PNGtuber are documented here.
Format follows Keep a Changelog; versioning is SemVer.

## [0.1.0] — 2026-11-02

First working MVP.

### Added
- Microphone speech detection with hysteresis, noise gate, attack/release,
  min-speech duration; guided 2-phase calibration
- Real-time audio engine (sounddevice + NumPy): 20ms blocks, lightweight
  callback, thread-safe queue, hot device switching, graceful degradation
- Transparent frameless click-through avatar overlay (~60 FPS, always-on-top)
- Idle grayscale / talking full-color state switching with eased lift and
  damped bounce animation, smooth return, optional breathing
- Cyberpunk settings GUI: Avatar / Audio / Animation / Overlay / App tabs,
  live level meter, threshold readout, edit-mode drag positioning
- Persistent validated settings in %APPDATA% with atomic writes
- Procedural placeholder artwork (idle + talking, user-replaceable)
- System tray integration, minimize-to-tray, autostart option (Windows)
- 71 automated tests (headless, cross-platform)
- Windows packaging: PyInstaller one-folder build, setup/run/build/test
  PowerShell scripts, WSL dev setup script
- Documentation: README, ARCHITECTURE, WINDOWS_SETUP, OBS_SETUP, DEVELOPMENT
