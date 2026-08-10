#!/usr/bin/env bash
# install-ollama.sh — Ollama installation and configuration script
#
# Purpose: Install Ollama on the mini PC and configure it for platform use.
#
# What this script does (to be implemented in Phase 2 — Ollama & Model Backend):
#   1. Install Ollama via the official install script (https://ollama.com/install.sh)
#   2. Set required environment variables in systemd override:
#      - OLLAMA_HOST=0.0.0.0 (accept connections from all services)
#      - OLLAMA_MAX_LOADED_MODELS=3 (memory management)
#      - OLLAMA_NUM_PARALLEL=1 (one request at a time per model)
#      Written to /etc/systemd/system/ollama.service.d/override.conf
#   3. Reload and restart the Ollama systemd service
#   4. Verify Ollama is running by hitting http://localhost:11434
#
# Usage: bash scripts/install-ollama.sh
#
# See BUILD_SEQUENCE.md Phase 2.1 for the implementation prompt.

echo "install-ollama.sh is not yet implemented. See BUILD_SEQUENCE.md Phase 2."
exit 1
