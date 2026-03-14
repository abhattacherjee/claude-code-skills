#!/bin/bash
# Install the custom statusline for Claude Code
# Copies the script and updates settings.json

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATUSLINE_SRC="$SCRIPT_DIR/../references/statusline-command.sh"
STATUSLINE_DEST="$HOME/.claude/statusline-command.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"

# Ensure ~/.claude exists
mkdir -p "$HOME/.claude"

# Copy the statusline script
cp "$STATUSLINE_SRC" "$STATUSLINE_DEST"
chmod +x "$STATUSLINE_DEST"
echo "Copied statusline script to $STATUSLINE_DEST"

# Update settings.json to add/update the statusLine entry
if [ -f "$SETTINGS_FILE" ]; then
  # Check if statusLine already exists
  if jq -e '.statusLine' "$SETTINGS_FILE" >/dev/null 2>&1; then
    # Update existing
    jq '.statusLine = {"type": "command", "command": "bash ~/.claude/statusline-command.sh"}' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo "Updated statusLine in $SETTINGS_FILE"
  else
    # Add new
    jq '. + {"statusLine": {"type": "command", "command": "bash ~/.claude/statusline-command.sh"}}' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo "Added statusLine to $SETTINGS_FILE"
  fi
else
  # Create minimal settings.json
  cat > "$SETTINGS_FILE" <<'SETTINGS'
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
SETTINGS
  echo "Created $SETTINGS_FILE with statusLine"
fi

echo ""
echo "Custom statusline installed! Restart Claude Code to see it."
echo ""
echo "Features:"
echo "  📁 Project directory"
echo "  🌿 Git branch with sync status"
echo "  🧠 Context usage with color-coded progress bar"
echo "  4-tier adaptive layout (ultra-narrow → wide)"
