#!/usr/bin/env bash
# ==================================================================
# AGY 2.0 // Universal Workstation & Command Center (Linux / Termux)
# ==================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "  AGY 2.0 // Workstation Bridge (PC & Mobile Universal Setup)"
echo "=================================================================="

# 1. Acquire Termux wake lock if on Android
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

# 2. Check Python
PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        echo "[!] Python 3 is not installed."
        if command -v pkg >/dev/null 2>&1; then
            echo "[*] Installing Python on Termux..."
            pkg update -y && pkg install -y python python-pip
        else
            echo "Please install Python 3 and pip."
            exit 1
        fi
    fi
fi

# 3. Auto-initialize .env if missing
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "[+] Initialized .env configuration from template."
fi

# 4. Check dependencies
if ! $PYTHON_BIN -c "import starlette, uvicorn, multipart, websockets" >/dev/null 2>&1; then
    echo "[*] Installing required packages..."
    pip install -r requirements.txt || pip3 install -r requirements.txt || pip install --no-build-isolation -r requirements.txt
fi

# 5. Launch Universal Engine
echo "[*] Launching AGY Universal Engine..."
exec $PYTHON_BIN start.py
