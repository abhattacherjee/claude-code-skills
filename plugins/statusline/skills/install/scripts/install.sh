#!/usr/bin/env bash
# Install the 3-tier adaptive statusline for Claude Code.
# Copies references/statusline-command.sh to ~/.claude/statusline-command.sh and points
# statusLine in ~/.claude/settings.json at it.
#
# Exit codes: 0 installed, 1 a write failed (nothing half-done is left), 2 bad input
# (unknown flag, or settings.json is not one JSON object), 3 refused: the existing
# statusline script was not written by this plugin (re-run with --force to replace it
# after a backup).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../../lib/write-statusline.sh
. "$SCRIPT_DIR/../../../lib/write-statusline.sh"

STATUSLINE_SRC="$SCRIPT_DIR/../references/statusline-command.sh"
STATUSLINE_DEST="$HOME/.claude/statusline-command.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"
COMMAND='bash ~/.claude/statusline-command.sh'

usage() {
  cat <<'USAGE'
Usage: install.sh [--force]

Installs the 3-tier adaptive statusline to ~/.claude/statusline-command.sh and sets
statusLine in ~/.claude/settings.json.

  --force   Replace an existing statusline script that this plugin did not write.
            It is backed up to statusline-command.sh.bak-<UTC time> first.
  --help    Show this help.

Exit codes: 0 installed, 1 write failed, 2 bad input, 3 refused (use --force).
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
update_settings "$SETTINGS_FILE" "$COMMAND" || exit $?

echo ""
echo "Statusline installed. Restart Claude Code to see it."
