#!/usr/bin/env python
"""PyInstaller entry launcher: absolute import so the package bundles cleanly."""
from hakuze_pngtuber.main import main

if __name__ == "__main__":
    raise SystemExit(main())
