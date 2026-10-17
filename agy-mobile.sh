#!/data/data/com.termux/files/usr/bin/bash
# =======================================================
# AGY-Mobile 2.0 Production Launcher for Termux:Widget
# =======================================================

# 1. Acquire wake lock to keep background network alive
termux-wake-lock 2>/dev/null

# 2. DNS & SSL certificate environment for proot
export SSL_CERT_FILE=$PREFIX/etc/tls/cert.pem
echo "nameserver 1.1.1.1" > $PREFIX/etc/resolv.conf
echo "nameserver 8.8.8.8" >> $PREFIX/etc/resolv.conf

# 3. Terminate stale processes to prevent [Errno 98] port collision
pkill -9 -f server.py 2>/dev/null
pkill -9 cloudflared 2>/dev/null
sleep 1

# 4. Enter app directory and load environment variables
APP_DIR="/data/data/com.termux/files/home/agy-mobile-app"
cd "$APP_DIR" || exit 1

if [ -f "$APP_DIR/.env" ]; then
    set -a
    source "$APP_DIR/.env"
    set +a
fi

# 5. Launch Python backend server
nohup python3 server.py > /sdcard/Download/server.log 2>&1 &

# 6. Launch Cloudflare Tunnel using proot mount
nohup proot \
  -b $PREFIX/etc/resolv.conf:/etc/resolv.conf \
  -b $PREFIX/etc/tls/cert.pem:/etc/ssl/certs/ca-certificates.crt \
  cloudflared tunnel --config /data/data/com.termux/files/home/.cloudflared/config.yml run > /sdcard/Download/cloudflared.log 2>&1 &

# 7. Status notification toast
if command -v termux-toast > /dev/null 2>&1; then
    termux-toast "⚡ AGY-Mobile 2.0 Online: agy-a2.harjani.me"
fi

echo "AGY-Mobile 2.0 launched successfully."
