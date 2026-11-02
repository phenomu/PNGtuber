# Hakuze PNGtuber - run on Windows
# Launches the app inside the .wvenv virtual environment.
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
$venvPy = Join-Path $ProjectRoot ".wvenv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "Virtual environment not found. Run scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
& $venvPy -m hakuze_pngtuber.main
exit $LASTEXITCODE
