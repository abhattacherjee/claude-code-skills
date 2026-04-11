#!/usr/bin/env bash
# verify-hooks.sh — manual diagnostic for obsidian-brain SessionStart hook.
#
# Simulates a SessionStart hook invocation with a dummy session_id and
# verifies that the bootstrap file and hook log were written. Does NOT
# need a running Claude Code session.
#
# Usage: ./scripts/verify-hooks.sh
# Exit:  0 on success, non-zero on any failure.
#
# Note on the bootstrap check:
#   After commit f26d93c, only the SessionStart hook writes the
#   bootstrap file. The previous slow-path "refresh" behavior in
#   _get_session_id_fast() was removed because it could clobber the
#   hook's authoritative write within the same hook invocation when
#   Claude Code fires SessionStart before flushing the new session's
#   JSONL to disk. This script verifies the hook fired via the
#   append-only hook log at ~/.claude/obsidian-brain-hook.log — that
#   is the authoritative signal. The bootstrap file check is advisory
#   and should now also show the dummy sid (no racing slow path
#   overwriting it).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO_ROOT/hooks/obsidian_session_hint.py"
HOOKS_DIR="$REPO_ROOT/hooks"
# Derive PROJECT via the same helper the hook uses, so the bootstrap path
# agrees with the hook regardless of how get_project_name() evolves.
PROJECT="$(python3 -c "
import sys
sys.path.insert(0, sys.argv[1])
from obsidian_utils import get_project_name
print(get_project_name(sys.argv[2]))
" "$HOOKS_DIR" "$(pwd)")"
DUMMY_SID="verify-hooks-$(date +%s)"
BOOTSTRAP="/tmp/.obsidian-brain-sid-$PROJECT"
LOG="$HOME/.claude/obsidian-brain-hook.log"

echo "→ Simulating SessionStart hook for project=$PROJECT"
# Build the JSON payload via json.dumps so a cwd containing quotes,
# backslashes, or newlines cannot produce an invalid-JSON stdin that
# the hook would reject as malformed.
python3 -c 'import json,sys; print(json.dumps({"cwd": sys.argv[1], "session_id": sys.argv[2]}))' \
    "$(pwd)" "$DUMMY_SID" \
    | python3 "$HOOK" >/dev/null

# Log is append-only and the authoritative proof the hook fired.
# The dummy sid is truncated to 8 chars in the log ("verify-h").
if ! tail -5 "$LOG" 2>/dev/null | grep -q "sid=verify-h"; then
    echo "[FAIL] hook log does not contain a verify-hooks entry" >&2
    echo "  log path: $LOG" >&2
    echo "  last 5 lines:" >&2
    tail -5 "$LOG" >&2 || true
    exit 1
fi

if ! tail -5 "$LOG" 2>/dev/null | grep -q "bootstrap_updated=true"; then
    echo "[FAIL] hook log does not show bootstrap_updated=true" >&2
    echo "  log path: $LOG" >&2
    tail -5 "$LOG" >&2 || true
    exit 1
fi

# Advisory: the bootstrap file should exist. After commit f26d93c, the
# slow path no longer writes the bootstrap, so this check should
# consistently match the dummy sid we just wrote (no racing overwrite).
if [[ ! -f "$BOOTSTRAP" ]]; then
    echo "[WARN] bootstrap file $BOOTSTRAP does not exist"
    echo "  the hook log shows bootstrap_updated=true, so this is unusual"
fi

echo "[OK] Hook fired, bootstrap written, log updated."
echo "  bootstrap: $BOOTSTRAP"
echo "  log:       $LOG"
