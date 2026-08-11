#!/usr/bin/env bash
# first-time-setup.sh — Deploy platform services to the mini PC for the first time.
# Run from the dev machine after setup.sh has been run on the mini PC.
# Requires: SSH key auth to jarvis@ms-s1 (Tailscale must be running on both machines).
# Safe to re-run — skips venvs that already exist, pulls latest code if repo exists.

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
info() { echo -e "       $*"; }

HOST="jarvis@ms-s1"
REPO="https://github.com/Sc1to/Jarvis.git"

# ── SSH check ─────────────────────────────────────────────────────────────────
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
    fail "Cannot reach $HOST — check Tailscale and SSH key auth"
    exit 1
fi
ok "SSH connection verified"

# ── Remote setup ──────────────────────────────────────────────────────────────
ssh "$HOST" bash -s << REMOTE
set -euo pipefail

GREEN='\033[0;32m' NC='\033[0m'
ok()   { echo -e "\${GREEN}[OK]\${NC}   \$*"; }
info() { echo -e "       \$*"; }

REPO_PATH="/opt/platform"
PLATFORM="\${REPO_PATH}/platform"

# ── Clone or update repo ──────────────────────────────────────────────────────
if [ -d "\${REPO_PATH}/.git" ]; then
    info "Repository exists — pulling latest..."
    git -C "\${REPO_PATH}" pull origin main --quiet
else
    info "Cloning into existing directory..."
    git -C "\${REPO_PATH}" init --quiet
    git -C "\${REPO_PATH}" remote add origin ${REPO}
    git -C "\${REPO_PATH}" fetch --quiet
    git -C "\${REPO_PATH}" checkout -t origin/main --quiet
fi
ok "Repository ready"

# ── Data directories ──────────────────────────────────────────────────────────
mkdir -p "\${REPO_PATH}/data/"{projects,writer,chromadb}
ok "Data directories ready"

# ── Virtual environments ──────────────────────────────────────────────────────
SERVICES=(
    "memory"
    "tools"
    "admin"
    "chat"
    "writer"
    "coding"
    "trading"
    "autocoder/conductor"
    "autocoder/re-agent"
    "autocoder/dashboard"
    "autocoder/specialists/backend"
    "autocoder/specialists/frontend"
    "autocoder/specialists/db"
    "autocoder/specialists/tester"
    "autocoder/specialists/refactorer"
)

for svc in "\${SERVICES[@]}"; do
    dir="\${PLATFORM}/\${svc}"
    if [ ! -f "\${dir}/requirements.txt" ]; then
        info "Skipping \${svc} — no requirements.txt yet"
        continue
    fi
    if [ -d "\${dir}/venv" ]; then
        info "\${svc} venv exists — updating dependencies..."
    else
        info "Creating venv for \${svc}..."
        python3 -m venv "\${dir}/venv"
    fi
    "\${dir}/venv/bin/pip" install --quiet -r "\${dir}/requirements.txt"
    ok "\${svc}"
done

# ── Systemd units ─────────────────────────────────────────────────────────────
info "Installing systemd units..."
sudo cp "\${REPO_PATH}/systemd/"*.service /etc/systemd/system/
sudo systemctl daemon-reload
for unit in "\${REPO_PATH}/systemd/"*.service; do
    name="\$(basename "\${unit%.service}")"
    sudo systemctl enable "\${name}" 2>/dev/null || true
done
ok "Systemd units installed and enabled"

echo ""
ok "First-time setup complete"
echo ""
echo "  Next: bash scripts/validate-platform.py"
REMOTE

ok "Done"
