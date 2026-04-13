# claude-utils

Bidirectional chat history sync between **Claude Code** and **Codex**.

Convert sessions from either tool into the other's format, so you can resume a conversation started in one tool from the other.

## What it does

- **`claude-to-codex.py`** — Converts a Claude Code session into Codex's rollout JSONL format and writes it to `~/.codex/sessions/`.
- **`codex-to-claude.py`** — Converts a Codex session into Claude Code's JSONL format and writes it to `~/.claude/projects/<path>/`.

Both scripts overwrite existing sessions by default (since you want the latest state to win).

## Manual usage

```bash
# Sync a Claude session to Codex
python3 ~/claude-utils/claude-to-codex.py <session-id>

# Sync a Codex session to Claude
python3 ~/claude-utils/codex-to-claude.py <session-id>

# Export to /tmp instead (for inspection)
python3 ~/claude-utils/claude-to-codex.py <session-id> --export
python3 ~/claude-utils/codex-to-claude.py <session-id> --export
```

After syncing, you can resume in the other tool:

```bash
codex --resume <session-id>
claude --resume <session-id>
```

## Automatic sync

### `claude-stop-hook.sh` — Claude Code end-of-session hook

This script is wired into Claude Code's `Stop` hook in `~/.claude/settings.json`. When a Claude Code session ends, Claude sends a JSON payload on stdin containing `{"session_id": "..."}`. The hook extracts the session ID and runs `claude-to-codex.py` in the background.

**Setup** — add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "bash ~/claude-utils/claude-stop-hook.sh"
      }
    ]
  }
}
```

No action needed from you — every time you finish a Claude Code conversation, it automatically appears in Codex.

### `codex-with-sync` — Codex wrapper script

Codex doesn't have an equivalent hook system, so instead this is a wrapper script you use *instead* of calling `codex` directly. It:

1. Runs `codex` with all your arguments as-is
2. After codex exits, reads the latest session ID from `~/.codex/history.jsonl`
3. Runs `codex-to-claude.py` to convert it

**Setup** — add an alias in your shell config:

```bash
alias codex='bash ~/claude-utils/codex-with-sync'
```

Now every `codex` invocation automatically syncs back to Claude Code when you exit.

## How it works

### Claude Code session format

Claude Code stores sessions as JSONL in `~/.claude/projects/<dir-path>/`. Each line is a JSON object with a `type` field. The conversation is a tree structure linked by `parentUuid`. Messages contain content blocks (text, tool_use, tool_result) in the `message.content` array.

### Codex session format

Codex stores sessions as JSONL in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Each line has a `type` like `"message"`, `"function_call"`, `"function_call_output"`. User and assistant messages alternate with tool calls interleaved.

### Conversion logic

- **Claude → Codex**: Walks the `parentUuid` tree to extract the linear conversation, maps Claude's `tool_use`/`tool_result` to Codex's `function_call`/`function_call_output`, filters out internal context (AGENTS.md, environment blocks).
- **Codex → Claude**: Reads the rollout JSONL, reconstructs conversation turns, maps tool names (`exec_command` → `Bash`, `apply_patch` → `Write`, etc.), builds proper `parentUuid` chains, adds `file-history-snapshot` entries, and preserves all required metadata.

## Symlinks

For convenience, the scripts are symlinked into `~/.local/bin/`:

```bash
ln -sf ~/claude-utils/claude-to-codex.py ~/.local/bin/claude-to-codex.py
ln -sf ~/claude-utils/codex-to-claude.py ~/.local/bin/codex-to-claude.py
ln -sf ~/claude-utils/claude-stop-hook.sh ~/.local/bin/claude-stop-hook.sh
ln -sf ~/claude-utils/codex-with-sync ~/.local/bin/codex-with-sync
```

## Installation

Run the installer:

```bash
bash ~/claude-utils/install.sh
```

This will:

1. **Create symlinks** from `~/.local/bin/` to the scripts in `~/claude-utils/`
2. **Install the Claude Code Stop hook** into `~/.claude/settings.json` (skips if already present)
3. **Print a reminder** to add the codex alias to your shell config

For the codex auto-sync alias, add to `~/.bashrc` or `~/.zshrc`:

```bash
alias codex='bash ~/claude-utils/codex-with-sync'
```
