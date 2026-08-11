#!/usr/bin/env bash
# restart.sh — Restart all systemd units for an app (no git pull, no pip install).
# Run on the mini PC: bash scripts/restart.sh <app>
# Usage:
#   bash scripts/restart.sh autocoder
#   bash scripts/restart.sh admin
#   bash scripts/restart.sh all

set -euo pipefail

GREEN='\033[0;32m' RED='\033[0;31m' NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

declare -A APP_UNITS=(
  [admin]="platform-admin"
  [chat]="platform-chat"
  [writer]="platform-writer"
  [coding]="platform-coding"
  [trading]="platform-trading platform-trading-auditor"
  [autocoder]="platform-autocoder-conductor
               platform-autocoder-re-agent
               platform-autocoder-dashboard
               platform-autocoder-specialist-backend
               platform-autocoder-specialist-frontend
               platform-autocoder-specialist-db
               platform-autocoder-specialist-tester
               platform-autocoder-specialist-refactorer"
)

restart_app() {
  local app="$1"
  if [[ -z "${APP_UNITS[$app]+_}" ]]; then
    fail "Unknown app: $app"
    echo "Known apps: ${!APP_UNITS[*]}"
    return 1
  fi
  # shellcheck disable=SC2206
  local units=(${APP_UNITS[$app]})
  echo "Restarting ${app} (${#units[@]} unit(s))..."
  sudo systemctl restart "${units[@]}"
  ok "$app restarted"
}

APP="${1:-}"
if [[ -z "$APP" ]]; then
  echo "Usage: bash scripts/restart.sh <app|all>"
  echo "Apps:  ${!APP_UNITS[*]}"
  exit 1
fi

if [[ "$APP" == "all" ]]; then
  for app in "${!APP_UNITS[@]}"; do
    restart_app "$app" || true
  done
else
  restart_app "$APP"
fi
