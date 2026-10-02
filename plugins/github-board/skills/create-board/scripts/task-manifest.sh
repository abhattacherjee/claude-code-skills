#!/usr/bin/env bash
# Emit task checklists for create-board workflows as JSON arrays.
# Each task has subject, activeForm, description fields suitable for TaskCreate.

set -eu

usage() {
  cat <<EOF
Usage: $(basename "$0") <workflow>

Workflows:
  full       Full board replication onto a new repo (default)
  audit      Report-only drift check of existing board(s) vs the template

Flags:
  --list     List workflow names (one per line)
  --help|-h  Show this help
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --list) printf 'full\naudit\n'; exit 0 ;;
esac

WORKFLOW="${1:-full}"

case "$WORKFLOW" in
  full)
    cat <<'JSON'
[
  {
    "subject": "Inspect template board",
    "activeForm": "Inspecting template board",
    "description": "Snapshot the source ProjectV2 fields, views, and workflows to a mktemp JSON file, whose path the script prints"
  },
  {
    "subject": "Copy template to new project",
    "activeForm": "Copying template to new project",
    "description": "Run `gh project copy` to clone fields, Status options, and the Kanban view (including columns and swimlanes, which no mutation can set) onto the target owner"
  },
  {
    "subject": "Link new project to target repo",
    "activeForm": "Linking new project to target repo",
    "description": "Call linkProjectV2ToRepository so issues/PRs from the target repo can be added"
  },
  {
    "subject": "Check Auto-add to project",
    "activeForm": "Checking the Auto-add workflow",
    "description": "gh project copy carries no workflows. The six on a new board are GitHub defaults. Only \"Auto-add to project\" is repo-scoped and missing, and no mutation can create it — emit the UI URL and the exact filter."
  },
  {
    "subject": "Backfill existing issues",
    "activeForm": "Backfilling existing issues",
    "description": "Add every existing open issue from the target repo to the new board via `gh project item-add`. Auto-add workflows only fire on new events, not retroactively."
  },
  {
    "subject": "Verify new board matches template",
    "activeForm": "Verifying board parity",
    "description": "Diff fields, Status options, view shape (layout/filter/columns/swimlanes) and workflows against the snapshot. Exit 0 = clean, 3 = structurally clean but Auto-add still needs enabling, 1 = drift."
  }
]
JSON
    ;;
  audit)
    cat <<'JSON'
[
  {
    "subject": "Snapshot the template board",
    "activeForm": "Snapshotting the template board",
    "description": "Capture the template's fields, Status options and view shape so boards can be diffed against it"
  },
  {
    "subject": "Audit board(s) against the template",
    "activeForm": "Auditing boards against the template",
    "description": "Run scripts/audit-board.sh (--number <n> or --all). Report-only: it never writes to a board."
  },
  {
    "subject": "Report drift and remediation",
    "activeForm": "Reporting drift and remediation",
    "description": "List per-board drift. Enabling Auto-add is UI-only; Status options can only be fixed by sending each option's existing id, or item values are cleared and workflows silently disabled."
  }
]
JSON
    ;;
  *)
    echo "Unknown workflow: $WORKFLOW" >&2
    usage >&2
    exit 2
    ;;
esac
