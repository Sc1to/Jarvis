#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env.docker ] || cp .env.docker.example .env.docker
docker compose up -d
echo "Platform started — admin at http://localhost:8000"
