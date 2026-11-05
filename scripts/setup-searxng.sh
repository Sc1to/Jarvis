#!/usr/bin/env bash
# setup-searxng.sh — run SearXNG (a metasearch engine) on this machine for Bookforge's research.
# Usage: sudo bash scripts/setup-searxng.sh
# Safe to run again: it keeps an existing settings.yml (and its secret key) and replaces the container.
# SearXNG listens on 127.0.0.1:8060 only; nothing outside this machine can reach it.

set -euo pipefail

PORT=8060
NAME=searxng
DATA=/opt/platform/data/searxng
IMAGE=docker.io/searxng/searxng:latest
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v docker &>/dev/null; then
    echo "[FAIL] docker is not installed (scripts/setup.sh installs it: sudo apt-get install -y docker.io)"
    exit 1
fi

mkdir -p "$DATA"
if [ ! -f "$DATA/settings.yml" ]; then
    SECRET="$(openssl rand -hex 32)"
    sed "s/__SECRET_KEY__/${SECRET}/" "$REPO/docker/searxng/settings.yml" > "$DATA/settings.yml"
    chmod 600 "$DATA/settings.yml"
    echo "[OK]   wrote $DATA/settings.yml (new secret key)"
else
    echo "[OK]   kept the existing $DATA/settings.yml"
fi
# the container's user must be able to write its cache next to the settings
chown -R 977:977 "$DATA" 2>/dev/null || true

docker rm -f "$NAME" &>/dev/null || true
docker run -d \
    --name "$NAME" \
    --restart always \
    -p "127.0.0.1:${PORT}:8080" \
    -v "$DATA:/etc/searxng" \
    -e "SEARXNG_BASE_URL=http://127.0.0.1:${PORT}/" \
    "$IMAGE" >/dev/null
echo "[OK]   started container '$NAME' on 127.0.0.1:${PORT}"

echo "       waiting for it to answer..."
for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${PORT}/search?q=history&format=json" -o /dev/null; then
        echo "[PASS] SearXNG answers JSON on http://127.0.0.1:${PORT}"
        echo "       Next: python -m bookforge doctor    (the 'searxng' line shows which engines answer)"
        exit 0
    fi
    sleep 2
done
echo "[WARN] it did not answer JSON within 60 s. Check: docker logs $NAME"
echo "       (HTTP 403 means json is missing under search.formats in $DATA/settings.yml)"
exit 1
