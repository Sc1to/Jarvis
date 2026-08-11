#!/usr/bin/env bash
# install-ollama.sh — Install Ollama and configure it for platform use.
#
# Usage:
#   bash scripts/install-ollama.sh --device /dev/sdX [--models-dir /mnt/ollama-models]
#
# Arguments:
#   --device      (required) Block device to mount for model storage, e.g. /dev/sdb
#   --models-dir  (optional) Mount point for the device. Default: /mnt/ollama-models
#   --skip-format (optional) Skip mkfs — use if device is already formatted
#   --skip-mount  (optional) Skip partitioning/mounting entirely — use if already mounted
#
# What this script does:
#   1. Validate arguments and confirm destructive actions before proceeding
#   2. Format and mount the dedicated model storage drive (unless skipped)
#   3. Add the drive to /etc/fstab for auto-mount on boot
#   4. Install Ollama via the official install script
#   5. Write systemd override with OLLAMA_MODELS and platform env vars
#   6. Reload systemd and restart Ollama
#   7. Verify Ollama is reachable at http://localhost:11434

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
DEVICE=""
MODELS_DIR="/mnt/ollama-models"
SKIP_FORMAT=false
SKIP_MOUNT=false
OLLAMA_URL="https://ollama.com/install.sh"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }
heading() { echo -e "\n${BOLD}=== $* ===${NC}"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --device)      DEVICE="$2";      shift 2 ;;
        --models-dir)  MODELS_DIR="$2";  shift 2 ;;
        --skip-format) SKIP_FORMAT=true; shift   ;;
        --skip-mount)  SKIP_MOUNT=true;  shift   ;;
        -h|--help)
            sed -n '2,30p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die "Unknown argument: $1. Use --help for usage." ;;
    esac
done

# ── Pre-flight checks ─────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run this script with sudo: sudo bash scripts/install-ollama.sh ..."

if [[ "$SKIP_MOUNT" == false ]]; then
    [[ -n "$DEVICE" ]] || die "--device is required unless --skip-mount is set. Example: --device /dev/sdb"
    [[ -b "$DEVICE" ]] || die "Device $DEVICE does not exist or is not a block device. Run 'lsblk' to list drives."
fi

# ── Step 1 — Mount dedicated drive ───────────────────────────────────────────
heading "Step 1: Model storage drive"

if [[ "$SKIP_MOUNT" == true ]]; then
    info "Skipping mount (--skip-mount set). Expecting $MODELS_DIR to already be mounted."
    mountpoint -q "$MODELS_DIR" || die "$MODELS_DIR is not mounted. Mount it first or omit --skip-mount."
else
    info "Device:     $DEVICE"
    info "Mount point: $MODELS_DIR"

    if [[ "$SKIP_FORMAT" == false ]]; then
        echo ""
        warn "This will FORMAT $DEVICE as ext4. ALL DATA ON IT WILL BE LOST."
        warn "If this drive already has data, re-run with --skip-format."
        echo ""
        read -r -p "Type YES to confirm formatting $DEVICE: " confirm
        [[ "$confirm" == "YES" ]] || die "Aborted. No changes made."

        info "Formatting $DEVICE as ext4..."
        mkfs.ext4 -F "$DEVICE"
        info "Format complete."
    else
        info "Skipping format (--skip-format set)."
    fi

    info "Creating mount point at $MODELS_DIR..."
    mkdir -p "$MODELS_DIR"

    info "Mounting $DEVICE at $MODELS_DIR..."
    mount "$DEVICE" "$MODELS_DIR"

    # Add to fstab if not already present
    DEVICE_UUID=$(blkid -s UUID -o value "$DEVICE")
    FSTAB_ENTRY="UUID=$DEVICE_UUID  $MODELS_DIR  ext4  defaults  0  2"
    if grep -q "$DEVICE_UUID" /etc/fstab; then
        info "Device already in /etc/fstab — skipping."
    else
        info "Adding to /etc/fstab for auto-mount on boot..."
        echo "$FSTAB_ENTRY" >> /etc/fstab
        info "fstab updated."
    fi
fi

# ── Step 2 — Install Ollama ───────────────────────────────────────────────────
heading "Step 2: Install Ollama"

if command -v ollama &>/dev/null; then
    CURRENT_VERSION=$(ollama --version 2>/dev/null | awk '{print $NF}' || echo "unknown")
    info "Ollama already installed (version: $CURRENT_VERSION). Skipping install."
else
    info "Downloading and running official Ollama installer..."
    curl -fsSL "$OLLAMA_URL" | sh
    info "Ollama installed."
fi

# Ensure the ollama user/group exist (created by the installer)
id ollama &>/dev/null || die "ollama system user not found — installer may have failed."

# ── Step 3 — Set model storage ownership ──────────────────────────────────────
heading "Step 3: Set ownership"

info "Setting $MODELS_DIR ownership to ollama:ollama..."
chown -R ollama:ollama "$MODELS_DIR"
info "Ownership set."

# ── Step 4 — Systemd override ─────────────────────────────────────────────────
heading "Step 4: Configure systemd override"

OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

mkdir -p "$OVERRIDE_DIR"

cat > "$OVERRIDE_FILE" <<EOF
[Service]
Environment="OLLAMA_MODELS=$MODELS_DIR"
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF

info "Wrote $OVERRIDE_FILE"
cat "$OVERRIDE_FILE"

# ── Step 5 — Reload and restart Ollama ───────────────────────────────────────
heading "Step 5: Reload and restart Ollama"

systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

info "Waiting for Ollama to start..."
for i in {1..15}; do
    if curl -sf http://localhost:11434 &>/dev/null; then
        break
    fi
    sleep 2
done

# ── Step 6 — Verify ───────────────────────────────────────────────────────────
heading "Step 6: Verify"

if curl -sf http://localhost:11434 &>/dev/null; then
    info "Ollama is reachable at http://localhost:11434"
else
    die "Ollama is not responding at http://localhost:11434 — check: journalctl -u ollama -n 50"
fi

LIVE_MODELS_DIR=$(systemctl show ollama --property=Environment | grep OLLAMA_MODELS | grep -o 'OLLAMA_MODELS=[^ ]*' | cut -d= -f2 || echo "")
if [[ "$LIVE_MODELS_DIR" == "$MODELS_DIR" ]]; then
    info "OLLAMA_MODELS correctly set to: $MODELS_DIR"
else
    warn "OLLAMA_MODELS in live service shows: '$LIVE_MODELS_DIR' (expected '$MODELS_DIR')"
    warn "Run 'systemctl show ollama --property=Environment' to inspect."
fi

echo ""
info "Installation complete."
info "Models will be stored at: $MODELS_DIR"
info "Next step: bash scripts/download-models.sh"
