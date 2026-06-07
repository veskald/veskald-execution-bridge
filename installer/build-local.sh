#!/usr/bin/env bash
# Build the Veskald Execution Bridge desktop app on the current machine.
#
# Linux  →  AppImage + tar.gz wrapper + installer bundle
# macOS  →  .app bundle inside a .tar.gz
# Windows uses installer/build-local.ps1 instead.
#
# Usage:
#   installer/build-local.sh                 # version from `git describe`, native arch
#   installer/build-local.sh v1.2.3          # pin a version
#   installer/build-local.sh --universal     # macOS: one .app for arm64+x86_64
#                                            # (requires universal2 Python from python.org)
#   installer/build-local.sh --arch arm64    # force arch on macOS
#   installer/build-local.sh --deploy        # also push artifacts to S3 after build
#
# Env (used with --deploy):
#   S3_BUCKET=...                            # required — destination bucket
#   S3_PREFIX=execution-bridge/releases      # optional — key prefix
#   S3_REGION=us-east-1                      # optional
#   AWS_PROFILE / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY — standard AWS auth
#   AWS_DOWNLOADS_BASE_URL=https://downloads.veskald.com   # optional — used in the
#                                            #   "public URLs" printout at the end
#
# Tip: env VESKALD_TARGET_ARCH=universal2 also works (same effect as --universal).

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

ARCH_OVERRIDE=""
DEPLOY=0
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --universal) ARCH_OVERRIDE="universal2"; shift ;;
    --arch)      ARCH_OVERRIDE="$2"; shift 2 ;;
    --deploy)    DEPLOY=1; shift ;;
    *)           ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || echo dev)}"

UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"
case "$UNAME_S" in
  Linux)  OS_TAG="linux" ;;
  Darwin) OS_TAG="macos" ;;
  *) echo "unsupported OS: $UNAME_S" >&2; exit 1 ;;
esac
case "$UNAME_M" in
  x86_64|amd64) ARCH_TAG="x86_64" ;;
  arm64|aarch64) ARCH_TAG="arm64" ;;
  *) echo "unsupported arch: $UNAME_M" >&2; exit 1 ;;
esac

# Honour --universal / --arch / VESKALD_TARGET_ARCH (env wins last).
EFFECTIVE_ARCH="${VESKALD_TARGET_ARCH:-$ARCH_OVERRIDE}"
if [[ -n "$EFFECTIVE_ARCH" ]]; then
  if [[ "$OS_TAG" != "macos" ]]; then
    echo "    (arch override ignored — only meaningful on macOS)"
    EFFECTIVE_ARCH=""
  else
    export VESKALD_TARGET_ARCH="$EFFECTIVE_ARCH"
    case "$EFFECTIVE_ARCH" in
      universal2) ARCH_TAG="universal2" ;;
      arm64)      ARCH_TAG="arm64" ;;
      x86_64)     ARCH_TAG="x86_64" ;;
      *) echo "bad --arch value: $EFFECTIVE_ARCH (use universal2, arm64, or x86_64)" >&2; exit 1 ;;
    esac
  fi
fi

TARGET="${OS_TAG}-${ARCH_TAG}"

echo ">>> Building Veskald Execution Bridge $VERSION for $TARGET"

# Local venv so we don't pollute the system Python.
PY="${PYTHON:-python3}"
VENV="$ROOT/.build-venv"
if [[ ! -d "$VENV" ]]; then
  "$PY" -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"

pip install --upgrade pip wheel >/dev/null
pip install -r requirements.txt
pip install -r requirements-gui.txt
pip install --no-deps "coinbase-advanced-py>=1.8.2"
pip install "pyinstaller==6.11.1"
# Pillow → PyInstaller auto-converts logo.png to .icns (macOS) / .ico (Windows)
pip install "Pillow>=10.0.0"

# ---- Icon ------------------------------------------------------------------
# Drop a PNG at installer/assets/logo.png (square 512×512 ideal). The build
# copies it as-is into the AppImage and installer bundle. If missing, we fall
# back to a 1×1 placeholder so the build doesn't break.
ICON_PNG="installer/assets/logo.png"
if [[ ! -f "$ICON_PNG" ]]; then
  echo "    (warning: $ICON_PNG missing — icon will be a 1×1 placeholder)"
fi

# ---- PyInstaller -----------------------------------------------------------
rm -rf build dist
pyinstaller --clean --noconfirm installer/veskald-execution-bridge.spec

# ---- Package ---------------------------------------------------------------
ARCHIVE=""

