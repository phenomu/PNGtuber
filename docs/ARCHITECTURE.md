# ARCHITECTURE

## Layers

```
┌──────────────────────────── UI (PySide6) ────────────────────────────┐
│ settings_window.py   avatar_overlay.py   widgets.py   styles.py     │
│  (control panel)      (transparent       (sliders,    (neon QSS)    │
│                        overlay window)    meter)                    │
└──────────────┬──────────────────┬──────────────────┬────────────────┘
               │ reads/writes     │ paints frames    │
┌──────────────▼──────────────────▼──────────────────▼────────────────┐
│ CORE (Qt-free, headless-testable)                                   │
│ audio_engine     speech_detector    avatar_controller  animation    │
│ (sounddevice)    (hysteresis gate)  (state bridge)     (offset math)│
│ settings_manager (defaults+user, atomic)   asset_manager (fallback) │
└──────────────┬──────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────────┐
│ UTILS: image_utils (RGBA/desat/placeholders), audio_utils (RMS),    │
│        platform_utils (winreg, click-through, resource paths)       │
└─────────────────────────────────────────────────────────────────────┘
```

## Threading model

- **PortAudio callback thread**: computes block RMS, pushes (level, t_ms)
  into a 64-slot queue. Nothing else. No Qt, no locks held, no images.
- **GUI thread**: 20ms `QTimer` poll drains the queue, feeds
  `AvatarController.feed_level()`, updates meter/state labels, mirrors state
  into the overlay.
- **Overlay paint**: 16ms precise timer redraws; animation offset comes from
  `AnimationEngine.frame(talking, now)` — pure function of time + state,
  so frames are always continuous (no jumps on image swap).

## Speech detection

Envelope follower with hysteresis:

- enter: level ≥ threshold for `attack_ms` (default 30)
- exit: level < threshold×0.75 continuously for
  `exit_hold_ms = max(silence_ms, release_ms)` (default 300)
- levels below `noise_gate` are floored to zero
- UI sensitivity scales the raw level before the detector:
  `eff = level × (1 + 3 × sensitivity)`

Calibration measures ambient noise (~3 s) and normal speech (~4 s), suggests
`noise_floor×1.5 + 0.35×(speech − floor)`, rejects unusable separations.

## Animation

Talking offset(t) = lift·ease_out_cubic(p) + bounce·e^(-2p)·sin(2πp)
(+ sustain bob sine after p = 1), where p = elapsed/duration (speed-scaled).
Idle offset(t) = exit_offset·(1 − ease_in_out_cubic(q)) + optional breath sine.
All params clamped in `AnimParams.validated()`.

## Settings

Bundled `config/default_settings.json` ← deep-merged ←
`%APPDATA%\HakuzePNGtuber\settings.json`. Values validated against per-key
ranges/bools; corrupt user file falls back to defaults. Saves are atomic
(temp file + `os.replace` + fsync).

## Asset resolution

`AssetManager` picks: user-configured path > bundled
`assets/character/{idle,talking}.png` > in-memory procedural placeholder.
Missing art never crashes; UI shows a one-time warning.

## Packaging

PyInstaller one-folder; entry is `run_app.py` (absolute import workaround
for frozen relative imports). `assets/` and `config/` are added as datas and
resolved at runtime via `sys._MEIPASS` (see `platform_utils.resource_path`).
