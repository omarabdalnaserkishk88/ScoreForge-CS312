@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 start.py
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python start.py
    goto done
)
echo Python was not found. Install Python 3.10 or newer, then run this file again.
echo During installation, enable "Add Python to PATH".
:done
pause
