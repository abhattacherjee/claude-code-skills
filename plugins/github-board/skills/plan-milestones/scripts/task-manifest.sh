#!/usr/bin/env bash
# task-manifest.sh — emit the TaskCreate checklist for each milestone-focus workflow.
set -eu

usage() {
  cat <<'USAGE'
Usage: task-manifest.sh WORKFLOW

Workflows:
  refocus       Full pass: release check -> gather -> judge -> plan -> confirm -> apply
                -> verify (7 tasks)
  audit-only    Release check, gather and judge, produce a plan, stop before writing (4 tasks)

Options:
  --list        Machine-readable workflow names
  -h, --help    This message
USAGE
}

[ $# -ge 1 ] || { usage >&2; exit 2; }

case "$1" in
  -h|--help) usage; exit 0 ;;
  --list) printf 'refocus\naudit-only\n'; exit 0 ;;
esac

case "$1" in
  refocus)
    cat <<'JSON'
[
  {"subject":"Check closed issues against their releases","activeForm":"Checking closed issues against their releases","description":"Step 0. Run scripts/release-reconcile.sh --repo O/R --json <file> from a checkout of the repo. Show its summary line even when clean. Fold its closed_moves into the plan before any theme work, and raise every FLAG line with the user."},
  {"subject":"Gather milestone + issue state","activeForm":"Gathering milestone and issue state","description":"Run scripts/milestone-report.sh. Note which milestones have no theme set and which open issues are flagged ACCRETION."},
  {"subject":"Establish the theme for each milestone","activeForm":"Establishing milestone themes","description":"Read each open milestone's description. A milestone with no theme cannot be triaged — write one with the user before judging membership."},
  {"subject":"Judge each open issue against its milestone theme","activeForm":"Judging issues against themes","description":"Inline classification over the report JSON: does this issue's failure mode match the theme? Priority label is NOT the criterion."},
  {"subject":"Check effort on every keep candidate","activeForm":"Checking effort on keep candidates","description":"For each issue staying, probe blast radius (callers, test references, signature changes). Keep must mean shippable."},
  {"subject":"Confirm the plan with the user","activeForm":"Confirming the plan","description":"Present keep vs defer with one-line rationale each, plus the deferral milestone's own theme. Get explicit approval before writing."},
  {"subject":"Apply and verify","activeForm":"Applying and verifying","description":"Run scripts/apply-plan.sh --apply, then re-run milestone-report.sh to confirm the resulting split."}
]
JSON
    ;;
  audit-only)
    cat <<'JSON'
[
  {"subject":"Check closed issues against their releases","activeForm":"Checking closed issues against their releases","description":"Step 0. Run scripts/release-reconcile.sh --repo O/R --json <file> from a checkout of the repo. Show its summary line even when clean. Fold its closed_moves into the plan before any theme work, and raise every FLAG line with the user."},
  {"subject":"Gather milestone + issue state","activeForm":"Gathering milestone and issue state","description":"Run scripts/milestone-report.sh --json."},
  {"subject":"Judge each open issue against its milestone theme","activeForm":"Judging issues against themes","description":"Inline classification. Produce keep/defer with a rationale per issue."},
  {"subject":"Write the plan file","activeForm":"Writing the plan file","description":"Emit plan JSON for scripts/apply-plan.sh. Do not apply it."}
]
JSON
    ;;
  *)
    echo "unknown workflow: $1" >&2; usage >&2; exit 2 ;;
esac
