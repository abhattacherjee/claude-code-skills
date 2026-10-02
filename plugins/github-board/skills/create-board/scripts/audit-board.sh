#!/usr/bin/env bash
# Audit existing ProjectV2 boards against the template. REPORT ONLY — this
# script never writes to a board.
#
# Why report-only, and why you should not "just fix" Status options by hand:
# updateProjectV2Field replaces single-select options. If the option objects
# you send omit their existing `id`, GitHub creates NEW options, clears the
# field value on every item that used the old ones, and silently DISABLES every
# workflow that referenced them. Measured 2026-09-16: one id-less
# updateProjectV2Field call disabled 5 of 6 enabled workflows on a fresh board.
# Repeating the same call WITH each option's `id` disabled none. Since
# deleteProjectV2Workflow is the only workflow mutation, re-enabling them is a
# UI-only repair. See references/graphql-snippets.md.

set -euo pipefail

TEMPLATE_OWNER=""      # --template-owner, else create_board.template_owner in the config
TEMPLATE_NUMBER=""     # --template, else create_board.template_number
OWNER=""
NUMBER=""
ALL=false
JSON=false

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <login> --number <n> [--template-owner <login>] [--template <n>] [--json]
       $(basename "$0") --owner <login> --all [--template-owner <login>] [--template <n>] [--json]

Compares one board (or every open board an owner has) against the template and
reports drift. Writes nothing, to either the board or the template.

Checks per board:
  status options   name + color, in order
  views            name, layout, filter, columns (verticalGroupByFields),
                   swimlanes (groupByFields)
  auto-add         whether "Auto-add to project" is enabled — it is the only
                   repo-scoped workflow, never survives a copy, and cannot be
                   created by any mutation

Flags:
  --owner <login>          Owner whose board(s) to audit. Required.
  --number <n>             Audit a single board. Mutually exclusive with --all.
  --all                    Audit every open board this owner has.
  --template-owner <login> Template owner. Default: create_board.template_owner in the
                           github-board config (create-board init writes it).
  --template <n>           Template project number. Default: create_board.template_number.
  --json                   Emit one JSON object per board instead of text.
  -h, --help               Show this help.

Exit codes:
  0  Every audited board matches the template and has auto-add enabled
  1  At least one board drifted or is missing auto-add
  2  Bad usage or unreadable template
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --owner)          OWNER="$2";           shift 2 ;;
    --number)         NUMBER="$2";          shift 2 ;;
    --all)            ALL=true;             shift   ;;
    --template-owner) TEMPLATE_OWNER="$2";  shift 2 ;;
    --template)       TEMPLATE_NUMBER="$2"; shift 2 ;;
    --json)           JSON=true;            shift   ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$OWNER" ] || { echo "Missing --owner" >&2; usage >&2; exit 2; }
if [ "$ALL" = true ] && [ -n "$NUMBER" ]; then
  echo "--all and --number are mutually exclusive" >&2; exit 2
fi
if [ "$ALL" = false ] && [ -z "$NUMBER" ]; then
  echo "Need --number <n> or --all" >&2; usage >&2; exit 2
fi

# Flags win; otherwise the template comes from the github-board config.
if [ -z "$TEMPLATE_OWNER" ] || [ -z "$TEMPLATE_NUMBER" ]; then
  . "$(dirname "$0")/../../../lib/config.sh"
  if cfg_owner="$(gb_config_get create_board.template_owner)" \
     && cfg_number="$(gb_config_get create_board.template_number)"; then
    TEMPLATE_OWNER="${TEMPLATE_OWNER:-$cfg_owner}"
    TEMPLATE_NUMBER="${TEMPLATE_NUMBER:-$cfg_number}"
  else
    echo "No template board: pass --template-owner <login> --template <n>, or run create-board init." >&2
    exit 2
  fi
fi

HERE="$(dirname "$0")"

# Snapshots go to unguessable paths and are removed on exit. A predictable
# name in world-writable /tmp lets another local user pre-create it as a
# symlink and redirect the write. Matches sync-workflows.sh.
umask 077
TEMPLATE_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/gh-board-audit-template.XXXXXX")"
SNAPSHOTS=( "$TEMPLATE_SNAPSHOT" )
trap 'rm -f "${SNAPSHOTS[@]}"' EXIT
"$HERE/inspect-template.sh" --owner "$TEMPLATE_OWNER" --number "$TEMPLATE_NUMBER" --out "$TEMPLATE_SNAPSHOT" >/dev/null || {
  echo "Could not snapshot template ${TEMPLATE_OWNER}/${TEMPLATE_NUMBER}" >&2; exit 2
}

