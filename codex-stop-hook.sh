#!/usr/bin/env bash
# Codex Stop hook: auto-convert session to Claude Code format
# Receives JSON on stdin with session_id and transcript_path

set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))" 2>/dev/null || true)

if [ -z "$SESSION_ID" ]; then
    exit 0
fi

# Run conversion in background
nohup python3 ~/claude-utils/codex-to-claude.py "$SESSION_ID" > /tmp/codex-to-claude-hook.log 2>&1 &
