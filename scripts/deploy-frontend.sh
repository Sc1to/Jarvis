#!/usr/bin/env bash
# Deploy a React frontend app to the mini PC.
# Usage: ./deploy-frontend.sh <app-name>
# Examples:
#   ./deploy-frontend.sh admin
#   ./deploy-frontend.sh trading

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' NC='\033[0m'
ok()   { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "       $*"; }

HOST="jarvis@ms-s1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

APP="${1:-}"
if [ -z "$APP" ]; then
  fail "Usage: $0 <app-name>  (admin|chat|writer|coding|autocoder|trading)"
  exit 1
fi

FRONTEND_DIR="${REPO_ROOT}/frontend/${APP}"
if [ ! -d "$FRONTEND_DIR" ]; then
  fail "No frontend directory at frontend/${APP}"
  exit 1
fi

# ── Build locally ─────────────────────────────────────────────────────────────

info "Building frontend/${APP}..."
npm --prefix "$FRONTEND_DIR" run build
ok "Build complete"

# ── Upload to mini PC ─────────────────────────────────────────────────────────

info "Uploading to ${HOST}..."
ssh "$HOST" "mkdir -p /opt/platform/frontend/${APP}"
scp -r "${FRONTEND_DIR}/dist/" "${HOST}:/opt/platform/frontend/${APP}/dist/"
ok "Upload complete"

# ── Reload Caddy ─────────────────────────────────────────────────────────────

info "Reloading Caddy..."
ssh "$HOST" "sudo systemctl reload caddy"
ok "Caddy reloaded"

echo ""
ok "frontend/${APP} deployed"
