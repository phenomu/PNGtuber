#!/usr/bin/env bash
# Hakuze PNGtuber - WSL dev environment setup (headless core tests only).
# The Windows GUI is run/tested via scripts/setup_windows.ps1 + run_windows.ps1.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-python3}

echo "== Hakuze PNGtuber WSL dev setup =="
$PYTHON --version

if [ ! -d .venv ]; then
    echo "Creating .venv ..."
    $PYTHON -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt pytest
# PySide6/sounddevice are optional here: core tests are headless and tolerate
# a missing PortAudio library (WSL has no Windows mic stack).
pip install --quiet PySide6 sounddevice 2>/dev/null || true

echo "Running headless test suite ..."
python -m pytest tests/ -q

echo ""
echo "WSL dev environment ready. Core tests are runnable here;"
echo "run the GUI on Windows: powershell -File scripts/run_windows.ps1"
