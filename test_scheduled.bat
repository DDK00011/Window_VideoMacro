@echo off
chcp 65001 >nul
REM ====================================================
REM   AutoClicker - Smoke test for schedule_multi_click.py
REM   Runs in 5 seconds with NO actual clicks (--dry-run --quick).
REM   Use this to verify the flow before running run_scheduled.bat.
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

echo [SMOKE TEST] Running schedule_multi_click.py --dry-run --quick
echo            (5-second wait, NO actual mouse clicks)
echo.
%PYCMD% schedule_multi_click.py --dry-run --quick

echo.
echo [SMOKE TEST DONE] If you saw 9 [DRY-RUN x/9] lines for the
echo                   correct coordinates, the flow is verified.
echo                   Now run_scheduled.bat is safe to use.
pause
