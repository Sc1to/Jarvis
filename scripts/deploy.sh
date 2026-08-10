#!/usr/bin/env bash
# Deploy one service or all services to the mini PC.
# Usage: ./deploy.sh [service-name]
# Examples:
#   ./deploy.sh          — deploy all services
#   ./deploy.sh admin    — deploy only the admin service

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

HOST="jarvis@ms-s1"
PLATFORM="/opt/platform"

# service-name → (port, relative-path-under-platform, systemd-unit)
declare -A SVC_PORT=(
  [admin]=8000
  [chat]=8010
  [writer]=8011
  [coding]=8012
  [autocoder-conductor]=8001
  [autocoder-re-agent]=8002
  [autocoder-dashboard]=8050
  [autocoder-specialist-backend]=8003
  [autocoder-specialist-frontend]=8004
  [autocoder-specialist-db]=8005
  [autocoder-specialist-tester]=8006
  [autocoder-specialist-refactorer]=8007
  [trading]=8030
  [trading-auditor]=8031
)
declare -A SVC_DIR=(
  [admin]=admin
  [chat]=chat
  [writer]=writer
  [coding]=coding
  [autocoder-conductor]=autocoder/conductor
  [autocoder-re-agent]=autocoder/re-agent
  [autocoder-dashboard]=autocoder/dashboard
  [autocoder-specialist-backend]=autocoder/specialists/backend
  [autocoder-specialist-frontend]=autocoder/specialists/frontend
  [autocoder-specialist-db]=autocoder/specialists/db
  [autocoder-specialist-tester]=autocoder/specialists/tester
  [autocoder-specialist-refactorer]=autocoder/specialists/refactorer
  [trading]=trading
  [trading-auditor]=trading/auditor
)

check_ssh() {
  if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
    fail "Cannot reach $HOST — check SSH key auth and Tailscale connection"
    exit 1
  fi
}

deploy_one() {
  local name="$1"
  if [[ -z "${SVC_PORT[$name]+_}" ]]; then
    fail "Unknown service: $name"
    info "Known services: ${!SVC_PORT[*]}"
    return 1
  fi

  local port="${SVC_PORT[$name]}"
  local dir="${SVC_DIR[$name]}"
  local unit="platform-${name}"

  echo ""
  info "Deploying ${name} (port ${port})..."

  ssh "$HOST" bash -s << EOF
set -e
cd ${PLATFORM}
git pull origin main --quiet
cd ${PLATFORM}/${dir}
source venv/bin/activate
pip install -r requirements.txt --quiet
sudo systemctl restart ${unit}
sleep 5
curl -sf http://localhost:${port}/health > /dev/null
EOF

  if [ $? -eq 0 ]; then
    ok "$name"
  else
    fail "$name — health check failed after restart"
    return 1
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

check_ssh

SERVICES=("$@")
if [ ${#SERVICES[@]} -eq 0 ]; then
  SERVICES=("${!SVC_PORT[@]}")
fi

PASSED=0; FAILED=0
for svc in "${SERVICES[@]}"; do
  if deploy_one "$svc"; then
    PASSED=$((PASSED+1))
  else
    FAILED=$((FAILED+1))
  fi
done

echo ""
echo "────────────────────────────────"
echo "Deployed: ${PASSED} passed, ${FAILED} failed"
[ $FAILED -eq 0 ] && ok "All deployments successful" || fail "Some deployments failed"
exit $FAILED
