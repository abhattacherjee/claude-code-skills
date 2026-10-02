#!/usr/bin/env bash
# Phase 5: diff a newly-created ProjectV2 against the template snapshot.
#
# What this checks, and why it is shaped this way (all measured 2026-09-16 on
# gh 2.96.0 — see SKILL.md "Measured capability model"):
#
#   * `gh project copy` carries fields, single-select options, and views —
#     including board columns (verticalGroupByFields) and swimlanes
#     (groupByFields). Neither can be set by any mutation, so proving the copy
#     carried them is the only assurance available. That is checked here.
#
#   * `gh project copy` carries NO workflows. The six that appear on a copy
#     ("Item added to project", "Item closed", "Pull request merged",
#     "Pull request linked to issue", "Auto-close issue", "Auto-add sub-issues
#     to project") are the defaults GitHub enables on EVERY new project,
#     including a bare `gh project create`. They are project-scoped and carry
#     no repo filter, so there is nothing to rewrite on them.
#
#   * "Auto-add to project" is the sole repo-scoped workflow. It is not a
#     default, it never survives a copy, and no mutation can create or enable
#     it. It is reported as a required manual step separately from structural
#     parity, so a structurally perfect board is not branded a failure for a
#     gap the API cannot close.

set -euo pipefail

# The one workflow that can never be copied or created via the API.
readonly UNCOPYABLE_WORKFLOW="Auto-add to project"

SNAPSHOT=""
NEW_OWNER=""
NEW_NUMBER=""
TARGET_OWNER=""
TARGET_REPO=""
PRINT_REMEDIATION=false

