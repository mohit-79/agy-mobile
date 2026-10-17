#!/data/data/com.termux/files/usr/bin/bash
# =======================================================
# AGY 2.0 // Termux:Widget 1-Tap Launcher
# =======================================================

# Acquire wake lock to prevent Android CPU sleep
termux-wake-lock 2>/dev/null || true

# Find repo directory
REPO_DIR="$HOME/agy-mobile"
if [ ! -d "$REPO_DIR" ]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

cd "$REPO_DIR" || exit 1

# Launch Universal Engine detached via nohup
nohup python3 start.py > "$HOME/agy.log" 2>&1 &

if command -v termux-toast >/dev/null 2>&1; then
    termux-toast "⚡ AGY 2.0 Engine Starting... Check notification or browser."
fi
