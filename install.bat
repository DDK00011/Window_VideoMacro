@echo off
REM ====================================================
REM   AutoClicker Dependency Installer (Windows)
REM   Installs pyautogui and other requirements.
REM   English-only messages to avoid encoding issues.
REM ====================================================

cd /d "%~dp0"

REM ----- 1) Locate Python -----
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
    where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    echo   IMPORTANT: check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM ----- 2) Show Python version -----
echo Using Python:
%PYCMD% --version
echo.

REM ----- 3) Install requirements -----
echo Installing dependencies from requirements.txt ...
echo.
%PYCMD% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed.
    echo   Check your internet connection or pip configuration.
    echo   You can also try: %PYCMD% -m pip install --user -r requirements.txt
    pause
    exit /b 1
)

echo.
echo ====================================================
echo   [OK] Installation complete.
echo   You can now double-click run_gui.bat (GUI mode)
echo   or run_console.bat (console mode).
echo ====================================================
pause
