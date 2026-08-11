#!/usr/bin/env bash
# build-frontends.sh — Build all React frontends on the mini PC.
# Run from the repo root: bash scripts/build-frontends.sh [app-name]
# With no argument, builds all apps.
# Requires Node.js — installs via nvm if not present.

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="${REPO}/frontend"

APPS=(admin chat writer coding autocoder trading)

# ── Node check ────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    warn "Node.js not found — installing via nvm..."
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    # shellcheck source=/dev/null
    source "$NVM_DIR/nvm.sh"
    nvm install --lts
    nvm use --lts
    ok "Node $(node --version) installed"
else
    ok "Node $(node --version) found"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=("${APPS[@]}")

PASSED=0; FAILED=0
for app in "${TARGETS[@]}"; do
    dir="${FRONTEND}/${app}"
    if [ ! -f "${dir}/package.json" ]; then
        warn "${app} — no package.json, skipping"
        continue
    fi

    info "Building ${app}..."
    if [ ! -f "${dir}/package-lock.json" ]; then
        warn "${app} — package-lock.json missing; run 'git pull' to restore it"
        warn "${app} — generating package-lock.json with npm install (commit it afterwards)"
        npm --prefix "${dir}" install --silent 2>/dev/null || true
    fi
    if npm --prefix "${dir}" ci --silent; then
        if npm --prefix "${dir}" run build --silent; then
            ok "${app} — dist ready at frontend/${app}/dist/"
            PASSED=$((PASSED+1))
        else
            fail "${app} — build failed"
            FAILED=$((FAILED+1))
        fi
    else
        fail "${app} — npm ci failed"
        FAILED=$((FAILED+1))
    fi
done

# ── Update Caddyfile to serve static files ────────────────────────────────────
if [ $PASSED -gt 0 ]; then
    info "Updating Caddyfile..."
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "100.105.155.91")

    sudo tee /etc/caddy/Caddyfile > /dev/null << CADDYEOF
# Managed by admin panel — do not edit manually

http://${TAILSCALE_IP} {
    handle /admin/api* {
        uri strip_prefix /admin/api
        reverse_proxy localhost:8000
    }
    handle /admin* {
        uri strip_prefix /admin
        root * ${FRONTEND}/admin/dist
        try_files {path} /index.html
        file_server
    }

    handle /autocoder/api* {
        uri strip_prefix /autocoder/api
        reverse_proxy localhost:8050
    }
    handle /autocoder* {
        uri strip_prefix /autocoder
        root * ${FRONTEND}/autocoder/dist
        try_files {path} /index.html
        file_server
    }

    handle /chat/api* {
        uri strip_prefix /chat/api
        reverse_proxy localhost:8010
    }
    handle /chat* {
        uri strip_prefix /chat
        root * ${FRONTEND}/chat/dist
        try_files {path} /index.html
        file_server
    }

    handle /writer/api* {
        uri strip_prefix /writer
        reverse_proxy localhost:8011
    }
    handle /writer* {
        uri strip_prefix /writer
        root * ${FRONTEND}/writer/dist
        try_files {path} /index.html
        file_server
    }

    handle /coding/api* {
        uri strip_prefix /coding/api
        reverse_proxy localhost:8012
    }
    handle /coding* {
        uri strip_prefix /coding
        root * ${FRONTEND}/coding/dist
        try_files {path} /index.html
        file_server
    }

    handle /trading/api* {
        uri strip_prefix /trading/api
        reverse_proxy localhost:8030
    }
    handle /trading/audit* {
        uri strip_prefix /trading/audit
        reverse_proxy localhost:8031
    }
    handle /trading* {
        uri strip_prefix /trading
        root * ${FRONTEND}/trading/dist
        try_files {path} /index.html
        file_server
    }
}
CADDYEOF

    sudo caddy fmt --overwrite /etc/caddy/Caddyfile
    sudo systemctl reload caddy
    ok "Caddy updated and reloaded"
fi

echo ""
echo "────────────────────────────────────────"
echo "Built: ${PASSED} ok, ${FAILED} failed"
[ $FAILED -eq 0 ] && ok "All frontends built" || fail "Some builds failed"
exit $FAILED