# Build the list of boards to audit.
if [ "$ALL" = true ]; then
  # Audit every open board this owner has, except the template itself (which
  # is only the template when its owner matches too).
  BOARDS=$(gh project list --owner "$OWNER" --limit 200 --format json \
    | jq -r --arg tn "$TEMPLATE_NUMBER" --arg to "$TEMPLATE_OWNER" --arg owner "$OWNER" '
        .projects[]
        | select(.closed == false)
        | select(((.number | tostring) == $tn and $to == $owner) | not)
        | "\(.number)\t\(.title)"')
else
  TITLE=$(gh project view "$NUMBER" --owner "$OWNER" --format json --jq '.title' 2>/dev/null || echo "")
  [ -n "$TITLE" ] || { echo "Cannot read project ${OWNER}/${NUMBER}" >&2; exit 2; }
  BOARDS=$(printf '%s\t%s' "$NUMBER" "$TITLE")
fi

DRIFT_FOUND=0

# Empty titles would collapse a tab-separated read; unit separator avoids it.
while IFS=$'\t' read -r BNUM BTITLE; do
  [ -n "$BNUM" ] || continue

  BSNAP="$(mktemp "${TMPDIR:-/tmp}/gh-board-audit.XXXXXX")"
  SNAPSHOTS+=( "$BSNAP" )
  if ! "$HERE/inspect-template.sh" --owner "$OWNER" --number "$BNUM" --out "$BSNAP" >/dev/null 2>&1; then
    echo "  ${BNUM}  ${BTITLE}: UNREADABLE (auth, scope, or deleted)" >&2
    DRIFT_FOUND=1
    continue
  fi

  RESULT=$(jq -n \
    --slurpfile t "$TEMPLATE_SNAPSHOT" \
    --slurpfile b "$BSNAP" \
    --arg num "$BNUM" \
    --arg title "$BTITLE" '
  def proj($x): ($x[0].data.user.projectV2 // $x[0].data.organization.projectV2);
  def status_options($p): [$p.fields.nodes[] | select(.name == "Status") | .options[]? | {name, color}];
  def view_shape($p): [$p.views.nodes[] | {
        name, layout, filter: (.filter // ""),
        columns:   [.verticalGroupByFields.nodes[]?.name],
        swimlanes: [.groupByFields.nodes[]?.name]
      }];
  def enabled($p): [$p.workflows.nodes[] | select(.enabled == true) | .name];

  (proj($t)) as $T | (proj($b)) as $B |
  {
    number: ($num | tonumber),
    title: $title,
    status_match: (status_options($T) == status_options($B)),
    status_template: status_options($T),
    status_actual:   status_options($B),
    views_match: (view_shape($T) == view_shape($B)),
    views_template: view_shape($T),
    views_actual:   view_shape($B),
    auto_add_enabled: ((enabled($B) | index("Auto-add to project")) != null)
  }
  | . + { ok: (.status_match and .views_match and .auto_add_enabled) }
  ')

  OK=$(echo "$RESULT" | jq -r '.ok')
  [ "$OK" = "true" ] || DRIFT_FOUND=1

  if [ "$JSON" = true ]; then
    # One object per line, so callers can pipe straight into `jq -r` or `while read`.
    echo "$RESULT" | jq -c .
  else
    if [ "$OK" = "true" ]; then
      printf '  %-4s %-45s OK\n' "$BNUM" "$BTITLE"
    else
      printf '  %-4s %-45s DRIFT\n' "$BNUM" "$BTITLE"
      echo "$RESULT" | jq -r '
        (if .status_match | not then
           "         status options: expected \([.status_template[] | "\(.name)(\(.color))"] | join(" > "))\n         status options: actual   \([.status_actual[]   | "\(.name)(\(.color))"] | join(" > "))"
         else empty end),
        (if .views_match | not then
           "         views: expected \(.views_template | map("\(.name)[\(.layout) cols=\(.columns|join(","))  lanes=\(.swimlanes|join(","))]") | join(" | "))\n         views: actual   \(.views_actual   | map("\(.name)[\(.layout) cols=\(.columns|join(","))  lanes=\(.swimlanes|join(","))]") | join(" | "))"
         else empty end),
        (if .auto_add_enabled | not then
           "         auto-add: \"Auto-add to project\" is NOT enabled — new issues will not land on this board"
         else empty end)
      '
    fi
  fi
done <<< "$BOARDS"

if [ "$JSON" = false ]; then
  echo ""
  if [ "$DRIFT_FOUND" -eq 0 ]; then
    echo "No drift. Every audited board matches ${TEMPLATE_OWNER}/${TEMPLATE_NUMBER} and has auto-add enabled."
  else
    cat <<EOF
Drift found. This script does not fix anything, by design.

  auto-add missing   Enable "Auto-add to project" in the board's /workflows page.
                     No mutation can create or enable a workflow.

  views drifted      Columns and swimlanes are read-only in the API
                     (ProjectV2ViewConfigurationInput accepts only visibleFieldIds).
                     Re-copy the template rather than rebuilding a view by hand.
                     View name, layout and filter CAN be fixed with
                     updateProjectV2View — see references/graphql-snippets.md.

  status drifted     updateProjectV2Field can fix this, but ONLY if you send each
                     option's existing id. Omitting ids clears item values and
                     silently disables every workflow that referenced the options.
EOF
  fi
fi

exit "$DRIFT_FOUND"
