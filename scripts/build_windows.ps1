# Hakuze PNGtuber - build a Windows one-folder distribution with PyInstaller
# Output: dist\HakuzePNGtuber\HakuzePNGtuber.exe + assets + config
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$OutName = "HakuzePNGtuber"
)

$ErrorActionPreference = "Stop"
Push-Location $ProjectRoot

$venvPy = Join-Path $ProjectRoot ".wvenv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Virtual environment not found. Run scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "== Building $OutName (one-folder) ==" -ForegroundColor Cyan

& $venvPy -m PyInstaller `
    --noconfirm `
    --clean `
    --name $OutName `
    --onedir `
    --windowed `
    --icon assets/icons/app.ico `
    --add-data "assets;assets" `
    --add-data "config;config" `
    --paths "src" `
    --specpath "scripts" `
    "src\hakuze_pngtuber\main.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$distDir = Join-Path $ProjectRoot "dist\$OutName"
Write-Host ""
Write-Host "Build OK -> $distDir" -ForegroundColor Green
Get-ChildItem $distDir | Select-Object Name, Length | Format-Table -AutoSize

Pop-Location
