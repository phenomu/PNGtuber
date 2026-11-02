# DEVELOPMENT

## Layout

```
src/hakuze_pngtuber/     # application package (core/ui/utils)
tests/                   # headless pytest suite (71 tests)
scripts/                 # Windows PS scripts + PyInstaller spec + smoke
docs/                    # these documents
assets/character/        # bundled idle/talking PNGs (placeholder art)
config/                  # bundled default settings
```

## Test pyramid

1. **Headless unit tests** (`python -m pytest`): detector hysteresis,
   animation math, settings persistence/validation, image ops. Run anywhere,
   no audio, no display — this is the dev loop in WSL.
2. **Windows smoke** (`scripts/smoke_windows.py` in `.wvenv`): real device
   enumeration, live stream RMS blocks, full app construction, event loop.
3. **Frozen exe check**: launch, verify tray + window + overlay, taskkill.

## WSL notes

- WSLg (`DISPLAY=:0`) lets the Qt GUI run for quick visual checks.
- PortAudio is absent in WSL, so `AudioEngine` reports
  "audio backend unavailable" — by design; live audio only on Windows.
- The Windows build mirror lives at `C:\Users\hadri\PNGtuber-dev`
  (accessible as `/mnt/c/Users/hadri/PNGtuber-dev` from WSL). Windows
  Python over the WSL 9P filesystem is too slow for venv operations, so
  mirror the repo there before running Windows python against it.

## Conventions

- Core modules import nothing from `ui/`. UI imports from `core/` and
  `utils/` only.
- Parameter bundles are frozen dataclasses with `validated()`.
- Keep the audio callback minimal (RMS + queue).
- Every commit message: what + why, one logical change per commit.

## Adding a feature

1. Write/extend headless tests for the logic.
2. Implement in `core/` (Qt-free) or `ui/` (presentation).
3. Wire through settings if user-configurable (config/default_settings.json
   + SettingsManager ranges).
4. Run `python -m pytest`; on Windows also `scripts\smoke_windows.py`.
5. Update TRACKER.md + relevant docs in the same commit.
