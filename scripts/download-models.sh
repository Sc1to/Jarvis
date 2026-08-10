#!/usr/bin/env bash
# download-models.sh — Download required Ollama models
#
# Purpose: Pull all three models needed by the platform.
#          Run after install-ollama.sh. Downloads are large — expect several hours on first run.
#
# What this script does (to be implemented in Phase 2 — Ollama & Model Backend):
#   1. Pull qwen2.5:14b          — conversational, RE-agent, routing (~8GB)
#   2. Pull qwen2.5-coder:32b   — specialist agents, coding tasks (~19GB)
#   3. Pull qwen2.5:72b-instruct-q4_K_M — Conductor, complex reasoning (~43GB)
#   Reports download progress and confirms each model is available after download.
#
# Usage: bash scripts/download-models.sh
#
# See BUILD_SEQUENCE.md Phase 2.1 for the implementation prompt.

echo "download-models.sh is not yet implemented. See BUILD_SEQUENCE.md Phase 2."
exit 1
