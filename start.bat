@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title REAGY // Universal Workstation and Command Center

echo ==================================================================
echo   REAGY // Universal Workstation and Command Center (1-Click)
echo ==================================================================

:: 1. Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Python was not found in your PATH.
    echo Please install Python 3.10+ from https://python.org and ensure "Add to PATH" is checked.
    pause
    exit /b 1
)

:: 2. Auto-initialize .env if missing
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [+] Initialized .env configuration from template.
    )
)

:: 3. Verify / Auto-install Antigravity CLI if missing
where agy >nul 2>&1
if %ERRORLEVEL% equ 0 goto agy_found
if exist "%LOCALAPPDATA%\agy\bin\agy.exe" (
    set "PATH=%LOCALAPPDATA%\agy\bin;!PATH!"
    goto agy_found
)
if exist "%USERPROFILE%\AppData\Local\agy\bin\agy.exe" (
    set "PATH=%USERPROFILE%\AppData\Local\agy\bin;!PATH!"
    goto agy_found
)

echo [*] Antigravity CLI [agy] not found. Checking npm install...
where npm >nul 2>&1
if %ERRORLEVEL% equ 0 (
    call npm install -g @google/antigravity-cli >nul 2>&1
)

:agy_found


:: 4. Auto-accept agy CLI onboarding terms in settings.json to prevent TUI blocking
python -c "import json, os, pathlib; p = pathlib.Path.home() / '.gemini' / 'antigravity-cli' / 'settings.json'; p.parent.mkdir(parents=True, exist_ok=True); data = json.loads(p.read_text('utf-8')) if p.exists() else {}; data['has_accepted_terms'] = True; data['accepted_terms_version'] = 1; p.write_text(json.dumps(data, indent=2), 'utf-8')" >nul 2>&1

:: 4. Verify / Auto-install dependencies
python -c "import starlette, uvicorn, multipart, websockets, winpty" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [*] Installing required dependencies from requirements.txt...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [!] pip install failed. Please check your internet connection.
        pause
        exit /b 1
    )
    echo [+] Dependencies installed successfully.
)

:: 5. Launch Universal Supervisor
echo [*] Launching REAGY Universal Workstation Engine...
python start.py
if %ERRORLEVEL% neq 0 (
    echo [!] REAGY process exited with error code %ERRORLEVEL%.
    pause
)
