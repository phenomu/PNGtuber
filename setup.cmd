@echo off
rem Hakuze PNGtuber setup - .cmd wrapper so PowerShell execution policy
rem never blocks first-time setup. Creates .wvenv and installs deps.
rem This file lives in the project ROOT, so ROOT is just its own directory.
setlocal
set "ROOT=%~dp0"
echo == Hakuze PNGtuber setup ==
echo Project root: %ROOT%

py -3.12 --version >nul 2>&1
if errorlevel 1 (
    py -3.11 --version >nul 2>&1
    if errorlevel 1 (
        set "PYCMD=python"
    ) else (
        set "PYCMD=py -3.11"
    )
) else (
    set "PYCMD=py -3.12"
)

if not exist "%ROOT%.wvenv" (
    echo Creating virtual environment .wvenv ...
    %PYCMD% -m venv "%ROOT%.wvenv"
    if errorlevel 1 (
        echo venv creation failed - install Python 3.11+ from python.org
        pause
        exit /b 1
    )
)

set "VENV=%ROOT%.wvenv\Scripts\python.exe"
"%VENV%" -m pip install --upgrade pip --quiet
"%VENV%" -m pip install -r "%ROOT%requirements.txt" -r "%ROOT%requirements-dev.txt" --quiet
if errorlevel 1 (
    echo pip install failed
    pause
    exit /b 1
)

"%VENV%" -c "import PySide6, numpy, sounddevice, PIL; print('deps OK:', PySide6.__version__)"
echo.
echo Setup complete. Launch with: run.cmd  (in the project root)
pause
endlocal
