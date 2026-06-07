#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "❌ .env file not found in $(pwd)"
    echo "   Create it from .env.example and fill in API credentials."
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "❌ 'docker compose' (v2) not found. Install Docker Compose plugin."
    exit 1
fi


TRADER_UID=1000
TRADER_GID=1000

mkdir -p logs
[ -f .unique_id ] || touch .unique_id


if [ "$(id -u)" -eq 0 ]; then
    chown -R "${TRADER_UID}:${TRADER_GID}" logs .unique_id
else
    if command -v sudo >/dev/null 2>&1; then
        sudo chown -R "${TRADER_UID}:${TRADER_GID}" logs .unique_id
    else
        echo "⚠️  Cannot chown logs/ and .unique_id without root or sudo."
        echo "   If the container fails with PermissionError, run:"
        echo "   sudo chown -R ${TRADER_UID}:${TRADER_GID} logs .unique_id"
    fi
fi

echo "⬇️  Pulling latest code..."
git pull --rebase


echo "🚀 Rebuilding and restarting container..."
docker compose up -d --build


sleep 3
if [ "$(docker compose ps --status running --quiet | wc -l)" -eq 0 ]; then
    echo "❌ Container failed to start. Last 30 log lines:"
    docker compose logs --tail=30
    exit 1
fi

echo ""
echo "✅ Deployment finished successfully!"
echo ""
echo "   Status: docker compose ps"
echo "   Logs:   docker compose logs -f"