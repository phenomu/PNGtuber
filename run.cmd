@echo off
rem Hakuze PNGtuber launcher - .cmd files bypass PowerShell execution policy.
rem Double-click this file or run from a terminal.
rem This file lives in the project ROOT, so ROOT is just its own directory.
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%\.wvenv\Scripts\python.exe" goto :found
echo Virtual environment not found. Run setup first:
echo   setup.cmd   (in the project root)
pause
exit /b 1
:found
set "PYTHONPATH=%ROOT%src"
"%ROOT%.wvenv\Scripts\python.exe" -m hakuze_pngtuber.main
endlocal
