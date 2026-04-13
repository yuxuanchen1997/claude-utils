#!/usr/bin/env bash
# Claude Code Stop hook: auto-convert session to Codex format
# Receives JSON on stdin with session_id

set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))" 2>/dev/null || true)

if [ -z "$SESSION_ID" ]; then
    exit 0
fi

# Run conversion in background (no flags needed - defaults to syncing)
nohup python3 ~/.local/bin/claude-to-codex.py "$SESSION_ID" > /tmp/claude-to-codex-hook.log 2>&1 &
