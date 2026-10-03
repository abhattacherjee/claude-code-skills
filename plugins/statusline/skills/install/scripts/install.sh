#!/usr/bin/env bash
# Install the 3-tier adaptive statusline for Claude Code.
# Copies references/statusline-command.sh to ~/.claude/statusline-command.sh and points
# statusLine in ~/.claude/settings.json at it.
#
# Exit codes: 0 installed, 1 failed (a write failed, jq is missing, or settings.json cannot
# be read; a file that was not written is unchanged), 2 bad input
# (unknown flag, or settings.json is not one JSON object), 3 refused: the existing
# statusline script was not written by this plugin (re-run with --force to replace it
# after a backup).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../../lib/write-statusline.sh
. "$SCRIPT_DIR/../../../lib/write-statusline.sh"

STATUSLINE_SRC="$SCRIPT_DIR/../references/statusline-command.sh"
# Claude Code reads its settings from $CLAUDE_CONFIG_DIR when that is set.
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CFG="${CFG%/}"
STATUSLINE_DEST="$CFG/statusline-command.sh"
SETTINGS_FILE="$CFG/settings.json"
if [ "$CFG" = "$HOME/.claude" ]; then
  COMMAND='bash ~/.claude/statusline-command.sh'
else
  COMMAND="bash $(sl_shell_quote "$STATUSLINE_DEST")"
fi

usage() {
  cat <<'USAGE'
Usage: install.sh [--force]

Installs the 3-tier adaptive statusline to ~/.claude/statusline-command.sh and sets
statusLine in ~/.claude/settings.json (both in $CLAUDE_CONFIG_DIR when that is set).

  --force   Replace an existing statusline script that this plugin did not write.
            It is backed up to statusline-command.sh.bak-<UTC time> first.
  --help    Show this help.

Exit codes: 0 installed, 1 failed, 2 bad input, 3 refused (use --force).
USAGE
}

FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Check settings.json before touching anything, so a bad file never leaves a half install.
check_settings "$SETTINGS_FILE" || exit $?

write_statusline "$STATUSLINE_SRC" "$STATUSLINE_DEST" "$FORCE" || exit $?
rc=0; update_settings "$SETTINGS_FILE" "$COMMAND" || rc=$?
if [ $rc -ne 0 ]; then
  echo "Result: statusline script written; settings.json unchanged. Fix the error above and re-run." >&2
  exit $rc
fi

echo ""
echo "Statusline installed. Restart Claude Code to see it."
