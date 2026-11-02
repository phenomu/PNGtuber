# Hakuze PNGtuber - Windows setup
# Creates a venv next to the project and installs dependencies.
# Run from Windows:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
param(
    [string]$Python = "py -3.12",
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
Write-Host "== Hakuze PNGtuber setup ==" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

Push-Location $ProjectRoot

# --- locate python ---------------------------------------------------
try {
    & py -3.12 --version 2>$null
    $pyCmd = "py -3.12"
} catch {
    try {
        & py -3.11 --version 2>$null
        $pyCmd = "py -3.11"
    } catch {
        $pyCmd = "python"
    }
}
Write-Host "Using: $pyCmd"

# --- venv -------------------------------------------------------------
if (-not (Test-Path ".wvenv")) {
    Write-Host "Creating virtual environment .wvenv ..."
    & $pyCmd -m venv .wvenv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}

$venvPy = Join-Path $ProjectRoot ".wvenv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "venv python not found at $venvPy" }

# --- deps -------------------------------------------------------------
Write-Host "Upgrading pip ..."
& $venvPy -m pip install --upgrade pip --quiet
Write-Host "Installing runtime + dev dependencies ..."
& $venvPy -m pip install -r requirements.txt -r requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& $venvPy -c "import PySide6, numpy, sounddevice, PIL; print('deps OK:', PySide6.__version__)"

Pop-Location
Write-Host ""
Write-Host "Setup complete. Launch with:" -ForegroundColor Green
Write-Host "    .\run.cmd        (simplest - double-click works too)"
Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1"
