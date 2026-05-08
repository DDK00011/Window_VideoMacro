@echo off
chcp 65001 >nul
REM ====================================================
REM   AutoClicker - PyInstaller EXE Builder (Windows)
REM   Builds dist\AutoClicker.exe (single file, windowed)
REM   Distribute the single .exe to PCs without Python.
REM ====================================================

cd /d "%~dp0"

REM ----- 1) Locate Python -----
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
    where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
    echo [ERROR] Python is not installed or not in PATH.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ----- 2) Verify runtime deps (pyautogui, Pillow) -----
%PYCMD% -c "import pyautogui, PIL" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Runtime deps missing. Run install.bat first.
    pause
    exit /b 1
)

REM ----- 3) Verify / install pyinstaller -----
%PYCMD% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] PyInstaller not found. Installing...
    echo.
    %PYCMD% -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo [ERROR] PyInstaller install failed.
        echo   Check your network or pip configuration.
        pause
        exit /b 1
    )
)

REM ----- 4) Clean previous build -----
if exist build (
    echo Cleaning old build/ folder...
    rmdir /s /q build
)
if exist dist\AutoClicker.exe (
    echo Removing old dist\AutoClicker.exe...
    del /q dist\AutoClicker.exe
)
if exist AutoClicker.spec (
    del /q AutoClicker.spec
)

REM ----- 5) Build single-file windowed EXE -----
echo.
echo ====================================================
echo Building AutoClicker.exe ^(single file, windowed^)...
echo This may take 30-90 seconds.
echo ====================================================
echo.
%PYCMD% -m PyInstaller --noconfirm --onefile --windowed --name AutoClicker gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)

REM ----- 6) Done -----
echo.
echo ====================================================
echo   [OK] Build complete.
echo   Output: dist\AutoClicker.exe
echo.
echo   - Single file, no Python required on target PC
echo   - Some antivirus may flag PyInstaller builds
echo     ^(known false positive^); add to allow-list if needed.
echo ====================================================
echo.
pause
