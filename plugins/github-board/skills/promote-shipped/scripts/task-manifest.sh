#!/usr/bin/env bash
# task-manifest.sh — Emit task definitions for /github-board:promote-shipped workflows.
#
# Exit codes: 0=ok (workflow emitted, or --list/--help)
#             1=unknown or missing workflow name
# Deliberately 1 rather than the 2 its siblings use for usage errors: this script
# takes no flags and makes no API calls, so it has no auth/API codes to leave room
# for, and 1 is what a caller checking `if ! task-manifest.sh X` already expects.

set -eu

case "${1:-}" in
  full-run)
    cat <<'JSON'
[
  {"subject":"Discover project boards","activeForm":"Discovering project boards","description":"Run discover-boards.sh OWNER REPO --json. Parse the boards array. If empty, exit (no-op). If >1, ask the user to pick one."},
  {"subject":"Inventory selected board","activeForm":"Inventorying board","description":"Run inventory-board.sh --board-id <id> > /tmp/release-board-inv.json. Verifies a Status field with a Done-like option exists; bails out otherwise."},
  {"subject":"Find promotable candidates","activeForm":"Filtering promotable candidates","description":"Run find-promotable.sh /tmp/release-board-inv.json > /tmp/release-board-cand.json. Filters to closed-issue + merged-PR (or merged PR-typed item) + status != Done."},
  {"subject":"Preview changes","activeForm":"Previewing changes","description":"Run apply-promotions.sh /tmp/release-board-cand.json --dry-run. Shows the per-item before/after for the user to inspect."},
  {"subject":"Confirm and apply","activeForm":"Applying promotions","description":"Ask the user to confirm. On yes, run apply-promotions.sh /tmp/release-board-cand.json --apply. Report ok/fail counts and any errors."},
  {"subject":"Summary report","activeForm":"Generating summary","description":"Print a final summary: project, items moved, items skipped, links to the promoted issues for spot-check."}
]
JSON
    ;;
  --list)
    echo "full-run"
    ;;
  -h|--help)
    cat <<EOF
Usage: task-manifest.sh <workflow>

Workflows:
  full-run     Discover → inventory → filter → preview → apply → report (6 tasks)

Use --list for machine-readable workflow names.
EOF
    ;;
  *)
    echo "Error: unknown workflow '${1:-}'. Use --list or --help." >&2
    exit 1
    ;;
esac
