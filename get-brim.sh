#!/usr/bin/env bash
#
# Brim installer.
#
#   curl -fsSL https://raw.githubusercontent.com/gabrielmf1998/brim/main/get-brim.sh | bash
#
# Prefer to read before you run? That is the right instinct:
#
#   curl -fsSLO https://raw.githubusercontent.com/gabrielmf1998/brim/main/get-brim.sh
#   less get-brim.sh && bash get-brim.sh
#
# Options:
#   --method rpm|appimage    pick the install method instead of auto
#   --version 1.2.3          install a specific release
#   --uninstall              remove Brim
#   --help
set -euo pipefail

GITHUB_REPO="gabrielmf1998/brim"
RAW_BASE="https://raw.githubusercontent.com/gabrielmf1998/brim/main"
GITLAB_REPO="gabriel17166/brim"
GITLAB_ID="$(printf '%s' "$GITLAB_REPO" | sed 's|/|%2F|')"

METHOD="auto"
WANT_VERSION=""
DO_UNINSTALL=0

APPS_DIR="$HOME/Applications"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

bold=""; dim=""; red=""; green=""; yellow=""; reset=""
if [ -t 1 ]; then
  bold="$(printf '\033[1m')"; dim="$(printf '\033[2m')"
  red="$(printf '\033[31m')"; green="$(printf '\033[32m')"
  yellow="$(printf '\033[33m')"; reset="$(printf '\033[0m')"
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$bold" "$reset" "$*"; }
warn() { printf '%s warning %s %s\n' "$yellow" "$reset" "$*" >&2; }
die()  { printf '%s error %s %s\n' "$red" "$reset" "$*" >&2; exit 1; }
ok()   { printf '%s  ok %s %s\n' "$green" "$reset" "$*"; }

usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --method)    METHOD="${2:-}"; shift 2 ;;
    --version)   WANT_VERSION="${2:-}"; shift 2 ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    -h|--help)   usage ;;
    *) die "Unknown option: $1. Try --help." ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1; }

# Escalate the way that actually works here. Piping this script into bash
# leaves no terminal for sudo to prompt on, so fall back to pkexec, which
# asks graphically. Trying sudo blind would just fail with a confusing error.
can_escalate() {
  [ "$(id -u)" = "0" ] && return 0
  { [ -t 0 ] || [ -t 1 ]; } && need sudo && return 0
  need pkexec && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; } && return 0
  need sudo && return 0
  return 1
}

as_root() {
  if [ "$(id -u)" = "0" ]; then
    "$@"
  elif { [ -t 0 ] || [ -t 1 ]; } && need sudo; then
    say "You will be asked for your password."
    sudo "$@"
  elif need pkexec && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
    say "An authentication window will open."
    pkexec "$@"
  elif need sudo; then
    say "You will be asked for your password."
    sudo "$@"
  else
    die "Need root to install the RPM, but neither sudo nor pkexec is usable.
Try the AppImage instead:
  curl -fsSL $RAW_BASE/get-brim.sh | bash -s -- --method appimage"
  fi
}

# ---------------------------------------------------------------- uninstall

if [ "$DO_UNINSTALL" -eq 1 ]; then
  step "Removing Brim"
  if rpm -q brim >/dev/null 2>&1; then
    as_root dnf remove -y brim
  fi
  rm -f "$APPS_DIR"/Brim-*.AppImage
  rm -f "$BIN_DIR/brim" "$DESKTOP_DIR/brim.desktop" "$ICON_DIR/brim.svg"
  rm -f "$HOME/.config/autostart/brim.desktop"
  ok "Brim removed. Settings in ~/.config/brim were kept."
  exit 0
fi

# ------------------------------------------------------------ sanity checks

step "Checking this system"

[ "$(uname -s)" = "Linux" ] || die "Brim is Linux only."

case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) warn "Untested architecture $(uname -m). The RPM is noarch so it may still work." ;;
esac

if ! need dnf && ! need dnf5; then
  die "No dnf found.

Brim drives DNF5 directly through libdnf5. It is built for Fedora and other
DNF5 based systems (Fedora, Nobara, Ultramarine, RHEL 10 and friends).
It will not work on Debian, Ubuntu, Arch, openSUSE or anything non RPM."
fi

DISTRO="unknown"
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO="${PRETTY_NAME:-${NAME:-unknown}}"
fi
ok "$DISTRO"

need curl || die "curl is required. Install it with: sudo dnf install curl"

# --------------------------------------------------------- find the release

step "Finding the latest release"

fetch() { curl -fsSL --retry 2 --connect-timeout 15 "$@" 2>/dev/null; }

json_field() { # json_field <key>  reads stdin, no jq needed
  python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
if isinstance(d,list): d = d[0] if d else {}
v = d.get('$1','')
print(v if isinstance(v,str) else '')
" 2>/dev/null || true
}

