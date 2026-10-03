@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python install.py %*
) else (
    py -3 install.py %*
)
if errorlevel 1 (
    echo Installation failed. Install Python 3.10 or newer with pip and try again.
    pause
    exit /b 1
)
pause
