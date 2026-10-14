#!/data/data/com.termux/files/usr/bin/bash
# =======================================================
# AGY-Mobile 2.0 Production Launcher for Termux:Widget
# =======================================================

# 1. Acquire wake lock to prevent Android from sleeping
termux-wake-lock 2>/dev/null

# 2. Kill stale instances to prevent [Errno 98] port collision
pkill -9 -f server.py 2>/dev/null
sleep 1

# 3. Enter app directory and load environment variables from .env
APP_DIR="/data/data/com.termux/files/home/agy-mobile-app"
cd "$APP_DIR" || exit 1

if [ -f "$APP_DIR/.env" ]; then
    set -a
    source "$APP_DIR/.env"
    set +a
elif [ -f "$APP_DIR/../.env" ]; then
    set -a
    source "$APP_DIR/../.env"
    set +a
fi

# 4. Launch server detached with nohup
nohup python3 server.py > /sdcard/Download/server.log 2>&1 &

# 5. Ensure Cloudflare tunnel is running if installed
if ! pgrep -f cloudflared > /dev/null 2>&1; then
    if command -v cloudflared > /dev/null 2>&1; then
        nohup cloudflared tunnel run > /sdcard/Download/cloudflared.log 2>&1 &
    fi
fi

# 6. Status notification toast (Termux API)
if command -v termux-toast > /dev/null 2>&1; then
    termux-toast "⚡ AGY-Mobile 2.0 Online (Port ${AGY_HTTP_PORT:-8080}/${AGY_WS_PORT:-8081})"
fi

echo "AGY-Mobile 2.0 launched successfully."
