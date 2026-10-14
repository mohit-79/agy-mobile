#!/data/data/com.termux/files/usr/bin/bash
# Install AGY-Mobile launcher shortcuts into Termux:Widget directories

SHORTCUTS_DIR="$HOME/.shortcuts"
TASKS_DIR="$SHORTCUTS_DIR/tasks"

mkdir -p "$SHORTCUTS_DIR" "$TASKS_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/agy-mobile.sh" "$SHORTCUTS_DIR/agy-mobile.sh"
cp "$SCRIPT_DIR/agy-mobile.sh" "$SHORTCUTS_DIR/AGY-Mobile.sh"
cp "$SCRIPT_DIR/agy-mobile.sh" "$TASKS_DIR/agy-mobile.sh"

chmod +x "$SHORTCUTS_DIR/agy-mobile.sh" "$SHORTCUTS_DIR/AGY-Mobile.sh" "$TASKS_DIR/agy-mobile.sh"

echo "✅ Installed AGY-Mobile shortcuts into ~/.shortcuts and ~/.shortcuts/tasks/"
