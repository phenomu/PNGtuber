# Hakuze PNGtuber

Custom 2D PNG avatar streaming application for Windows. Your character switches
between **idle** and **talking** states automatically based on microphone input —
no Live2D, no face tracking, no webcam. Built for livestreaming Minecraft with
OBS Studio.

Lightweight by design: pure threshold-based detection (no neural network), low
CPU, ~60 FPS overlay, safe to run alongside games.

![screenshot placeholder](https://placehold.co/800x400/0b0e17/21e6ff?text=Hakuze+PNGtuber+Settings)

## Features

- **Microphone-driven state switching** — talk, the character talks; stop, it idles
- **Hysteresis + noise gate** — no flicker on soft speech, no triggering on fan noise
- **Calibration** — 2-phase guided mic calibration suggests a threshold
- **Transparent click-through overlay** — frameless, always-on-top, OBS-ready
- **Idle grayscale** — character desaturates at rest, colors pop when talking
- **Bounce animation** — eased lift + damped bounce, configurable
- **Cyberpunk settings GUI** — dark, neon cyan/purple, 5 tabs
- **System tray** — minimizes out of the way, double-click to reopen
- **Hot mic switching** — change device without restart
- **Placeholder art included** — drop in your own idle/talking PNGs

## Installation

### Option A — run from source (Windows)

Requires Python 3.11+ on Windows.

```powershell
git clone https://github.com/phenomu/PNGtuber.git
cd PNGtuber
.\setup.cmd
.\run.cmd
```

(`setup.cmd` / `run.cmd` are plain batch files — they work regardless of
PowerShell execution policy. PowerShell equivalents:
`powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1` /
`...\run_windows.ps1` — the `-ExecutionPolicy Bypass` flag is required on
default Windows installs.)

### Option B — prebuilt release

Download the latest release, unzip, run `HakuzePNGtuber.exe`.
No Python installation needed.

## Usage

1. Launch the app — the settings window opens with a live mic meter.
2. Check the **Audio** tab: pick your microphone, watch the level meter move.
3. Press **Calibrate**: stay silent ~3 s, then speak normally ~4 s. A threshold
   is suggested; tweak the slider if needed.
4. **Overlay** tab → **Start overlay**. A transparent avatar appears on screen.
5. In **Avatar** tab → **Edit position** (toggles dragging) to drag the avatar
   where you want it, then **Save position**.
6. Replace the placeholder art with your own PNGs: **select idle PNG** /
   **select talking PNG**. Both should be transparent-background PNGs with the
   same canvas size and character anchor.
7. Talk — the character bounces up and switches to the talking sprite;
   stop — it eases back down and desaturates.

## OBS Integration

1. In OBS: **Sources → + → Window Capture**
2. Window: **Hakuze PNGtuber Overlay**
3. Capture Method: **Windows 10 (1903 and up)** — preserves the transparent background
4. Crop the window margins if needed (hold **Alt** and drag the source edges)
5. The overlay is click-through, so it never steals focus from your game

For details see [docs/OBS_SETUP.md](docs/OBS_SETUP.md).

## Build Instructions

One-folder executable with PyInstaller (Windows, inside the project venv):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Output: `dist\HakuzePNGtuber\` containing `HakuzePNGtuber.exe`, `assets/`, `config/`.

## Development

- Python 3.11+, PySide6, sounddevice, NumPy, Pillow
- Layout: `src/hakuze_pngtuber/` (core / ui / utils), tests in `tests/`
- Headless test suite: `python -m pytest` (runs on any OS)
- Windows-only validation: `scripts\test_windows.ps1`, `scripts\smoke_windows.py`

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

1. Fork, branch, commit with clear messages
2. Keep dependencies minimal; no new heavy frameworks
3. `python -m pytest` must stay green
4. GUI changes must be verified on Windows

## License

MIT — see [LICENSE](LICENSE).

Avatar art is user-supplied; bundled placeholder art is generated and MIT-licensed.
