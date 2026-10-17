@echo off
setlocal enabledelayedexpansion
title AGY 2.0 // Universal Workstation & Command Center

echo ==================================================================
echo   AGY 2.0 // Workstation Bridge (PC & Mobile Universal Setup)
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

:: 3. Verify / Auto-install dependencies
python -c "import starlette, uvicorn, multipart, websockets" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [*] Installing required dependencies (starlette, uvicorn, python-multipart, websockets)...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [!] pip install failed. Please check your internet connection.
        pause
        exit /b 1
    )
    echo [+] Dependencies installed successfully.
)

:: 4. Launch Universal Supervisor
echo [*] Launching AGY Universal Workstation Engine...
python start.py
if %ERRORLEVEL% neq 0 (
    echo [!] AGY process exited with error code %ERRORLEVEL%.
    pause
)
