#!/usr/bin/env bash
# setup.sh — Full platform setup script
#
# Purpose: Install and configure every platform dependency on a fresh Ubuntu 24.04 LTS
#          installation. Run once on the mini PC after Ubuntu is installed.
#
# What this script does (to be implemented in Phase 12 — Documentation):
#   1. Install system dependencies: git, python3.12, python3-pip, python3-venv, nodejs, npm
#   2. Install Tailscale and prompt for authentication
#   3. Install Caddy and deploy base Caddyfile
#   4. Install Ollama and configure environment variables
#   5. Download required models (qwen2.5:14b, qwen2.5-coder:32b, qwen2.5:72b-instruct-q4_K_M)
#   6. Create directory structure at /opt/platform/
#   7. Deploy all platform services and their dependencies
#   8. Install and enable all systemd unit files
#   9. Run validate-platform.py to confirm everything is working
#
# Usage: bash scripts/setup.sh
#
# See BUILD_SEQUENCE.md Phase 12 for the implementation prompt.

echo "setup.sh is not yet implemented. See BUILD_SEQUENCE.md Phase 12."
exit 1
