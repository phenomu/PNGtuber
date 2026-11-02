# Changelog

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
