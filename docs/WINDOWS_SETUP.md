# WINDOWS_SETUP

## From source

1. Install Python 3.11+ (3.12 recommended) from python.org — the `py`
   launcher is included.
2. Clone and enter the repo (PowerShell):

   ```powershell
   git clone https://github.com/phenomu/PNGtuber.git
   cd PNGtuber
   ```

3. Set up the venv + dependencies:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
   ```

   Creates `.wvenv\` and installs runtime + dev dependencies
   (PySide6, sounddevice, NumPy, Pillow, pytest, PyInstaller).

4. Launch:

   ```powershell
   powershell -File scripts\run_windows.ps1
   ```

   The settings window appears; a tray icon runs the app in the background.
   Double-click the tray icon to reopen the window after minimizing.

## From a release build

1. Download + unzip the release.
2. Run `HakuzePNGtuber\HakuzePNGtuber.exe`.
3. Settings live in `%APPDATA%\HakuzePNGtuber\settings.json` — delete that
   file to reset everything.

## Troubleshooting

- **"audio backend unavailable" / no devices**: ensure a microphone is
  connected and Windows privacy settings allow desktop apps to access the
  microphone (Settings → Privacy & security → Microphone).
- **Overlay not visible**: check the Overlay tab → Start overlay; the window
  is frameless, so look for it near your saved position (default 120,120).
- **Avatar doesn't switch while talking**: run Calibrate (Audio tab), then
  verify the level meter moves while you speak; raise sensitivity.
- **Missing art warning**: select your own PNGs in the Avatar tab.
- **Antivirus flags the exe**: PyInstaller one-folder builds occasionally
  trip heuristics; build from source with `scripts\build_windows.ps1`.
