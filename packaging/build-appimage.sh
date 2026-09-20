#!/usr/bin/env bash
# Builds Brim-<version>-x86_64.AppImage into dist/
#
# This is a thin AppImage on purpose. Brim drives the running system's
# package manager, so it has to use that system's own python3-libdnf5:
# a bundled copy would be the wrong version the moment dnf5 moves. The
# AppImage therefore ships Brim itself and leans on two system packages,
# and AppRun says so plainly when they are missing.
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/brim/version.py")"
TOOL="${APPIMAGETOOL:-$(command -v appimagetool || true)}"

if [ -z "$TOOL" ]; then
  echo "appimagetool not found." >&2
  echo "Get it from https://github.com/AppImage/appimagetool/releases" >&2
  echo "then re-run with APPIMAGETOOL=/path/to/appimagetool" >&2
  exit 1
fi

APPDIR="$(mktemp -d)/Brim.AppDir"
trap 'rm -rf "$(dirname "$APPDIR")"' EXIT

echo "Building Brim $VERSION AppImage"

mkdir -p "$APPDIR/usr/lib/brim" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/applications"

tar --exclude-vcs --exclude='__pycache__' --exclude='*.pyc' \
    -C "$SRC" -cf - brim | tar -C "$APPDIR/usr/lib/brim" -xf -

install -m 644 "$SRC/data/icons/brim.svg" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps/brim.svg"
install -m 644 "$SRC/data/icons/brim.svg" "$APPDIR/brim.svg"

sed 's|BRIM_EXEC|brim|' "$SRC/data/brim.desktop" \
  > "$APPDIR/usr/share/applications/brim.desktop"
cp "$APPDIR/usr/share/applications/brim.desktop" "$APPDIR/brim.desktop"

cat > "$APPDIR/AppRun" <<'RUNEOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONPATH="$HERE/usr/lib/brim${PYTHONPATH:+:$PYTHONPATH}"

die() {
  printf '%s\n' "$@" >&2
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --error "$(printf '%s\n' "$@")" 2>/dev/null || true
  elif command -v zenity >/dev/null 2>&1; then
    zenity --error --no-wrap --text="$(printf '%s\n' "$@")" 2>/dev/null || true
  fi
  exit 1
}

command -v python3 >/dev/null 2>&1 || die "Brim needs python3." \
  "Install it with: sudo dnf install python3"

missing=""
python3 -c 'import PySide6' 2>/dev/null || missing="$missing python3-pyside6"
python3 -c 'import libdnf5' 2>/dev/null || missing="$missing python3-libdnf5"

if [ -n "$missing" ]; then
  die "Brim needs these system packages:" \
      "  $missing" \
      "" \
      "Install them with:" \
      "  sudo dnf install$missing" \
      "" \
      "Brim talks to your system package manager, so libdnf5 has to be the" \
      "one your system uses. That is why it cannot be bundled here."
fi

exec python3 -c 'import sys; from brim.app import main; sys.exit(main())' "$@"
RUNEOF
chmod +x "$APPDIR/AppRun"

mkdir -p "$SRC/dist"
OUT="$SRC/dist/Brim-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" "$OUT"

chmod +x "$OUT"
echo
echo "Done:"
ls -la "$OUT"
