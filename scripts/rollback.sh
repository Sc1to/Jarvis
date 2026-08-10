#!/usr/bin/env bash
# Roll back the last git commit on the mini PC and restart affected services.
# Usage: ./rollback.sh [service-name ...]
# If no service is given, only the git rollback happens — restart manually.

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

HOST="jarvis@ms-s1"

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
  fail "Cannot reach $HOST"
  exit 1
fi

# Show what will be rolled back
info "Current HEAD on mini PC:"
ssh "$HOST" "cd /opt/platform && git log --oneline -3"

echo ""
warn "This will reset HEAD~1 on the mini PC — one commit will be lost from the remote tree"
read -r -p "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted"; exit 0; }

ssh "$HOST" "cd /opt/platform && git reset --hard HEAD~1"
ok "Rolled back to $(ssh "$HOST" "cd /opt/platform && git log --oneline -1")"

SERVICES=("$@")
if [ ${#SERVICES[@]} -gt 0 ]; then
  for svc in "${SERVICES[@]}"; do
    info "Restarting platform-${svc}..."
    ssh "$HOST" "sudo systemctl restart platform-${svc}" && ok "$svc restarted" || fail "$svc restart failed"
  done
else
  warn "No services specified — restart manually: sudo systemctl restart platform-<name>"
fi
