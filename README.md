# claude-utils

Bidirectional chat history sync between **Claude Code** and **Codex**.

Convert sessions from either tool into the other's format, so you can resume a conversation started in one tool from the other. Both hooks fire automatically on session exit — no manual steps needed.

## What it does

- **`claude-to-codex.py`** — Converts a Claude Code session into Codex's rollout JSONL format and writes it to `~/.codex/sessions/`.
- **`codex-to-claude.py`** — Converts a Codex session into Claude Code's JSONL format and writes it to `~/.claude/projects/<path>/`.

Both scripts overwrite existing sessions by default (latest state wins).

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

Wired into Claude Code's `Stop` hook in `~/.claude/settings.json`. When a Claude Code session ends, Claude sends a JSON payload on stdin containing `{"session_id": "..."}`. The hook extracts the session ID and runs `claude-to-codex.py` in the background.

### `codex-stop-hook.sh` — Codex end-of-session hook

Wired into Codex's `Stop` hook in `~/.codex/hooks.json`. When a Codex session ends, Codex sends a JSON payload on stdin containing `{"session_id": "...", "transcript_path": "..."}`. The hook extracts the session ID and runs `codex-to-claude.py` in the background.

Requires the `codex_hooks` feature flag in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

## Installation

Run the installer:

```bash
bash ~/claude-utils/install.sh
```

This will:

1. **Create symlinks** from `~/.local/bin/` to the scripts in `~/claude-utils/`
2. **Install the Claude Code Stop hook** into `~/.claude/settings.json` (skips if already present)
3. **Install the Codex Stop hook** into `~/.codex/hooks.json` and enable the `codex_hooks` feature flag in `~/.codex/config.toml`

After installation, both tools will automatically sync sessions to the other on exit. No further action needed.

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
ln -sf ~/claude-utils/codex-stop-hook.sh ~/.local/bin/codex-stop-hook.sh
```
