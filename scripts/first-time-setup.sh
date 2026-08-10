#!/usr/bin/env bash
# First-time platform setup on a fresh Ubuntu mini PC (ms-s1).
# Run from the dev machine: ./first-time-setup.sh
# Requires: SSH key auth already configured to jarvis@ms-s1

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

HOST="jarvis@ms-s1"
PLATFORM="/opt/platform"
REPO="https://github.com/yourusername/jarvis.git"  # TODO: set actual repo URL

# Check SSH
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
  fail "Cannot reach $HOST"
  info "Make sure: 1) Tailscale is running, 2) SSH key is configured on ms-s1"
  exit 1
fi
ok "SSH connection verified"

ssh "$HOST" bash -s << 'REMOTE'
set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
info() { echo -e "       $*"; }

PLATFORM="/opt/platform"

# ── System packages ───────────────────────────────────────────────────────────

info "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq git python3.12 python3.12-venv python3.12-dev \
  curl build-essential nodejs npm
ok "System packages installed"

# ── Clone repository ──────────────────────────────────────────────────────────

if [ -d "$PLATFORM/.git" ]; then
  info "Repository already exists — pulling latest..."
  cd "$PLATFORM" && git pull origin main
else
  info "Cloning repository..."
  sudo mkdir -p "$PLATFORM"
  sudo chown jarvis:jarvis "$PLATFORM"
  git clone REPO_PLACEHOLDER "$PLATFORM"
fi
ok "Repository ready"

# ── Data directories ──────────────────────────────────────────────────────────

sudo mkdir -p "$PLATFORM/data/projects"
sudo chown -R jarvis:jarvis "$PLATFORM/data"
ok "Data directories created"

# ── Virtual environments and dependencies ─────────────────────────────────────

SERVICES=(
  "admin"
  "chat"
  "writer"
  "coding"
  "autocoder/conductor"
  "autocoder/re-agent"
  "autocoder/dashboard"
  "autocoder/specialists/backend"
  "autocoder/specialists/frontend"
  "autocoder/specialists/db"
  "autocoder/specialists/tester"
  "autocoder/specialists/refactorer"
  "trading"
  "memory"
  "tools"
)

for svc in "${SERVICES[@]}"; do
  dir="$PLATFORM/$svc"
  if [ -f "$dir/requirements.txt" ]; then
    info "Setting up venv for $svc..."
    python3.12 -m venv "$dir/venv"
    "$dir/venv/bin/pip" install --quiet -r "$dir/requirements.txt"
    ok "$svc"
  fi
done

# Trading auditor has its own entry point but shares trading requirements
if [ -f "$PLATFORM/trading/requirements.txt" ]; then
  mkdir -p "$PLATFORM/trading/auditor"
  [ -d "$PLATFORM/trading/auditor/venv" ] || ln -sf "$PLATFORM/trading/venv" "$PLATFORM/trading/auditor/venv"
fi

# ── Systemd units ─────────────────────────────────────────────────────────────

info "Installing systemd service units..."
sudo cp "$PLATFORM/systemd/"*.service /etc/systemd/system/
sudo systemctl daemon-reload

for unit in $(ls "$PLATFORM/systemd/"); do
  sudo systemctl enable "${unit%.service}" 2>/dev/null || true
done
ok "Systemd units installed and enabled"

# ── Frontend dist directories ─────────────────────────────────────────────────

for app in admin chat writer coding autocoder trading; do
  mkdir -p "$PLATFORM/frontend/$app/dist"
done
ok "Frontend directories created (deploy frontends separately with deploy-frontend.sh)"

echo ""
ok "First-time setup complete"
echo ""
echo "Next steps:"
echo "  1. Install Ollama: curl -fsSL https://ollama.com/install.sh | sh"
echo "  2. Pull models: ollama pull qwen2.5:14b && ollama pull qwen2.5-coder:32b"
echo "  3. Install and configure Caddy (see docs/SETUP.md Part 4)"
echo "  4. Start services: sudo systemctl start platform-admin platform-chat"
echo "  5. Run validation: python3 scripts/validate-platform.py"
REMOTE

ok "Remote setup complete"
warn "Remember to set the actual GitHub repo URL in this script (REPO_PLACEHOLDER)"
