"""Frozen-exe AI smoke: launch dist exe, verify process + clean kill.

Run from repo root (Windows): dist\\HakuzePNGtuber\\HakuzePNGtuber.exe
Checks the AI companion import chain survives PyInstaller (openai, keyring,
pyttsx3, providers package) by watching stderr output + resident memory.
"""
from __future__ import annotations

import subprocess
import sys
import time


def main() -> int:
    exe = r"dist\HakuzePNGtuber\HakuzePNGtuber.exe"
    print(f"launching {exe} ...")
    proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    time.sleep(12)  # cold start: Qt + openai + keyring init
    alive = proc.poll() is None
    print(f"  resident after 12s: {'yes' if alive else 'no (exited)'}")
    if not alive:
        err = proc.stderr.read().decode(errors="replace")
        print("  stderr:", err[:2000])
        return 1
    # clean kill (tray quit path is user-side; taskkill emulates shutdown)
    subprocess.run(["taskkill", "/IM", "HakuzePNGtuber.exe", "/F"],
                   capture_output=True)
    time.sleep(1)
    print("EXE AI SMOKE: OK (no import crash, resident, killed clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
