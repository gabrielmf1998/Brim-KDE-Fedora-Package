#!/usr/bin/env bash
# Installs Brim for the current user. No root, nothing outside $HOME.
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin"

echo "Installing Brim from $SRC"

mkdir -p "$APPS" "$ICONS" "$BIN"

install -m 644 "$SRC/data/icons/brim.svg" "$ICONS/brim.svg"

sed "s|BRIM_EXEC|$SRC/brim.sh|" "$SRC/data/brim.desktop" > "$APPS/brim.desktop"
chmod 644 "$APPS/brim.desktop"

ln -sf "$SRC/brim.sh" "$BIN/brim"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && \
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "Done."
echo "  Launcher   $APPS/brim.desktop"
echo "  Icon       $ICONS/brim.svg"
echo "  Command    $BIN/brim"
echo
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Note: $BIN is not on your PATH yet." ;;
esac
echo "Run it with: brim"
