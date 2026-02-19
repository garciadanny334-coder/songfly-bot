#!/bin/bash
# session-start.sh — Songfly Bot session startup hook
# Installs Python + Playwright dependencies in Claude Code on the web.
set -euo pipefail

# Only run in remote (Claude Code on the web) environments.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo "[session-start] Installing Python dependencies…"
pip install -r "$CLAUDE_PROJECT_DIR/requirements.txt" --quiet

echo "[session-start] Installing Playwright Chromium browser…"
playwright install chromium --with-deps

echo "[session-start] Environment ready."
