#!/usr/bin/env bash
# ==================================================================
# AGY 2.0 // Universal Automated Full-Stack Installer
# ==================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "  AGY 2.0 // Universal Automated Installer"
echo "=================================================================="

# 1. Termux package prerequisites
if command -v pkg >/dev/null 2>&1; then
    echo "📦 [Termux] Updating packages and installing prerequisites..."
    pkg update -y && pkg install -y python python-pip termux-api proot
fi

# 2. Python dependencies
echo "🐍 Installing Python dependencies..."
python3 -m pip install -r requirements.txt 2>/dev/null || pip install -r requirements.txt || pip install --no-build-isolation -r requirements.txt

# 3. Environment setup
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "⚙️ Initialized .env from template. Update your PIN or domain in .env as needed."
fi

# 4. Make all launcher scripts executable
chmod +x start.sh install.sh launcher/*.sh 2>/dev/null || true

# 5. Setup Termux widget if on Termux
if [ -d "/data/data/com.termux/files/home" ] && [ -f "launcher/install-widget.sh" ]; then
    echo "📲 Setting up Termux:Widget shortcuts..."
    bash launcher/install-widget.sh
fi

echo "=================================================================="
echo "🎉 Setup complete! Launch using:"
echo "   - Windows PC:        Double-click start.bat"
echo "   - Linux / Termux:    ./start.sh"
echo "=================================================================="
