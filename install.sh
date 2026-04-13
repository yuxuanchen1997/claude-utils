#!/usr/bin/env bash
# Install claude-utils: set up symlinks, Claude Code hook, and codex alias
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
ln -sf "$SCRIPT_DIR/codex-with-sync" ~/.local/bin/codex-with-sync
echo "  ✓ Symlinks created"

# 2. Claude Code Stop hook
echo ""
echo "Installing Claude Code Stop hook ..."
SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

if [ ! -f "$SETTINGS" ]; then
    # No settings file — create one
    cat > "$SETTINGS" << 'SETTINGS_EOF'
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
    echo "  ✓ Created $SETTINGS with Stop hook"
else
    # Check if hook already exists
    if grep -q "claude-stop-hook" "$SETTINGS" 2>/dev/null; then
        echo "  ✓ Stop hook already present in $SETTINGS"
    else
        # Add hook using python (safe JSON manipulation)
        python3 -c "
import json, sys
with open('$SETTINGS', 'r') as f:
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
    # Add to existing Stop hooks
    if isinstance(settings['hooks']['Stop'], list) and len(settings['hooks']['Stop']) > 0:
        if 'hooks' in settings['hooks']['Stop'][0]:
            settings['hooks']['Stop'][0]['hooks'].append(hook_entry)
        else:
            settings['hooks']['Stop'][0]['hooks'] = [hook_entry]
    else:
        settings['hooks']['Stop'] = [{'hooks': [hook_entry]}]

with open('$SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
print('  ✓ Added Stop hook to $SETTINGS')
"
    fi
fi

# 3. Codex alias suggestion
echo ""
echo "Codex auto-sync: add this alias to your shell config (~/.bashrc, ~/.zshrc, etc.):"
echo ""
echo "    alias codex='bash ~/claude-utils/codex-with-sync'"
echo ""

echo "=== Done! ==="
