#!/usr/bin/env bash
# setup.sh — Platform infrastructure setup
# Run as the jarvis user on a fresh Ubuntu 24.04 LTS install.
# Safe to re-run — skips steps already done.
# Models are NOT downloaded — configure OLLAMA_MODELS and pull manually from your model HD.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
step() { echo -e "\n${YELLOW}▶${NC} $1"; }

[[ $EUID -eq 0 ]] && { echo "Run as jarvis, not root: bash setup.sh"; exit 1; }

# ── 1. System update ──────────────────────────────────────────────────────────
step "System update"
sudo apt-get update -q
sudo apt-get upgrade -y -q
ok "System updated"

# ── 2. Disable sleep/hibernate ────────────────────────────────────────────────
step "Disable sleep and hibernate"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
ok "Sleep disabled"

# ── 3. System dependencies ────────────────────────────────────────────────────
step "System dependencies"
sudo apt-get install -y -q \
    git curl \
    python3.12 python3.12-venv python3-pip \
    build-essential \
    apt-transport-https debian-keyring debian-archive-keyring \
    software-properties-common
ok "System dependencies installed"

# ── 4. Node.js LTS ────────────────────────────────────────────────────────────
step "Node.js"
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
ok "Node.js $(node --version)"

# ── 5. Tailscale ──────────────────────────────────────────────────────────────
step "Tailscale"
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! sudo tailscale status &>/dev/null; then
    warn "A URL will appear below — open it on any device and click Authenticate"
    sudo tailscale up
fi
ok "Tailscale connected"

# Resolve Tailscale hostname for Caddyfile
TS_HOSTNAME=$(tailscale status --json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" \
    2>/dev/null || echo "ms-s1")

# ── 6. Caddy ──────────────────────────────────────────────────────────────────
step "Caddy"
if ! command -v caddy &>/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -q && sudo apt-get install -y caddy
fi

sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
# Caddyfile — managed by admin panel
# Tailscale hostname: ${TS_HOSTNAME}

${TS_HOSTNAME} {
    handle /admin* {
        reverse_proxy localhost:8000
    }
    handle /autocoder* {
        reverse_proxy localhost:8001
    }
    handle /chat* {
        reverse_proxy localhost:3000
    }
    handle /writer* {
        reverse_proxy localhost:8011
    }
    handle /coding* {
        reverse_proxy localhost:8012
    }
    handle /trading/api/* {
        reverse_proxy localhost:8030
    }
    handle /trading/audit/* {
        uri strip_prefix /trading/audit
        reverse_proxy localhost:8031
    }
    handle /trading* {
        root * /opt/platform/frontend/trading/dist
        file_server
    }
}
EOF

sudo systemctl enable caddy
sudo systemctl restart caddy
ok "Caddy configured — ${TS_HOSTNAME}"

# ── 7. Ollama ─────────────────────────────────────────────────────────────────
step "Ollama"
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Systemd env drop-in
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/env.conf > /dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=1"
# ponytail: OLLAMA_MODELS points to model HD — set this before pulling models
# Environment="OLLAMA_MODELS=/mnt/models"
EOF

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama
ok "Ollama installed"
warn "Set OLLAMA_MODELS in /etc/systemd/system/ollama.service.d/env.conf before pulling models"

# ── 8. Docker ─────────────────────────────────────────────────────────────────
step "Docker"
if ! command -v docker &>/dev/null; then
    sudo apt-get install -y docker.io
fi
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker jarvis || true
ok "Docker installed (log out and back in for docker group to take effect)"

# ── 9. Directory structure ────────────────────────────────────────────────────
step "Platform directory structure"
sudo mkdir -p /opt/platform/{admin,chat,writer,coding,trading}
sudo mkdir -p /opt/platform/autocoder/{conductor,re-agent,specialists}
sudo mkdir -p /opt/platform/frontend/{admin,autocoder,chat,writer,coding,trading}
sudo mkdir -p /opt/platform/data/{chromadb,projects}
sudo mkdir -p /opt/platform/docs
sudo chown -R jarvis:jarvis /opt/platform
ok "Created /opt/platform/"

# ── 10. Open WebUI ────────────────────────────────────────────────────────────
step "Open WebUI"
if sudo docker ps -a --format '{{.Names}}' | grep -q "^open-webui$"; then
    ok "Open WebUI already running"
else
    sudo docker run -d \
        --name open-webui \
        --restart always \
        -p 3000:8080 \
        -v open-webui:/app/backend/data \
        -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
        ghcr.io/open-webui/open-webui:main
    ok "Open WebUI started on port 3000"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  SETUP COMPLETE"
echo "============================================"
echo "  Platform URL:  http://${TS_HOSTNAME}"
echo "  Chat UI:       http://${TS_HOSTNAME}/chat"
echo ""
echo "  Next steps:"
echo "  1. Mount your model HD, set OLLAMA_MODELS in:"
echo "     /etc/systemd/system/ollama.service.d/env.conf"
echo "     then: sudo systemctl daemon-reload && sudo systemctl restart ollama"
echo "  2. Pull models: ollama pull qwen2.5:14b  (and others)"
echo "  3. Deploy platform services: bash scripts/first-time-setup.sh"
echo "  4. Log out and back in for Docker group to take effect"
echo "============================================"
