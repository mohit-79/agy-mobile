#!/data/data/com.termux/files/usr/bin/bash
# =======================================================
# AGY-Mobile 2.0 Full-Stack Installer for Termux
# =======================================================
set -e

echo "📦 Installing system prerequisites..."
pkg update -y && pkg install -y python python-pip termux-api

echo "🐍 Installing Python dependencies..."
pip install -r agy-mobile-app/requirements.txt

echo "⚙️ Initializing environment configuration..."
if [ ! -f "agy-mobile-app/.env" ] && [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️ Created .env from template. Please update your confidential secrets in .env!"
fi

echo "📲 Setting up Termux:Widget shortcuts..."
bash launcher/install-widget.sh

echo "🔑 Setting executable permissions..."
chmod +x launcher/agy-mobile.sh launcher/AGY-Mobile.sh launcher/install-widget.sh agy-mobile.sh

echo "🎉 Installation complete! Tap the AGY-Mobile widget or run ./agy-mobile.sh to start."
