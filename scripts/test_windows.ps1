# Run the headless test suite on Windows (inside .wvenv).
# powershell -ExecutionPolicy Bypass -File scripts\test_windows.ps1
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
)

$ErrorActionPreference = "Stop"
Push-Location $ProjectRoot

$venvPy = Join-Path $ProjectRoot ".wvenv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Virtual environment not found. Run scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "== Running test suite (Windows python) ==" -ForegroundColor Cyan
& $venvPy -m pytest tests -v
$code = $LASTEXITCODE

Pop-Location
exit $code
