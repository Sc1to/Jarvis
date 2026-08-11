#!/usr/bin/env bash
# setup.sh — Platform infrastructure setup
# Run on the mini PC as the jarvis user.
# Safe to re-run — each section is independent and skips what's already done.

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
step() { echo -e "\n${YELLOW}▶${NC} $1"; }

ERRORS=0
err() { fail "$1"; ERRORS=$((ERRORS+1)); }

[[ $EUID -eq 0 ]] && { echo "Run as jarvis, not root: bash setup.sh"; exit 1; }

# ── 1. System update ──────────────────────────────────────────────────────────
step "System update"
sudo apt-get update -q && sudo apt-get upgrade -y -q \
  && ok "System updated" || err "System update failed"

# ── 2. Disable sleep ──────────────────────────────────────────────────────────
step "Disable sleep"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target \
  && ok "Sleep disabled" || ok "Sleep already disabled"

# ── 3. System packages ────────────────────────────────────────────────────────
step "System packages"
sudo apt-get install -y -q \
    git curl \
    python3 python3-venv python3-pip \
    build-essential \
    apt-transport-https debian-keyring debian-archive-keyring \
    software-properties-common \
  && ok "System packages installed" || err "System packages failed"

# ── 4. Node.js ────────────────────────────────────────────────────────────────
step "Node.js"
if command -v node &>/dev/null; then
    ok "Node.js already installed ($(node --version))"
else
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - \
      && sudo apt-get install -y nodejs \
      && ok "Node.js $(node --version) installed" \
      || err "Node.js install failed"
fi

# ── 5. Tailscale ──────────────────────────────────────────────────────────────
step "Tailscale"
if command -v tailscale &>/dev/null; then
    ok "Tailscale already installed"
else
    curl -fsSL https://tailscale.com/install.sh | sh \
      && ok "Tailscale installed" || err "Tailscale install failed"
fi

if sudo tailscale status &>/dev/null; then
    ok "Tailscale already connected"
else
    warn "Open the URL below on any device and click Authenticate, then press Enter here"
    sudo tailscale up || err "Tailscale auth failed"
fi

# ── 6. Caddy ─────────────────────────────────────────────────────────────────
step "Caddy"
if command -v caddy &>/dev/null; then
    ok "Caddy already installed"
else
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -q && sudo apt-get install -y caddy \
      && ok "Caddy installed" || err "Caddy install failed"
fi

# Write Caddyfile
TS_IP=$(sudo tailscale ip -4 2>/dev/null || echo "")
TS_HOSTNAME=$(tailscale status --json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" \
    2>/dev/null || echo "")
# Use IP as fallback if hostname not set yet
CADDY_HOST="${TS_HOSTNAME:-${TS_IP:-localhost}}"

sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
# Managed by admin panel — do not edit manually

${CADDY_HOST} {
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
        root * /opt/platform/platform/frontend/trading/dist
        file_server
    }
}
EOF

sudo systemctl enable caddy
sudo systemctl restart caddy \
  && ok "Caddy running (host: ${CADDY_HOST})" || err "Caddy failed to start"

# ── 7. Ollama ─────────────────────────────────────────────────────────────────
step "Ollama"
if command -v ollama &>/dev/null; then
    ok "Ollama already installed"
else
    curl -fsSL https://ollama.com/install.sh | sh \
      && ok "Ollama installed" || err "Ollama install failed"
fi

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/env.conf > /dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=1"
# Set OLLAMA_MODELS to your model HD mount point before pulling models:
# Environment="OLLAMA_MODELS=/mnt/models"
EOF
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama \
  && ok "Ollama running" || err "Ollama failed to start"

# ── 8. Docker ─────────────────────────────────────────────────────────────────
step "Docker"
if command -v docker &>/dev/null; then
    ok "Docker already installed"
else
    sudo apt-get install -y docker.io \
      && ok "Docker installed" || err "Docker install failed"
fi
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker jarvis 2>/dev/null || true

# ── 9. Directory structure ────────────────────────────────────────────────────
step "Platform directory structure"
sudo mkdir -p /opt/platform/{admin,chat,writer,coding,trading}
sudo mkdir -p /opt/platform/autocoder/{conductor,re-agent,specialists}
sudo mkdir -p /opt/platform/frontend/{admin,autocoder,chat,writer,coding,trading}
sudo mkdir -p /opt/platform/data/{chromadb,projects}
sudo chown -R jarvis:jarvis /opt/platform
ok "Directory structure ready"

# ── 10. Open WebUI ────────────────────────────────────────────────────────────
step "Open WebUI"
if sudo docker ps -a --format '{{.Names}}' | grep -q "^open-webui$"; then
    ok "Open WebUI already exists"
    sudo docker start open-webui 2>/dev/null || true
else
    sudo docker run -d \
        --name open-webui \
        --restart always \
        -p 3000:8080 \
        -v open-webui:/app/backend/data \
        -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
        ghcr.io/open-webui/open-webui:main \
      && ok "Open WebUI started" || err "Open WebUI failed to start"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "  ${GREEN}SETUP COMPLETE — no errors${NC}"
else
    echo -e "  ${RED}SETUP DONE WITH ${ERRORS} ERROR(S) — scroll up to see what failed${NC}"
fi
echo ""
echo "  Tailscale IP:  ${TS_IP:-not connected}"
echo "  Platform URL:  http://${CADDY_HOST}"
echo "  Chat:          http://${CADDY_HOST}/chat"
echo ""
echo "  Next: mount model HD, set OLLAMA_MODELS in"
echo "  /etc/systemd/system/ollama.service.d/env.conf"
echo "  then pull models with: ollama pull qwen2.5:14b"
echo "============================================"
