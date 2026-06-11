#!/usr/bin/env bash
# Veskald Execution Bridge — server installer.
#
# One-command install on a fresh Linux server. Detects the distro, installs
# Docker if missing, prompts for credentials, generates docker-compose.yml
# next to a 0600 .env, starts the container from GitLab Container Registry.
# No clone needed.
#
# Run:
#   bash <(curl -fsSL https://gitlab.com/veskald/veskald-execution-bridge/-/raw/main/installer/server-install.sh)
#
# Subcommands (once installed):
#   bash server-install.sh install        # default — wizard + start
#   bash server-install.sh update         # pull latest image, restart
#   bash server-install.sh logs           # tail container logs
#   bash server-install.sh restart        # restart container
#   bash server-install.sh stop           # stop container
#   bash server-install.sh reconfigure    # rerun wizard, overwrite .env
#   bash server-install.sh status         # docker compose ps
#   bash server-install.sh uninstall      # remove container + image + dir

set -euo pipefail

REPO_GROUP="veskald"
REPO_NAME="veskald-execution-bridge"
REGISTRY="registry.gitlab.com"
# Image tag — defaults to :latest. Override with env VESKALD_IMAGE_TAG=<tag>
# to pin a specific build (e.g. an rc release, a sha- tag, or v0.0.1).
IMAGE="${REGISTRY}/${REPO_GROUP}/${REPO_NAME}:${VESKALD_IMAGE_TAG:-latest}"
DEFAULT_PREFIX="/opt/veskald-execution-bridge"
USER_PREFIX="${HOME}/veskald-execution-bridge"
CONTAINER_NAME="veskald-execution-bridge"
DEFAULT_HUB_URL="https://stream.veskald.com"

# ---- helpers --------------------------------------------------------------

c_red()    { printf '\033[31m%s\033[0m' "$*"; }
c_green()  { printf '\033[32m%s\033[0m' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m' "$*"; }
c_cyan()   { printf '\033[36m%s\033[0m' "$*"; }
c_bold()   { printf '\033[1m%s\033[0m' "$*"; }

say()  { printf '%s\n' "$*"; }
info() { printf '%s %s\n' "$(c_cyan '==>')" "$*"; }
warn() { printf '%s %s\n' "$(c_yellow 'WARN')" "$*" >&2; }
die()  { printf '%s %s\n' "$(c_red 'ERROR')" "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

is_root() {
  [[ "$(id -u)" -eq 0 ]]
}

sudo_cmd() {
  if is_root; then "$@"
  elif need_cmd sudo; then sudo "$@"
  else die "need root or sudo to run: $*"
  fi
}

# ---- distro detection -----------------------------------------------------

detect_os() {
  if [[ ! -r /etc/os-release ]]; then
    die "Cannot read /etc/os-release — unsupported OS."
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}${ID_LIKE:-}" in
    *debian*|*ubuntu*)         echo "debian" ;;
    *rhel*|*fedora*|*centos*|*rocky*|*almalinux*) echo "rhel" ;;
    *) die "Unsupported distro: ${ID:-unknown}. Install Docker manually then re-run." ;;
  esac
}

# ---- Docker -----------------------------------------------------------------

install_docker() {
  if need_cmd docker; then
    info "Docker already installed: $(docker --version)"
    return 0
  fi
  info "Installing Docker via official get.docker.com script"
  if ! need_cmd curl; then
    case "$1" in
      debian) sudo_cmd apt-get update && sudo_cmd apt-get install -y curl ;;
      rhel)   sudo_cmd dnf install -y curl 2>/dev/null || sudo_cmd yum install -y curl ;;
    esac
  fi
  curl -fsSL https://get.docker.com | sudo_cmd sh
  sudo_cmd systemctl enable --now docker || warn "Could not enable docker via systemd. Start it manually."

  if ! is_root; then
    info "Adding $USER to the docker group (takes effect on next login)"
    sudo_cmd usermod -aG docker "$USER" || true
  fi
}

require_compose() {
  if docker compose version >/dev/null 2>&1; then return 0; fi
  die "'docker compose' (v2 plugin) not found. Re-run install or update Docker."
}

# ---- prefix / paths -------------------------------------------------------

resolve_prefix() {
  if [[ -n "${PREFIX:-}" ]]; then echo "$PREFIX"; return; fi
  if is_root; then echo "$DEFAULT_PREFIX"; else echo "$USER_PREFIX"; fi
}

