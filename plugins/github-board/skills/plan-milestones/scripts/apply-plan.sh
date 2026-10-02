#!/usr/bin/env bash
# apply-plan.sh — apply a milestone-focus plan: create target milestones, move issues,
# and comment the rationale on each moved issue.
#
# The rationale comment is not optional decoration. Six months later the milestone
# assignment is visible but the reasoning is not, and "why isn't this in the release?"
# gets re-litigated from scratch. The comment is where the decision survives.
#
# Validation script: set -euo pipefail.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: apply-plan.sh --plan FILE [--apply] [--repo OWNER/REPO]

Applies a milestone re-organisation plan. Dry-run by default — pass --apply to write.

Options:
  --plan FILE     Plan JSON (see shape below). Required.
  --apply         Actually perform the changes (default: dry-run)
  --repo O/R      Override the repo named in the plan
  -h, --help      This message

Plan shape:
  {
    "repo": "owner/repo",
    "create_milestones": [
      {"title": "v3.7", "description": "Theme: ... (why these belong together)"}
    ],
    "moves": [
      {"issue": 337, "to": "v3.7", "rationale": "Why it does not fit the source theme."}
    ],
    "keep": [
      {"issue": 336, "note": "Why it stays (optional, not written anywhere)"}
    ]
  }

Every move REQUIRES a non-empty rationale; the script refuses the plan otherwise.
A move whose target milestone does not exist and is not in create_milestones is
also refused, rather than silently creating one.

Exit codes: 0 ok · 1 error · 2 usage
USAGE
}

PLAN=""; APPLY=0; REPO_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --repo) REPO_OVERRIDE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$PLAN" ] || { echo "ERROR: --plan is required" >&2; usage >&2; exit 2; }
[ -f "$PLAN" ] || { echo "ERROR: plan file not found: $PLAN" >&2; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "ERROR: gh not found on PATH" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found on PATH" >&2; exit 1; }
jq -e . "$PLAN" >/dev/null 2>&1 || { echo "ERROR: plan is not valid JSON" >&2; exit 1; }

REPO="${REPO_OVERRIDE:-$(jq -r '.repo // empty' "$PLAN")}"
[ -n "$REPO" ] || { echo "ERROR: no repo in plan and --repo not given" >&2; exit 1; }

# --- validate before touching anything -------------------------------------
BAD=$(jq -r '[.moves // [] | .[] | select((.rationale // "") | length < 10)
              | "  #\(.issue) -> \(.to): missing or too-short rationale"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: every move needs a real rationale (>=10 chars):" >&2
  printf '%s\n' "$BAD" >&2
  exit 1
fi

# No --jq here: gh applies --jq to each page, so past 100 milestones it printed one array per
# page and `jq --argjson` below failed. `jq -s add` joins the pages whether gh merged them into
# one array or printed them back to back. A failed read stops the script: an empty list would
# report real milestones as unknown, or try to create them again.
if ! MS_RAW=$(gh api "repos/$REPO/milestones?state=all&per_page=100" --paginate); then
  echo "ERROR: could not list milestones for $REPO (see above); nothing was changed." >&2
  exit 1
fi
EXISTING=$(printf '%s' "$MS_RAW" | jq -cs 'add // [] | [.[].title]') || {
  echo "ERROR: could not read the milestone list for $REPO; nothing was changed." >&2
  exit 1
}
UNKNOWN=$(jq -r --argjson have "$EXISTING" '
  ([.create_milestones // [] | .[].title]) as $new |
  [.moves // [] | .[].to] | unique
  | map(select((. as $t | $have | index($t)) == null and (. as $t | $new | index($t)) == null))
  | join(", ")' "$PLAN")
if [ -n "$UNKNOWN" ]; then
  echo "ERROR: move targets that neither exist nor are being created: $UNKNOWN" >&2
  echo "       add them to create_milestones, or fix the title (titles are case-sensitive)." >&2
  exit 1
fi

# --- report ----------------------------------------------------------------
echo "repo: $REPO"
[ "$APPLY" -eq 1 ] && echo "mode: APPLY" || echo "mode: DRY-RUN (pass --apply to write)"
echo

jq -r '
  ((.create_milestones // []) | map("CREATE milestone \(.title)") | join("\n")) as $c |
  ((.moves // []) | map("MOVE   #\(.issue) -> \(.to)") | join("\n")) as $m |
  ((.keep // []) | map("KEEP   #\(.issue)") | join("\n")) as $k |
  [$c, $m, $k] | map(select(. != "")) | join("\n")' "$PLAN"
echo

if [ "$APPLY" -eq 0 ]; then
  echo "(nothing written)"
  exit 0
fi

# --- create milestones -----------------------------------------------------
while IFS=$'\t' read -r title desc; do
  [ -n "$title" ] || continue
  if printf '%s' "$EXISTING" | jq -e --arg t "$title" 'index($t) != null' >/dev/null; then
    echo "milestone $title: already exists, skipping create"
    continue
  fi
  gh api "repos/$REPO/milestones" -X POST \
    -f title="$title" -f state="open" -f description="$desc" \
    --jq '"created milestone #\(.number): \(.title)"'
done < <(jq -r '.create_milestones // [] | .[] | [.title, (.description // "")] | @tsv' "$PLAN")

# --- move + comment --------------------------------------------------------
FAILED=0
while IFS=$'\t' read -r num target rationale; do
  [ -n "$num" ] || continue
  if ! gh issue edit "$num" --repo "$REPO" --milestone "$target" >/dev/null 2>&1; then
    echo "  #$num -> $target: FAILED to set milestone" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  # Comment failure must not read as success: the move without its reason is the
  # exact half-state this script exists to prevent.
  if ! printf '%s' "$rationale" | gh issue comment "$num" --repo "$REPO" --body-file - >/dev/null 2>&1; then
    echo "  #$num: milestone set to $target but RATIONALE COMMENT FAILED — add it by hand" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  echo "  #$num -> $target (rationale posted)"
done < <(jq -r '.moves // [] | .[] | [.issue, .to, .rationale] | @tsv' "$PLAN")

echo
if [ "$FAILED" -gt 0 ]; then
  echo "completed with $FAILED failure(s) — see above" >&2
  exit 1
fi
echo "done"
