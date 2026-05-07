@echo off
REM ====================================================
REM   AutoClicker GUI Launcher (Windows)
REM   Double-click to run.
REM   All messages in English to avoid Windows cmd
REM   cp949/UTF-8 encoding mismatch issues.
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

REM ----- 2) Check pyautogui -----
%PYCMD% -c "import pyautogui" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] pyautogui is not installed.
    echo.
    echo   Run this command first:
    echo       %PYCMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM ----- 3) Run GUI -----
%PYCMD% gui.py
if errorlevel 1 (
    echo.
    echo [ERROR] gui.py exited with an error.
    echo   See the messages above for details.
    pause
)