asset_url() { # asset_url <suffix>  reads stdin
  python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(1)
out=''
if isinstance(d,dict) and 'assets' in d and isinstance(d['assets'],list):
    for a in d['assets']:
        if a.get('name','').lower().endswith('$1'):
            out=a.get('browser_download_url',''); break
elif isinstance(d,list) and d:
    for l in (d[0].get('assets',{}) or {}).get('links',[]) or []:
        if l.get('name','').lower().endswith('$1'):
            out=l.get('url',''); break
print(out)
" 2>/dev/null || true
}

RELEASE_JSON=""
HOST=""
if [ -n "$WANT_VERSION" ]; then
  RELEASE_JSON="$(fetch "https://api.github.com/repos/$GITHUB_REPO/releases/tags/$WANT_VERSION" || true)"
else
  RELEASE_JSON="$(fetch "https://api.github.com/repos/$GITHUB_REPO/releases/latest" || true)"
fi
if [ -n "$RELEASE_JSON" ] && printf '%s' "$RELEASE_JSON" | grep -q '"tag_name"'; then
  HOST="GitHub"
else
  RELEASE_JSON="$(fetch "https://gitlab.com/api/v4/projects/$GITLAB_ID/releases" || true)"
  if [ -n "$RELEASE_JSON" ] && printf '%s' "$RELEASE_JSON" | grep -q '"tag_name"'; then
    HOST="GitLab"
  fi
fi

[ -n "$HOST" ] || die "Could not reach GitHub or GitLab, or no release is published yet."

VERSION="$(printf '%s' "$RELEASE_JSON" | json_field tag_name)"
RPM_URL="$(printf '%s' "$RELEASE_JSON" | asset_url .rpm)"
APPIMAGE_URL="$(printf '%s' "$RELEASE_JSON" | asset_url .appimage)"
ok "Brim ${VERSION:-unknown} on $HOST"

# ------------------------------------------------------------ pick a method

if [ "$METHOD" = "auto" ]; then
  if [ -n "$RPM_URL" ] && can_escalate; then
    METHOD="rpm"
  elif [ -n "$APPIMAGE_URL" ]; then
    METHOD="appimage"
  elif [ -n "$RPM_URL" ]; then
    METHOD="rpm"
  else
    die "That release has neither an RPM nor an AppImage attached."
  fi
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------------ install

case "$METHOD" in
  rpm)
    [ -n "$RPM_URL" ] || die "That release has no RPM attached. Try --method appimage."
    step "Installing the RPM"
    say "${dim}$RPM_URL${reset}"
    curl -fSL --progress-bar -o "$TMP/brim.rpm" "$RPM_URL"
    # pkexec drops the caller's environment, so hand dnf an absolute path.
    as_root dnf install -y "$TMP/brim.rpm"
    ok "Installed. Run it with: brim"
    ;;

  appimage)
    [ -n "$APPIMAGE_URL" ] || die "That release has no AppImage attached. Try --method rpm."
    step "Checking what the AppImage needs"
    MISSING=""
    python3 -c 'import PySide6' 2>/dev/null || MISSING="$MISSING python3-pyside6"
    python3 -c 'import libdnf5' 2>/dev/null || MISSING="$MISSING python3-libdnf5"
    if [ -n "$MISSING" ]; then
      warn "Missing:$MISSING"
      say ""
      say "The AppImage ships Brim itself but uses your system's libdnf5, because"
      say "it has to be the same one your package manager uses."
      say ""
      if can_escalate; then
        say "Installing them now."
        # shellcheck disable=SC2086
        as_root dnf install -y $MISSING || die "Could not install:$MISSING"
      else
        die "Install them first: sudo dnf install$MISSING"
      fi
    fi
    ok "Dependencies present"

    step "Installing the AppImage"
    say "${dim}$APPIMAGE_URL${reset}"
    mkdir -p "$APPS_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
    rm -f "$APPS_DIR"/Brim-*.AppImage
    TARGET="$APPS_DIR/Brim-${VERSION}-x86_64.AppImage"
    curl -fSL --progress-bar -o "$TARGET" "$APPIMAGE_URL"
    chmod +x "$TARGET"
    ln -sf "$TARGET" "$BIN_DIR/brim"

    curl -fsSL -o "$ICON_DIR/brim.svg" \
      "$RAW_BASE/data/icons/brim.svg" \
      2>/dev/null || true

    cat > "$DESKTOP_DIR/brim.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Brim
GenericName=Package Manager
Comment=Search, install and update from every Fedora source at once
Exec=$TARGET %U
Icon=brim
Terminal=false
Categories=System;Settings;PackageManager;Qt;
Keywords=package;dnf;rpm;flatpak;copr;appimage;install;update;software;
StartupNotify=true
StartupWMClass=brim
DESKTOP

    need update-desktop-database && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    ok "Installed to $TARGET"

    case ":$PATH:" in
      *":$BIN_DIR:"*) ok "Run it with: brim" ;;
      *) warn "$BIN_DIR is not on your PATH."
         say "Run it with: $TARGET"
         say "Or add to your shell: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
    ;;

  *) die "Unknown method: $METHOD. Use rpm or appimage." ;;
esac

say ""
say "${bold}Brim ${VERSION} is ready.${reset}"
say "Press F1 inside the app for the guide, including what COPR costs you."
