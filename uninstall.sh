#!/usr/bin/env bash
# Removes what install.sh put in place. Leaves the checkout alone.
set -euo pipefail
rm -f "$HOME/.local/share/applications/brim.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/brim.svg"
rm -f "$HOME/.local/bin/brim"
rm -f "$HOME/.config/autostart/brim.desktop"
echo "Brim launcher removed. Settings in ~/.config/brim were kept."
echo "Delete the checkout to finish removing it."
