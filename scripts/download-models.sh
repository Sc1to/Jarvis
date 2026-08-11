#!/usr/bin/env bash
# download-models.sh — Pull all Ollama models required by the platform.
#
# Usage:
#   bash scripts/download-models.sh
#
# Run after install-ollama.sh. Downloads are large (~70 GB total) — expect
# several hours on first run depending on connection speed.
#
# Models pulled:
#   qwen2.5:14b                    — RE-agent, conversational, routing    (~8 GB)
#   qwen2.5-coder:32b              — All specialist agents, coding tasks  (~19 GB)
#   qwen2.5:72b-instruct-q4_K_M   — Conductor, complex reasoning         (~43 GB)

set -euo pipefail

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

# ── Models to pull ────────────────────────────────────────────────────────────
declare -A MODEL_DESCRIPTIONS=(
    ["qwen2.5:14b"]="RE-agent, conversational, routing (~8 GB)"
    ["qwen2.5-coder:32b"]="Specialist agents, coding tasks (~19 GB)"
    ["qwen2.5:72b-instruct-q4_K_M"]="Conductor, complex reasoning (~43 GB)"
)
# Ordered — smallest first so you can test before committing to the large pull
MODELS=(
    "qwen2.5:14b"
    "qwen2.5-coder:32b"
    "qwen2.5:72b-instruct-q4_K_M"
)

# ── Pre-flight checks ─────────────────────────────────────────────────────────
command -v ollama &>/dev/null || die "ollama is not installed. Run scripts/install-ollama.sh first."

if ! curl -sf http://localhost:11434 &>/dev/null; then
    die "Ollama is not running. Start it with: sudo systemctl start ollama"
fi

MODELS_DIR=$(systemctl show ollama --property=Environment 2>/dev/null \
    | grep -o 'OLLAMA_MODELS=[^ ]*' \
    | cut -d= -f2 || echo "")

heading "Model storage"
if [[ -n "$MODELS_DIR" ]]; then
    info "OLLAMA_MODELS = $MODELS_DIR"
    AVAIL=$(df -BG "$MODELS_DIR" 2>/dev/null | awk 'NR==2{print $4}' || echo "unknown")
    info "Available space: $AVAIL"
    if [[ "$AVAIL" != "unknown" ]]; then
        AVAIL_NUM=${AVAIL%G}
        if (( AVAIL_NUM < 75 )); then
            warn "Less than 75 GB available. You need ~70 GB for all three models."
            warn "Free up space or pull models individually."
        fi
    fi
else
    warn "OLLAMA_MODELS not set in systemd — Ollama will use its default path (~/.ollama/models)."
    warn "If you want models on a dedicated drive, run install-ollama.sh first."
fi

# ── Pull models ───────────────────────────────────────────────────────────────
FAILED=()
SKIPPED=()
PULLED=()

for MODEL in "${MODELS[@]}"; do
    heading "Pulling: $MODEL"
    info "${MODEL_DESCRIPTIONS[$MODEL]}"

    # Check if already present
    if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
        info "Already downloaded — skipping."
        SKIPPED+=("$MODEL")
        continue
    fi

    info "Starting pull... (this may take a long time)"
    START=$(date +%s)

    if ollama pull "$MODEL"; then
        END=$(date +%s)
        ELAPSED=$(( END - START ))
        MINS=$(( ELAPSED / 60 ))
        SECS=$(( ELAPSED % 60 ))
        info "Done in ${MINS}m ${SECS}s."
        PULLED+=("$MODEL")
    else
        error "Failed to pull $MODEL."
        FAILED+=("$MODEL")
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
heading "Summary"

echo ""
echo "Available models after run:"
ollama list

echo ""
if (( ${#PULLED[@]} > 0 )); then
    info "Pulled:"
    for m in "${PULLED[@]}"; do info "  $m"; done
fi
if (( ${#SKIPPED[@]} > 0 )); then
    info "Already present (skipped):"
    for m in "${SKIPPED[@]}"; do info "  $m"; done
fi
if (( ${#FAILED[@]} > 0 )); then
    error "Failed:"
    for m in "${FAILED[@]}"; do error "  $m"; done
    echo ""
    die "One or more models failed to pull. Check your connection and retry."
fi

echo ""
info "All models ready. Platform is good to go."
