#!/usr/bin/env bash
# Install claude-utils: set up symlinks and hooks for both Claude Code and Codex
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== claude-utils installer ==="

# 1. Symlinks
echo ""
echo "Creating symlinks in ~/.local/bin/ ..."
mkdir -p ~/.local/bin
ln -sf "$SCRIPT_DIR/claude-to-codex.py" ~/.local/bin/claude-to-codex.py
ln -sf "$SCRIPT_DIR/codex-to-claude.py" ~/.local/bin/codex-to-claude.py
ln -sf "$SCRIPT_DIR/claude-stop-hook.sh" ~/.local/bin/claude-stop-hook.sh
ln -sf "$SCRIPT_DIR/codex-stop-hook.sh" ~/.local/bin/codex-stop-hook.sh
echo "  ✓ Symlinks created"

# 2. Claude Code Stop hook
echo ""
echo "Installing Claude Code Stop hook ..."
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

if [ ! -f "$CLAUDE_SETTINGS" ]; then
    cat > "$CLAUDE_SETTINGS" << 'SETTINGS_EOF'
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.local/bin/claude-stop-hook.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF
    echo "  ✓ Created $CLAUDE_SETTINGS with Stop hook"
else
    if grep -q "claude-stop-hook" "$CLAUDE_SETTINGS" 2>/dev/null; then
        echo "  ✓ Stop hook already present in $CLAUDE_SETTINGS"
    else
        python3 -c "
import json
with open('$CLAUDE_SETTINGS', 'r') as f:
    settings = json.load(f)

hook_entry = {
    'type': 'command',
    'command': 'bash ~/.local/bin/claude-stop-hook.sh',
    'timeout': 10
}

if 'hooks' not in settings:
    settings['hooks'] = {}
if 'Stop' not in settings['hooks']:
    settings['hooks']['Stop'] = [{'hooks': [hook_entry]}]
else:
    if isinstance(settings['hooks']['Stop'], list) and len(settings['hooks']['Stop']) > 0:
        if 'hooks' in settings['hooks']['Stop'][0]:
            settings['hooks']['Stop'][0]['hooks'].append(hook_entry)
        else:
            settings['hooks']['Stop'][0]['hooks'] = [hook_entry]
    else:
        settings['hooks']['Stop'] = [{'hooks': [hook_entry]}]

with open('$CLAUDE_SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
print('  ✓ Added Stop hook to $CLAUDE_SETTINGS')
"
    fi
fi

# 3. Codex Stop hook
echo ""
echo "Installing Codex Stop hook ..."
mkdir -p "$HOME/.codex"

# Enable hooks feature flag in config.toml
CODEX_CONFIG="$HOME/.codex/config.toml"
if [ -f "$CODEX_CONFIG" ]; then
    if grep -q "codex_hooks" "$CODEX_CONFIG" 2>/dev/null; then
        echo "  ✓ Hooks feature flag already present in $CODEX_CONFIG"
    else
        # Append or create [features] section
        if grep -q '\[features\]' "$CODEX_CONFIG" 2>/dev/null; then
            # Insert after [features] line
            sed -i '/\[features\]/a codex_hooks = true' "$CODEX_CONFIG"
        else
            echo -e '\n[features]\ncodex_hooks = true' >> "$CODEX_CONFIG"
        fi
        echo "  ✓ Added codex_hooks feature flag to $CODEX_CONFIG"
    fi
else
    mkdir -p "$(dirname "$CODEX_CONFIG")"
    cat > "$CODEX_CONFIG" << 'CONFIG_EOF'
[features]
codex_hooks = true
CONFIG_EOF
    echo "  ✓ Created $CODEX_CONFIG with codex_hooks feature flag"
fi

# Write hooks.json
CODEX_HOOKS="$HOME/.codex/hooks.json"
if [ -f "$CODEX_HOOKS" ]; then
    if grep -q "codex-stop-hook" "$CODEX_HOOKS" 2>/dev/null; then
        echo "  ✓ Stop hook already present in $CODEX_HOOKS"
    else
        python3 -c "
import json
with open('$CODEX_HOOKS', 'r') as f:
    hooks = json.load(f)

hook_entry = {
    'type': 'command',
    'command': 'bash ~/.local/bin/codex-stop-hook.sh',
    'timeout': 10
}

if 'hooks' not in hooks:
    hooks['hooks'] = {}
if 'Stop' not in hooks['hooks']:
    hooks['hooks']['Stop'] = [{'hooks': [hook_entry]}]
else:
    if isinstance(hooks['hooks']['Stop'], list) and len(hooks['hooks']['Stop']) > 0:
        if 'hooks' in hooks['hooks']['Stop'][0]:
            hooks['hooks']['Stop'][0]['hooks'].append(hook_entry)
        else:
            hooks['hooks']['Stop'][0]['hooks'] = [hook_entry]
    else:
        hooks['hooks']['Stop'] = [{'hooks': [hook_entry]}]

with open('$CODEX_HOOKS', 'w') as f:
    json.dump(hooks, f, indent=2)
    f.write('\n')
print('  ✓ Added Stop hook to $CODEX_HOOKS')
"
    fi
else
    cat > "$CODEX_HOOKS" << 'HOOKS_EOF'
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.local/bin/codex-stop-hook.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
HOOKS_EOF
    echo "  ✓ Created $CODEX_HOOKS with Stop hook"
fi

echo ""
echo "=== Done! ==="
echo ""
echo "Both Claude Code and Codex will now auto-sync sessions on exit."
