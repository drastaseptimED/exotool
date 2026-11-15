#!/usr/bin/env bash
# Creates a start menu entry and a desktop icon for ED ExoTool.
# Run it again if you move the ed-exotool folder somewhere else.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRY="[Desktop Entry]
Type=Application
Name=ED ExoTool
Comment=Elite Dangerous exobiology dashboard
Exec=python3 \"$DIR/exotool.py\"
Icon=$DIR/web/icon.svg
Terminal=true
Categories=Game;Utility;"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
printf '%s\n' "$ENTRY" > "$APPS/ed-exotool.desktop"
chmod +x "$APPS/ed-exotool.desktop"
echo "Start menu entry created: $APPS/ed-exotool.desktop"

DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP" ]; then
  cp "$APPS/ed-exotool.desktop" "$DESKTOP/"
  chmod +x "$DESKTOP/ed-exotool.desktop"
  echo "Desktop icon created: $DESKTOP/ed-exotool.desktop"
fi
