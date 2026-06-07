#!/usr/bin/env bash
# Veskald Execution Bridge — Linux installer.
#
# Places the AppImage into ~/.local/bin (or /usr/local/bin with --system),
# registers a .desktop entry, installs the icon under hicolor, and refreshes
# the desktop/icon caches so it shows up in your application menu immediately.
#
# Usage:
#   ./install.sh                  # per-user, no sudo
#   ./install.sh --system         # system-wide, needs sudo
#   ./install.sh --uninstall      # remove what install.sh created
#   ./install.sh --help

set -euo pipefail

APP_ID="veskald-execution-bridge"
APP_NAME="Veskald Execution Bridge"

# Detect bundle dir (the dir this script lives in).
HERE="$(cd "$(dirname "$0")" && pwd)"

MODE="user"
ACTION="install"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system)    MODE="system"; shift ;;
    --user)      MODE="user"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help)
      cat <<EOF
Veskald Execution Bridge installer

  ./install.sh                  install for current user (default)
  ./install.sh --system         install for all users (needs sudo)
  ./install.sh --uninstall      remove a previous install (honours --system too)

Files installed (per-user):
  ~/.local/bin/${APP_ID}
  ~/.local/share/applications/${APP_ID}.desktop
  ~/.local/share/icons/hicolor/256x256/apps/${APP_ID}.png

Files installed (--system):
  /usr/local/bin/${APP_ID}
  /usr/local/share/applications/${APP_ID}.desktop
  /usr/local/share/icons/hicolor/256x256/apps/${APP_ID}.png
EOF
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ "$MODE" == "system" ]]; then
  BIN_DIR="/usr/local/bin"
  APP_DIR="/usr/local/share/applications"
  ICON_DIR="/usr/local/share/icons/hicolor/256x256/apps"
  SUDO="sudo"
else
  BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
  APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
  SUDO=""
fi

BIN_PATH="$BIN_DIR/$APP_ID"
DESKTOP_PATH="$APP_DIR/$APP_ID.desktop"
ICON_PATH="$ICON_DIR/$APP_ID.png"

refresh_caches() {
  if command -v update-desktop-database >/dev/null 2>&1; then
    $SUDO update-desktop-database "$APP_DIR" 2>/dev/null || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    $SUDO gtk-update-icon-cache -t -q "$(dirname "$(dirname "$(dirname "$ICON_PATH")")")" 2>/dev/null || true
  fi
}

# ---------------- Uninstall -----------------------------------------------
if [[ "$ACTION" == "uninstall" ]]; then
  echo ">>> Removing $APP_NAME ($MODE install)"
  for f in "$BIN_PATH" "$DESKTOP_PATH" "$ICON_PATH"; do
    if [[ -e "$f" ]]; then
      echo "    rm $f"
      $SUDO rm -f "$f"
    fi
  done
  refresh_caches
  echo ">>> Done."
  echo "    Config (~/.config/veskald-execution-bridge) is kept. Delete it manually"
  echo "    if you want a clean wipe."
  exit 0
fi

# ---------------- Install -------------------------------------------------
APPIMAGE_SRC="$(ls -1 "$HERE"/*.AppImage 2>/dev/null | head -n1)"
if [[ -z "$APPIMAGE_SRC" ]]; then
  echo "Error: no *.AppImage found next to install.sh" >&2
  echo "       (expected the installer bundle, not a bare script)" >&2
  exit 2
fi
ICON_SRC="$HERE/$APP_ID.png"

echo ">>> Installing $APP_NAME ($MODE)"
echo "    AppImage: $APPIMAGE_SRC"
echo "    Binary  : $BIN_PATH"
echo "    Launcher: $DESKTOP_PATH"
echo "    Icon    : $ICON_PATH"
echo

$SUDO install -d "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
$SUDO install -m 0755 "$APPIMAGE_SRC" "$BIN_PATH"
if [[ -f "$ICON_SRC" ]]; then
  $SUDO install -m 0644 "$ICON_SRC" "$ICON_PATH"
else
  echo "    (warning: icon not found in bundle — menu entry will use default icon)"
fi

# Generate the .desktop pointing at the installed binary.
TMP_DESKTOP="$(mktemp)"
cat > "$TMP_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
GenericName=Automated Trading Client
Comment=Automated trading bot for Binance, Bybit, Kraken, OKX, Coinbase
Exec="$BIN_PATH" %U
TryExec=$BIN_PATH
Icon=$APP_ID
Categories=Office;Finance;Network;
Terminal=false
StartupNotify=true
StartupWMClass=$APP_NAME
Keywords=trading;bot;crypto;futures;
EOF
$SUDO install -m 0644 "$TMP_DESKTOP" "$DESKTOP_PATH"
rm -f "$TMP_DESKTOP"

refresh_caches

# If installing to ~/.local/bin and it is not on PATH, warn — but the .desktop
# uses an absolute path so the menu entry works regardless.
if [[ "$MODE" == "user" && ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo
  echo "  Note: $BIN_DIR is not on your \$PATH. The menu entry still works,"
  echo "        but to run from a terminal add this to ~/.bashrc / ~/.zshrc:"
  echo "          export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo
echo ">>> Done. Open your application menu and search for \"$APP_NAME\"."
echo "    Or run from a terminal:  $APP_ID"
echo
echo "    Uninstall later with:   $(basename "$0") --uninstall${MODE/user/}"
