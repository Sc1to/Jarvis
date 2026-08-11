#!/usr/bin/env bash
# setup-services.sh — Run directly on the mini PC to create venvs, install
# dependencies, and start all platform services.
# Safe to re-run: skips venvs that already exist, updates deps if they do.
# Usage: bash scripts/setup-services.sh [service-name]
#   No argument = set up all services.
#   service-name = one of: admin chat writer coding trading
#                          autocoder-conductor autocoder-re-agent autocoder-dashboard
#                          autocoder-specialist-backend autocoder-specialist-frontend
#                          autocoder-specialist-db autocoder-specialist-tester
#                          autocoder-specialist-refactorer health-monitor

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM="${REPO}/platform"

# service-name → relative path under PLATFORM (or REPO for scripts)
declare -A SVC_DIR=(
  [admin]="platform/admin"
  [chat]="platform/chat"
  [writer]="platform/writer"
  [coding]="platform/coding"
  [trading]="platform/trading"
  [autocoder-conductor]="platform/autocoder/conductor"
  [autocoder-re-agent]="platform/autocoder/re-agent"
  [autocoder-dashboard]="platform/autocoder/dashboard"
  [autocoder-specialist-backend]="platform/autocoder/specialists/backend"
  [autocoder-specialist-frontend]="platform/autocoder/specialists/frontend"
  [autocoder-specialist-db]="platform/autocoder/specialists/db"
  [autocoder-specialist-tester]="platform/autocoder/specialists/tester"
  [autocoder-specialist-refactorer]="platform/autocoder/specialists/refactorer"
  [health-monitor]="scripts"
)

declare -A SVC_PORT=(
  [admin]=8000
  [chat]=8010
  [writer]=8011
  [coding]=8012
  [trading]=8030
  [autocoder-conductor]=8001
  [autocoder-re-agent]=8002
  [autocoder-dashboard]=8050
  [autocoder-specialist-backend]=8003
  [autocoder-specialist-frontend]=8004
  [autocoder-specialist-db]=8005
  [autocoder-specialist-tester]=8006
  [autocoder-specialist-refactorer]=8007
  [health-monitor]=""
)

setup_shared() {
  for shared in memory tools; do
    dir="${PLATFORM}/${shared}"
    if [ ! -f "${dir}/requirements.txt" ]; then
      info "Skipping shared/${shared} — no requirements.txt"
      continue
    fi
    info "Setting up shared/${shared}..."
    if [ ! -d "${dir}/venv" ]; then
      python3 -m venv "${dir}/venv"
    fi
    "${dir}/venv/bin/pip" install --quiet -r "${dir}/requirements.txt"
    ok "shared/${shared}"
  done
}

setup_one() {
  local name="$1"
  if [[ -z "${SVC_DIR[$name]+_}" ]]; then
    fail "Unknown service: $name"
    info "Known services: ${!SVC_DIR[*]}"
    return 1
  fi

  local rel="${SVC_DIR[$name]}"
  local dir="${REPO}/${rel}"
  local unit="platform-${name}"

  if [ ! -f "${dir}/requirements.txt" ]; then
    warn "${name} — no requirements.txt at ${rel}, skipping"
    return 0
  fi

  info "Setting up ${name}..."
  if [ ! -d "${dir}/venv" ]; then
    python3 -m venv "${dir}/venv"
  fi
  "${dir}/venv/bin/pip" install --quiet -r "${dir}/requirements.txt"

  # Install systemd unit if it exists
  local unit_src="${REPO}/systemd/${unit}.service"
  if [ -f "${unit_src}" ]; then
    sudo cp "${unit_src}" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable "${unit}" 2>/dev/null || true
    sudo systemctl restart "${unit}"

    local port="${SVC_PORT[$name]}"
    if [ -n "${port}" ]; then
      sleep 3
      if curl -sf "http://localhost:${port}/health" > /dev/null 2>&1; then
        ok "${name} — running on :${port}"
      else
        warn "${name} — started but health check failed (may still be initialising)"
      fi
    else
      ok "${name} — started (no health port)"
    fi
  else
    warn "${name} — no systemd unit found, skipping service start"
  fi
}

# ── Data directories ──────────────────────────────────────────────────────────
sudo mkdir -p /opt/platform/data/{projects,writer,chromadb}
ok "Data directories ready"

# ── Shared packages ───────────────────────────────────────────────────────────
setup_shared

# ── Services ─────────────────────────────────────────────────────────────────
TARGETS=("$@")
if [ ${#TARGETS[@]} -eq 0 ]; then
  TARGETS=("${!SVC_DIR[@]}")
fi

PASSED=0; FAILED=0; SKIPPED=0
for svc in "${TARGETS[@]}"; do
  if setup_one "$svc"; then
    PASSED=$((PASSED+1))
  else
    FAILED=$((FAILED+1))
  fi
done

echo ""
echo "────────────────────────────────────────"
echo "Services: ${PASSED} ok, ${FAILED} failed"
[ $FAILED -eq 0 ] && ok "All done" || fail "Some services failed — check logs with: sudo journalctl -u platform-<name> -n 30"
exit $FAILED