if [[ "$OS_TAG" == "linux" ]]; then
  # ---- AppImage ----
  APPDIR="dist/AppDir"
  rm -rf "$APPDIR"
  mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
           "$APPDIR/usr/share/icons/hicolor/256x256/apps"

  cp "dist/veskald-execution-bridge" "$APPDIR/usr/bin/"
  cp "installer/assets/veskald-execution-bridge.desktop" \
     "$APPDIR/veskald-execution-bridge.desktop"
  cp "installer/assets/veskald-execution-bridge.desktop" \
     "$APPDIR/usr/share/applications/"

  if [[ -f "$ICON_PNG" ]]; then
    cp "$ICON_PNG" "$APPDIR/veskald-execution-bridge.png"
    cp "$ICON_PNG" "$APPDIR/usr/share/icons/hicolor/256x256/apps/veskald-execution-bridge.png"
  else
    # appimagetool refuses without an icon — drop a 1x1 placeholder.
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x05\x00\x00\xc4\x00\x01\x96\xb9_t\x00\x00\x00\x00IEND\xaeB`\x82' \
      > "$APPDIR/veskald-execution-bridge.png"
  fi

  cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/veskald-execution-bridge" "$@"
APPRUN
  chmod +x "$APPDIR/AppRun"

  APPIMAGETOOL="${APPIMAGETOOL:-/tmp/appimagetool-x86_64.AppImage}"
  if [[ ! -x "$APPIMAGETOOL" ]]; then
    echo ">>> Fetching appimagetool"
    curl -fL -o "$APPIMAGETOOL" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$APPIMAGETOOL"
  fi

  APPIMAGE="dist/Veskald-Execution-Bridge-${VERSION}-${ARCH_TAG}.AppImage"
  ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run \
    --no-appstream "$APPDIR" "$APPIMAGE"
  chmod +x "$APPIMAGE"

  # tar.gz wrapper: preserves the executable bit so users don't need
  # `chmod +x` after extracting — `tar xf` → double-click → run.
  APPIMAGE_TAR="dist/Veskald-Execution-Bridge-${VERSION}-linux-${ARCH_TAG}.tar.gz"
  tar -czf "$APPIMAGE_TAR" -C dist "$(basename "$APPIMAGE")"

  # Also produce an "installer bundle" tar.gz that contains the AppImage,
  # the icon, the install.sh script and a README. Users who want menu
  # integration extract it and run ./install.sh — users who don't can
  # ignore this and use the bare .AppImage above.
  BUNDLE_DIR="dist/installer-bundle/veskald-execution-bridge-${VERSION}"
  rm -rf "$(dirname "$BUNDLE_DIR")"
  mkdir -p "$BUNDLE_DIR"
  cp "$APPIMAGE" "$BUNDLE_DIR/"
  cp installer/assets/linux-install.sh "$BUNDLE_DIR/install.sh"
  chmod +x "$BUNDLE_DIR/install.sh"
  if [[ -f "$ICON_PNG" ]]; then
    cp "$ICON_PNG" "$BUNDLE_DIR/veskald-execution-bridge.png"
  fi
  cat > "$BUNDLE_DIR/README.txt" <<'README'
Veskald Execution Bridge — Linux installer bundle
============================================

This archive contains the AppImage plus an install script that registers
the app in your application menu (KDE / GNOME / XFCE / etc.).

Quick start:
  ./install.sh                  install for the current user (no sudo)
  ./install.sh --system         install system-wide (sudo)
  ./install.sh --uninstall      remove what was installed

After install, search for "Veskald Execution Bridge" in your application menu,
or run `veskald-execution-bridge` from any terminal.

If you don't want menu integration, just `chmod +x` the .AppImage and
run it directly.
README

  BUNDLE_TAR="dist/Veskald-Execution-Bridge-${VERSION}-linux-${ARCH_TAG}-installer.tar.gz"
  tar -czf "$BUNDLE_TAR" -C "$(dirname "$BUNDLE_DIR")" "$(basename "$BUNDLE_DIR")"

  # Primary output stays the AppImage; the installer bundle is the second
  # artefact and gets its own sha256 below.
  ARCHIVE="$APPIMAGE"

elif [[ "$OS_TAG" == "macos" ]]; then
  # Ad-hoc codesign so Gatekeeper can at least launch the bundle.
  if [[ -d "dist/Veskald Execution Bridge.app" ]]; then
    codesign --force --deep --sign - "dist/Veskald Execution Bridge.app"
  fi

  STAGE="dist/stage"
  rm -rf "$STAGE"
  mkdir -p "$STAGE"
  if [[ -d "dist/Veskald Execution Bridge.app" ]]; then
    cp -R "dist/Veskald Execution Bridge.app" "$STAGE/"
  else
    cp "dist/veskald-execution-bridge" "$STAGE/"
  fi
  cp .env.example "$STAGE/"
  cp installer/INSTALL.md "$STAGE/"

  ARCHIVE="dist/Veskald-Execution-Bridge-${VERSION}-${TARGET}.tar.gz"
  tar -czf "$ARCHIVE" -C "$STAGE" .
fi

_sha256_into() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" > "${file}.sha256"
  else
    sha256sum "$file" > "${file}.sha256"
  fi
}

_sha256_into "$ARCHIVE"
if [[ "$OS_TAG" == "linux" ]]; then
  [[ -n "${APPIMAGE_TAR:-}" && -f "$APPIMAGE_TAR" ]] && _sha256_into "$APPIMAGE_TAR"
  [[ -n "${BUNDLE_TAR:-}"   && -f "$BUNDLE_TAR"   ]] && _sha256_into "$BUNDLE_TAR"
fi

echo
echo ">>> Done."
echo "    Primary:  $ARCHIVE"
echo "    SHA-256:  $(cat "${ARCHIVE}.sha256")"
if [[ "$OS_TAG" == "linux" ]]; then
  if [[ -n "${APPIMAGE_TAR:-}" && -f "${APPIMAGE_TAR}" ]]; then
    echo
    echo "    Easy download (already executable after tar xf):"
    echo "      tar xzf \"$APPIMAGE_TAR\" && ./$(basename "$ARCHIVE")"
    echo "      SHA-256:  $(cat "${APPIMAGE_TAR}.sha256")"
  fi
  echo
  echo "    Raw AppImage (needs chmod +x):"
  echo "      chmod +x \"$ARCHIVE\" && \"$ARCHIVE\""
  if [[ -n "${BUNDLE_TAR:-}" && -f "${BUNDLE_TAR}" ]]; then
    echo
    echo "    Installer bundle (adds app to system menu):"
    echo "      tar xzf \"$BUNDLE_TAR\""
    echo "      cd veskald-execution-bridge-${VERSION} && ./install.sh"
    echo "      SHA-256:  $(cat "${BUNDLE_TAR}.sha256")"
  fi
fi

# ─── Deploy to S3 ─────────────────────────────────────────────────────────
#
# Required env vars when --deploy is passed:
#   S3_BUCKET           — bucket name (e.g. downloads.veskald.com)
# Optional:
#   S3_PREFIX           — key prefix (default: execution-bridge/releases)
#   S3_REGION           — region (default: us-east-1)
#   AWS_PROFILE         — pick a non-default ~/.aws/credentials profile
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY — inline creds
#
# Uploads happen to two locations:
#   s3://$S3_BUCKET/$S3_PREFIX/$VERSION/<file>     immutable, versioned
#   s3://$S3_BUCKET/$S3_PREFIX/latest/<unversioned>  short-cached, overwritten

_s3_deploy() {
  if ! command -v aws >/dev/null 2>&1; then
    echo "ERROR: --deploy requires the aws CLI." >&2
    echo "  Install:" >&2
    echo "    Linux:  sudo apt install awscli  (or pip install awscli)" >&2
    echo "    macOS:  brew install awscli" >&2
    exit 1
  fi
  : "${S3_BUCKET:?ERROR: S3_BUCKET env var is required for --deploy}"
  local prefix="${S3_PREFIX:-execution-bridge/releases}"
  local region="${S3_REGION:-us-east-1}"
  echo
  echo ">>> Deploying to s3://$S3_BUCKET/$prefix/"

  _upload_one() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    local name; name="$(basename "$file")"
    local stable="${name//${VERSION}-/}"

    echo "    upload  s3://$S3_BUCKET/$prefix/$VERSION/$name"
    aws s3 cp "$file" "s3://$S3_BUCKET/$prefix/$VERSION/$name" \
      --region "$region" \
      --no-progress \
      --cache-control "public, max-age=31536000, immutable"

    if [[ "$name" != "$stable" ]]; then
      echo "    mirror  s3://$S3_BUCKET/$prefix/latest/$stable"
      aws s3 cp "$file" "s3://$S3_BUCKET/$prefix/latest/$stable" \
        --region "$region" \
        --no-progress \
        --cache-control "public, max-age=300"
    fi
  }

  _upload_one "$ARCHIVE"
  _upload_one "${ARCHIVE}.sha256"
  if [[ "$OS_TAG" == "linux" ]]; then
    _upload_one "${APPIMAGE_TAR:-}"
    _upload_one "${APPIMAGE_TAR:-}.sha256"
    _upload_one "${BUNDLE_TAR:-}"
    _upload_one "${BUNDLE_TAR:-}.sha256"
  fi

  echo
  echo "    Done. Public URLs:"
  local base="${AWS_DOWNLOADS_BASE_URL:-https://$S3_BUCKET.s3.$region.amazonaws.com}"
  echo "      $base/$prefix/$VERSION/"
  echo "      $base/$prefix/latest/   (rolling)"
}

if [[ "$DEPLOY" == "1" ]]; then
  _s3_deploy
fi