usage() {
  cat <<EOF
Usage: $(basename "$0") --snapshot <path> --new-owner <login> --new-number <n> \\
         [--target-owner <login>] [--target-repo <name>]
       $(basename "$0") --print-remediation --new-owner <login> --new-number <n> \\
         [--target-owner <login>] [--target-repo <name>]

Re-introspects the new project and diffs it against the template snapshot.

Normal mode emits a JSON parity report:
  {
    "fields":    { "template": N, "new": N, "match": bool },
    "status":    { "options_template": [...], "options_new": [...], "match": bool },
    "views":     { "template": [...], "new": [...], "match": bool },
    "workflows": { "expected": [...], "enabled_new": [...], "missing": [...], "match": bool },
    "auto_add":  { "required": true, "present": bool, "filter": "...", "ui_url": "..." },
    "structural_pass": bool,
    "pass": bool
  }

"views" compares each view's name, layout, filter, columns
(verticalGroupByFields) and swimlanes (groupByFields) — not just the count. A
count-only check cannot fail usefully: a brand-new unconfigured project also
has exactly one view.

"workflows.expected" is the template's enabled set MINUS "$UNCOPYABLE_WORKFLOW",
which no copy carries and no mutation can create. That one is reported under
"auto_add" instead.

--print-remediation mode:
  Skips the diff. Emits ONLY a Markdown checklist for the manual step, suitable
  for \`gh issue create --body-file -\`. Exits 0.

Flags:
  --snapshot <path>        Template snapshot from inspect-template.sh (normal mode).
  --new-owner <login>      Owner of the newly-created project. Required.
  --new-number <n>         Number of the newly-created project. Required.
  --target-owner <login>   Owner for the auto-add filter. Defaults to --new-owner.
  --target-repo <name>     Target repo name, used to build the auto-add filter.
  --print-remediation      Emit ONLY the Markdown checklist, exit 0.
  -h, --help               Show this help.

Exit codes:
  0  Structural parity AND "$UNCOPYABLE_WORKFLOW" already enabled
  1  Structural drift (fields, status options, views, or workflows)
  2  Bad usage, or unreadable snapshot
  3  Structural parity, but "$UNCOPYABLE_WORKFLOW" still needs enabling in the UI
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot)           SNAPSHOT="$2";          shift 2 ;;
    --new-owner)          NEW_OWNER="$2";         shift 2 ;;
    --new-number)         NEW_NUMBER="$2";        shift 2 ;;
    --target-owner)       TARGET_OWNER="$2";      shift 2 ;;
    --target-repo)        TARGET_REPO="$2";       shift 2 ;;
    --print-remediation)  PRINT_REMEDIATION=true; shift   ;;
    -h|--help)            usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Accept owner/name too (sync-workflows.sh and SKILL.md use that form);
# a bare join would print repo:owner/owner/name.
if [[ "$TARGET_REPO" == */* ]]; then
  TARGET_OWNER="${TARGET_REPO%%/*}"
  TARGET_REPO="${TARGET_REPO#*/}"
fi
TARGET_OWNER="${TARGET_OWNER:-$NEW_OWNER}"

# Orgs and users have different project URLs. Guess wrong and the operator
# lands on a 404 while being told to go fix something.
workflows_ui_url() {
  if gh api "/users/${NEW_OWNER}" --jq '.type' 2>/dev/null | grep -qx "Organization"; then
    echo "https://github.com/orgs/${NEW_OWNER}/projects/${NEW_NUMBER}/workflows"
  else
    echo "https://github.com/users/${NEW_OWNER}/projects/${NEW_NUMBER}/workflows"
  fi
}

auto_add_filter() {
  if [ -n "$TARGET_REPO" ]; then
    echo "repo:${TARGET_OWNER}/${TARGET_REPO} is:issue,pr is:open"
  else
    echo "is:issue,pr is:open"
  fi
}

print_remediation_markdown() {
  cat <<EOF
## Manual setup: enable "${UNCOPYABLE_WORKFLOW}"

\`gh project copy\` does not carry this workflow, and GitHub's public GraphQL API
has no mutation that can create or enable it (\`deleteProjectV2Workflow\` is the
only workflow mutation). It has to be enabled once, by hand.

Every other workflow on the board is a GitHub default and is already enabled —
there is nothing to change on those.

**Open**: $(workflows_ui_url)

- [ ] Enable **${UNCOPYABLE_WORKFLOW}** with filter \`$(auto_add_filter)\`
- [ ] Open a throwaway issue in the target repo and confirm it lands on the board
- [ ] Close the throwaway issue

Issues that already existed were added by the backfill phase; this workflow only
governs items created from now on.
EOF
}

if [ "$PRINT_REMEDIATION" = true ]; then
  [ -n "$NEW_OWNER" ]  || { echo "Missing --new-owner"  >&2; exit 2; }
  [ -n "$NEW_NUMBER" ] || { echo "Missing --new-number" >&2; exit 2; }
  print_remediation_markdown
  exit 0
fi

[ -n "$SNAPSHOT" ] && [ -f "$SNAPSHOT" ] || { echo "Snapshot not found: ${SNAPSHOT:-<missing --snapshot>}" >&2; exit 2; }
[ -n "$NEW_OWNER" ]  || { echo "Missing --new-owner"  >&2; exit 2; }
[ -n "$NEW_NUMBER" ] || { echo "Missing --new-number" >&2; exit 2; }

# Unguessable path, removed on exit -- a predictable name in world-writable
# /tmp can be pre-created as a symlink to redirect the write.
umask 077
NEW_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/gh-board-new.XXXXXX")"
trap 'rm -f "$NEW_SNAPSHOT"' EXIT
"$(dirname "$0")/inspect-template.sh" --owner "$NEW_OWNER" --number "$NEW_NUMBER" --out "$NEW_SNAPSHOT" >/dev/null

# `gh api graphql` exits 0 on a data:null + errors envelope, which would
# otherwise diff two nulls and report a meaningless pass.
for f in "$SNAPSHOT" "$NEW_SNAPSHOT"; do
  jq -e '(.data.user.projectV2 // .data.organization.projectV2) | .id' "$f" >/dev/null 2>&1 || {
    echo "Invalid snapshot at $f — missing projectV2 data (likely auth or NOT_FOUND)" >&2
    exit 2
  }
done

REPORT=$(jq -n \
  --slurpfile t "$SNAPSHOT" \
  --slurpfile n "$NEW_SNAPSHOT" \
  --arg uncopyable "$UNCOPYABLE_WORKFLOW" \
  --arg ui_url "$(workflows_ui_url)" \
  --arg filter "$(auto_add_filter)" '
def proj($x): ($x[0].data.user.projectV2 // $x[0].data.organization.projectV2);
def status_options($p): [
  $p.fields.nodes[] | select(.name == "Status") | .options[]? | {name, color}
];
# Compare the properties that actually define the board: layout, filter, the
# column field and the swimlane field. Counting views proves nothing.
def view_shape($p): [
  $p.views.nodes[] | {
    name,
    layout,
    filter:    (.filter // ""),
    columns:   [.verticalGroupByFields.nodes[]?.name],
    swimlanes: [.groupByFields.nodes[]?.name]
  }
];
def enabled_workflows($p): [$p.workflows.nodes[] | select(.enabled == true) | .name] | sort;

(proj($t)) as $T | (proj($n)) as $N |
(enabled_workflows($T) - [$uncopyable]) as $expected_wf |
(enabled_workflows($N))                 as $new_wf |
([$expected_wf[] | select(. as $w | $new_wf | index($w) | not)]) as $missing_wf |
{
  fields: {
    template: ($T.fields.nodes | length),
    new:      ($N.fields.nodes | length),
    match:    (($T.fields.nodes | length) == ($N.fields.nodes | length))
  },
  status: {
    options_template: status_options($T),
    options_new:      status_options($N),
    match:            (status_options($T) == status_options($N))
  },
  views: {
    template: view_shape($T),
    new:      view_shape($N),
    match:    (view_shape($T) == view_shape($N))
  },
  workflows: {
    expected:    $expected_wf,
    enabled_new: $new_wf,
    missing:     $missing_wf,
    match:       (($missing_wf | length) == 0)
  },
  auto_add: {
    name:     $uncopyable,
    required: true,
    present:  (($new_wf | index($uncopyable)) != null),
    filter:   $filter,
    ui_url:   $ui_url
  }
}
| . + { structural_pass: (.fields.match and .status.match and .views.match and .workflows.match) }
| . + { pass: (.structural_pass and .auto_add.present) }
')

echo "$REPORT"

STRUCTURAL=$(echo "$REPORT" | jq -r '.structural_pass')
AUTO_ADD=$(echo "$REPORT" | jq -r '.auto_add.present')

if [ "$STRUCTURAL" != "true" ]; then
  {
    echo ""
    echo "STRUCTURAL DRIFT — the copy did not reproduce the template."
    echo "$REPORT" | jq -r '
      (if .fields.match    | not then "  fields: template \(.fields.template) vs new \(.fields.new)" else empty end),
      (if .status.match    | not then "  status options differ — compare .status in the report above" else empty end),
      (if .views.match     | not then "  views differ (name/layout/filter/columns/swimlanes) — compare .views above" else empty end),
      (if .workflows.match | not then "  workflows missing: \(.workflows.missing | join(", "))" else empty end)
    '
    echo "  Columns and swimlanes cannot be set by any mutation. If those drifted,"
    echo "  delete this board and re-copy the template rather than hand-fixing it."
  } >&2
  exit 1
fi

if [ "$AUTO_ADD" != "true" ]; then
  {
    echo ""
    echo "Structural parity OK. One manual step remains:"
    echo "  Enable \"${UNCOPYABLE_WORKFLOW}\" at $(workflows_ui_url)"
    echo "  Filter: $(auto_add_filter)"
    echo "  No API can do this — deleteProjectV2Workflow is the only workflow mutation."
    echo "  Re-run this script after enabling it to get a clean exit 0."
  } >&2
  exit 3
fi

exit 0
