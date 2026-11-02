# OBS_SETUP

Add the Hakuze avatar to OBS Studio as a transparent overlay source.

## Steps

1. Start the app and launch the overlay
   (Overlay tab → **Start overlay**, or enable "show on start").
2. In OBS: **Sources → + → Window Capture**.
3. Properties:
   - **Window**: `Hakuze PNGtuber Overlay` (title set explicitly for matching)
   - **Capture Method**: **Windows 10 (1903 and up)** (Windows Graphics
     Capture) — this preserves transparency on translucent always-on-top
     Qt windows.
4. The source appears with transparent surroundings. Hold **Alt** and drag
   the source edges to crop away the window margins around the character.
5. Scale/move the source like any other. The overlay window itself is
   click-through, so it never steals focus from Minecraft.

## Why Window Capture

The overlay is a native top-level translucent window, so window capture is
the lowest-complexity reliable path (PROMPT.md §8: avoid extra complexity).
Windows Graphics Capture handles layered windows with alpha correctly on
Windows 10 1903+ / Windows 11.

## Validation checklist (run once before first stream)

- [ ] Level meter moves while speaking (Audio tab)
- [ ] STATE label flips to TALKING when speaking, back to IDLE after a pause
- [ ] Overlay shows the avatar, transparent background in OBS program view
- [ ] Character switches sprite while talking (mouth opens)
- [ ] No black rectangle behind the character in OBS
- [ ] Recording a 10s test clip shows the avatar with clean edges

## Fallbacks (only if Window Capture fails on your machine)

- Switch the capture method dropdown to **BitBlt** and re-test; some
  driver combos handle it better.
- As a last resort, use **Game Capture** with "Capture specific window"
  pointing at the overlay (less reliable with layered windows).
- If alpha is lost entirely, position the overlay inside OBS over a
  matching background and use a Color Key filter on the captured window
  background — a workaround, not a fix; report the issue.

## Performance

The app targets <1% CPU on a modern desktop (RMS threshold math, no NN, no
GPU). During Minecraft + OBS streaming it should be imperceptible; check
Task Manager → `HakuzePNGtuber.exe` if in doubt.