ensure_prefix() {
  local prefix="$1"
  if [[ "$prefix" == /opt/* ]] || [[ "$prefix" == /usr/* ]] || [[ "$prefix" == /var/* ]]; then
    sudo_cmd mkdir -p "$prefix/logs"
    sudo_cmd chown -R "$(id -u):$(id -g)" "$prefix"
  else
    mkdir -p "$prefix/logs"
  fi
}

# ---- wizard ---------------------------------------------------------------

ask() {
  local label="$1" default="${2:-}" var
  if [[ -n "$default" ]]; then
    read -r -p "  $label [$default]: " var || true
  else
    read -r -p "  $label: " var || true
  fi
  echo "${var:-$default}"
}

ask_secret() {
  local label="$1" var
  read -r -s -p "  $label: " var || true
  echo
  echo "$var"
}

ask_yes_no() {
  local label="$1" default="${2:-N}" answer
  local hint="[y/N]"
  [[ "$default" == "Y" ]] && hint="[Y/n]"
  read -r -p "  $label $hint: " answer || true
  answer="${answer:-$default}"
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

write_env() {
  local prefix="$1"
  local env_path="$prefix/.env"

  echo
  c_bold "  ───── Veskald hub ─────"; echo
  HUB_URL="$(ask 'Hub URL' "$DEFAULT_HUB_URL")"
  while :; do
    MACHINE="$(ask 'Machine token (from app.veskald.com/notifications)' "")"
    [[ -n "$MACHINE" ]] && break
    warn "Machine token is required."
  done

  declare -A KEYS
  declare -a SECTIONS=(
    "Binance:BINANCE:BINANCE_API_KEY:BINANCE_API_SECRET:"
    "Bybit:BYBIT:BYBIT_API_KEY:BYBIT_API_SECRET:BYBIT_TESTNET=false"
    "Kraken Futures:KRAKEN:KRAKEN_API_KEY:KRAKEN_API_SECRET:KRAKEN_SANDBOX=false"
    "OKX:OKX:OKX_API_KEY:OKX_API_SECRET:OKX_API_PASSPHRASE,OKX_DEMO=false,OKX_DEFAULT_ISOLATED=false"
    "Coinbase:COINBASE:COINBASE_API_KEY:COINBASE_API_SECRET:COINBASE_INTX_PORTFOLIO_UUID"
  )

  for section in "${SECTIONS[@]}"; do
    IFS=":" read -r label _prefix key_var secret_var extras <<< "$section"
    echo
    c_bold "  ───── $label ─────"; echo
    if ! ask_yes_no "Configure $label?" "N"; then
      continue
    fi
    KEYS[$key_var]="$(ask "$label API Key" "")"
    KEYS[$secret_var]="$(ask_secret "$label API Secret")"
    # extras: comma-separated "VAR" or "VAR=default"
    if [[ -n "$extras" ]]; then
      IFS=',' read -ra fields <<< "$extras"
      for field in "${fields[@]}"; do
        local fkey fdefault
        if [[ "$field" == *"="* ]]; then
          fkey="${field%%=*}"
          fdefault="${field#*=}"
        else
          fkey="$field"
          fdefault=""
        fi
        # OKX passphrase is sensitive
        if [[ "$fkey" == *PASSPHRASE* ]]; then
          KEYS[$fkey]="$(ask_secret "$fkey")"
        else
          KEYS[$fkey]="$(ask "$fkey" "$fdefault")"
        fi
      done
    fi
  done

  # Write atomically.
  local tmp
  tmp="$(mktemp)"
  {
    echo "# Veskald Execution Bridge — generated by server-install.sh"
    echo "# $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
    echo
    echo "HUB_URL=$HUB_URL"
    echo "MACHINE=$MACHINE"
    for var in "${!KEYS[@]}"; do
      val="${KEYS[$var]}"
      if [[ -n "$val" ]]; then
        echo "$var=$val"
      fi
    done
  } > "$tmp"
  install -m 0600 "$tmp" "$env_path"
  rm -f "$tmp"
  info "Wrote $env_path (mode 0600)"
}

# ---- docker-compose generation --------------------------------------------

write_compose() {
  local prefix="$1"
  local compose_path="$prefix/docker-compose.yml"
  cat > "$compose_path" <<EOF
# Veskald Execution Bridge — generated by server-install.sh
services:
  ${CONTAINER_NAME}:
    image: ${IMAGE}
    container_name: ${CONTAINER_NAME}
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
EOF
  info "Wrote $compose_path"
}

# ---- compose helpers ------------------------------------------------------

compose_in() {
  local prefix="$1"; shift
  ( cd "$prefix" && docker compose "$@" )
}

# ---- actions --------------------------------------------------------------

action_install() {
  local prefix; prefix="$(resolve_prefix)"
  local os; os="$(detect_os)"
  info "Detected: $(c_bold "$os")"
  info "Install prefix: $(c_bold "$prefix")"
  echo

  install_docker "$os"
  require_compose

  ensure_prefix "$prefix"

  if [[ -f "$prefix/.env" ]]; then
    if ! ask_yes_no "$prefix/.env exists. Overwrite?" "N"; then
      info "Keeping existing .env"
    else
      write_env "$prefix"
    fi
  else
    write_env "$prefix"
  fi

  write_compose "$prefix"

  info "Pulling image $IMAGE"
  compose_in "$prefix" pull

  info "Starting container"
  compose_in "$prefix" up -d

  sleep 3
  if [[ -z "$(compose_in "$prefix" ps --status running --quiet)" ]]; then
    warn "Container did not enter the running state. Last 30 log lines:"
    compose_in "$prefix" logs --tail=30
    exit 1
  fi

  echo
  c_green "  ✓ Veskald Execution Bridge is running."; echo
  echo
  say "  Status:        bash $0 status"
  say "  Logs:          bash $0 logs"
  say "  Update image:  bash $0 update"
  say "  Reconfigure:   bash $0 reconfigure"
  say "  Stop:          bash $0 stop"
  say "  Uninstall:     bash $0 uninstall"
  echo
  say "  Config: $prefix/.env"
  say "  Logs:   $prefix/logs/"
}

action_update() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix. Run install first."
  info "Pulling latest image"
  compose_in "$prefix" pull
  info "Restarting container"
  compose_in "$prefix" up -d
  c_green "  ✓ Updated."; echo
}

action_logs() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix."
  compose_in "$prefix" logs -f --tail=100
}

action_status() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix."
  compose_in "$prefix" ps
}

action_restart() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix."
  compose_in "$prefix" restart
  c_green "  ✓ Restarted."; echo
}

action_stop() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix."
  compose_in "$prefix" down
  c_green "  ✓ Stopped."; echo
}

action_reconfigure() {
  local prefix; prefix="$(resolve_prefix)"
  [[ -f "$prefix/docker-compose.yml" ]] || die "Not installed at $prefix. Run install first."
  write_env "$prefix"
  info "Restarting container with new config"
  compose_in "$prefix" up -d --force-recreate
  c_green "  ✓ Reconfigured and restarted."; echo
}

action_uninstall() {
  local prefix; prefix="$(resolve_prefix)"
  echo
  warn "This will:"
  say "  - Stop and remove the $CONTAINER_NAME container"
  say "  - Remove the $IMAGE image from this host"
  say "  - Delete $prefix (including .env and logs)"
  echo
  if ! ask_yes_no "Are you sure?" "N"; then
    info "Aborted."
    return 0
  fi
  if [[ -f "$prefix/docker-compose.yml" ]]; then
    compose_in "$prefix" down -v || true
  fi
  docker image rm -f "$IMAGE" 2>/dev/null || true
  if [[ "$prefix" == /opt/* || "$prefix" == /usr/* || "$prefix" == /var/* ]]; then
    sudo_cmd rm -rf "$prefix"
  else
    rm -rf "$prefix"
  fi
  c_green "  ✓ Uninstalled."; echo
}

usage() {
  cat <<EOF
Veskald Execution Bridge — server installer

Usage:
  bash $0 [SUBCOMMAND] [--prefix=/path]

Subcommands:
  install        (default) Install Docker, wizard, start container
  update         Pull the latest image and restart
  status         docker compose ps
  logs           tail -f the container logs
  restart        Restart the container
  stop           Stop the container
  reconfigure    Rerun the wizard, overwrite .env, recreate container
  uninstall      Remove the container, image and install directory

Options:
  --prefix=PATH  Install directory (default: /opt/veskald-execution-bridge for root,
                 \$HOME/veskald-execution-bridge for non-root)

Examples:
  bash <(curl -fsSL https://gitlab.com/${REPO_GROUP}/${REPO_NAME}/-/raw/main/installer/server-install.sh)
  bash server-install.sh update
  bash server-install.sh --prefix=\$HOME/trader install
EOF
}

# ---- arg parsing ----------------------------------------------------------

ACTION="install"
for arg in "$@"; do
  case "$arg" in
    install|update|logs|status|restart|stop|reconfigure|uninstall) ACTION="$arg" ;;
    --prefix=*)        PREFIX="${arg#--prefix=}"; export PREFIX ;;
    -h|--help)         usage; exit 0 ;;
    *) warn "Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

case "$ACTION" in
  install)     action_install ;;
  update)      action_update ;;
  logs)        action_logs ;;
  status)      action_status ;;
  restart)     action_restart ;;
  stop)        action_stop ;;
  reconfigure) action_reconfigure ;;
  uninstall)   action_uninstall ;;
esac
