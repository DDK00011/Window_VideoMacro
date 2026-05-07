@echo off
chcp 65001 >nul
REM ====================================================
REM   AutoClicker - Scheduled multi-click runner
REM   1h 45min wait, 9 coordinates, 10s interval
REM   Edit schedule_multi_click.py to change config.
REM ====================================================

cd /d "%~dp0"

set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
    where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

%PYCMD% -c "import pyautogui" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pyautogui not installed. Run install.bat first.
    pause
    exit /b 1
)

%PYCMD% schedule_multi_click.py

echo.
echo [DONE] Press any key to close this window.
pause
