#!/data/data/com.termux/files/usr/bin/bash
if [ ! -f /data/data/com.termux/files/usr/bin/bash ]; then
    exec /usr/bin/env bash "$0" "$@"
fi
# ==============================================================================
# REAGY // Universal Workstation & Command Center (Linux / Termux / macOS)
# ==============================================================================
set -e


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "  REAGY // Workstation Bridge (PC & Mobile Universal Setup)"
echo "=================================================================="

# 1. Acquire Termux wake lock if on Android
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

# Pre-flight cleanup: Terminate any old lingering servers holding port 8090
if command -v lsof >/dev/null 2>&1; then
    OLD_PIDS=$(lsof -t -i:8090 2>/dev/null || true)
    if [ -n "$OLD_PIDS" ]; then
        echo "[*] Cleaning up lingering processes on port 8090: $OLD_PIDS"
        kill -9 $OLD_PIDS 2>/dev/null || true
        sleep 1
    fi
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

# 4. Verify / Auto-install Antigravity CLI (agy) if missing
if ! command -v agy >/dev/null 2>&1 && [ ! -f "$HOME/bin/agy" ] && [ ! -f "/data/data/com.termux/files/usr/bin/agy" ]; then
    echo "[*] Checking Antigravity CLI (agy)..."
    if command -v npm >/dev/null 2>&1; then
        npm install -g @google/antigravity-cli >/dev/null 2>&1 || true
    fi
fi


# 5. Auto-accept agy CLI onboarding terms in settings.json to prevent TUI blocking
$PYTHON_BIN -c "import json, os, pathlib; p = pathlib.Path.home() / '.gemini' / 'antigravity-cli' / 'settings.json'; p.parent.mkdir(parents=True, exist_ok=True); data = json.loads(p.read_text('utf-8')) if p.exists() else {}; data['has_accepted_terms'] = True; data['accepted_terms_version'] = 1; p.write_text(json.dumps(data, indent=2), 'utf-8')" >/dev/null 2>&1 || true

# 5. Check dependencies
if ! $PYTHON_BIN -c "import starlette, uvicorn, multipart, websockets" >/dev/null 2>&1; then
    echo "[*] Installing required packages from requirements.txt..."
    pip install -r requirements.txt || pip3 install -r requirements.txt || pip install --no-build-isolation -r requirements.txt
fi

# 6. Auto-setup widget shortcuts on Termux if not already created
if [ -d "/data/data/com.termux/files/home" ] && [ ! -f "$HOME/.shortcuts/REAGY.sh" ]; then
    if [ -f "launcher/install-widget.sh" ]; then
        bash launcher/install-widget.sh >/dev/null 2>&1 || true
    fi
fi

# 7. Launch Universal Engine
echo "[*] Launching REAGY Universal Engine..."
exec $PYTHON_BIN start.py
