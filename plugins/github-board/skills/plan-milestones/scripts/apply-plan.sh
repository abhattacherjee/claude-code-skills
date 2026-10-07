#!/usr/bin/env bash
# apply-plan.sh — apply a milestone-focus plan: create target milestones, move issues,
# and comment the rationale on each moved issue. closed_moves fix the milestone of a
# closed issue with no comment. Every milestone write is REST by number
# (`gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`), which also works for a
# closed milestone; `gh issue edit --milestone <title>` does not.
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
    "closed_moves": [
      {"issue": 181, "to": "v3.6"}
    ],
    "keep": [
      {"issue": 336, "note": "Why it stays (optional, not written anywhere)"}
    ]
  }

Every move REQUIRES a rationale of at least 10 characters, posted as a comment; the
script refuses the plan otherwise. closed_moves set the release milestone of a closed
issue: no rationale, no comment. The target may be a closed milestone.

Refused before anything is written: a target that does not exist and is not in
create_milestones, a target title held by two milestones, an issue that is not a
positive integer, an issue listed more than once, and a repo that is not OWNER/REPO.

Exit codes: 0 ok · 1 error, or any write failed (gh's error is printed) · 2 usage
USAGE
}

PLAN=""; APPLY=0; REPO_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    # `shift 2` with one argument left fails under set -e: exit 1 and no message.
    --plan|--repo)
      [ $# -ge 2 ] || { echo "ERROR: $1 needs a value" >&2; usage >&2; exit 2; }
      if [ "$1" = "--plan" ]; then PLAN="$2"; else REPO_OVERRIDE="$2"; fi
      shift 2 ;;
    --apply) APPLY=1; shift ;;
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

# A REPO with extra path segments would send the REST calls below to another endpoint.
if ! printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
  echo "ERROR: repo must be OWNER/REPO, got: $REPO" >&2
  exit 1
fi

# --- validate before touching anything -------------------------------------
BAD=$(jq -r '[.moves // [] | .[] | select((.rationale // "") | length < 10)
              | "  #\(.issue) -> \(.to): missing or too-short rationale"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: every move needs a real rationale (>=10 chars):" >&2
  printf '%s\n' "$BAD" >&2
  exit 1
fi

# The issue number goes into a REST path, so it must be a plain positive integer: "11/lock"
# would PATCH another endpoint. A target must be a non-empty title.
BAD=$(jq -r '
  [((.moves // []) | if type == "array" then .[] else {issue: "moves is not a list"} end),
   ((.closed_moves // []) | if type == "array" then .[] else {issue: "closed_moves is not a list"} end)
   | select(((.issue | tostring | test("^[1-9][0-9]*$")) and ((.to | type) == "string")
             and ((.to // "") != "")) | not)
   | "  \(.issue // "(no issue)") -> \(.to // "(no target)")"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: each move needs an issue number and a target milestone title:" >&2
  printf '%s\n' "$BAD" >&2
  exit 1
fi

# One issue in two entries has no single right answer; refuse rather than apply both.
DUP=$(jq -r '[((.moves // []) + (.closed_moves // []))[] | .issue | tostring]
             | group_by(.) | map(select(length > 1) | "#\(.[0])") | join(", ")' "$PLAN")
if [ -n "$DUP" ]; then
  echo "ERROR: issue(s) listed more than once across moves and closed_moves: $DUP" >&2
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
# Every state, with its number: REST assigns a milestone by number, and that is the only way
# to put an issue into a CLOSED milestone (`gh issue edit --milestone` takes an open title).
EXISTING=$(printf '%s' "$MS_RAW" | jq -cs 'add // [] | map({title, number, state})') || {
  echo "ERROR: could not read the milestone list for $REPO; nothing was changed." >&2
  exit 1
}
UNKNOWN=$(jq -r --argjson have "$EXISTING" '
  ([.create_milestones // [] | .[].title]) as $new | [$have[].title] as $titles |
  [(.moves // []) + (.closed_moves // []) | .[].to] | unique
  | map(select((. as $t | $titles | index($t)) == null and (. as $t | $new | index($t)) == null))
  | join(", ")' "$PLAN")
if [ -n "$UNKNOWN" ]; then
  echo "ERROR: move targets that neither exist nor are being created: $UNKNOWN" >&2
  echo "       add them to create_milestones, or fix the title (titles are case-sensitive)." >&2
  exit 1
fi
# Resolve by exact title. Two milestones with one title (or one without a number) have no
# single right answer, so refuse instead of picking one.
AMBIGUOUS=$(jq -r --argjson have "$EXISTING" '
  [(.moves // []) + (.closed_moves // []) | .[].to] | unique
  | map(. as $t | [$have[] | select(.title == $t)] as $m
        | select(($m | length) > 1 or (($m | length) == 1 and ($m[0].number | type) != "number"))
        | if ($m | length) > 1 then "\($t) (\($m | map("#\(.number) \(.state)") | join(", ")))"
          else "\($t) (no number in the milestone list)" end)
  | join("; ")' "$PLAN")
if [ -n "$AMBIGUOUS" ]; then
  echo "ERROR: ambiguous move target(s), so no single milestone number: $AMBIGUOUS" >&2
  echo "       rename one of the milestones, then re-run." >&2
  exit 1
fi

# --- report ----------------------------------------------------------------
echo "repo: $REPO"
[ "$APPLY" -eq 1 ] && echo "mode: APPLY" || echo "mode: DRY-RUN (pass --apply to write)"
echo

jq -r --argjson have "$EXISTING" '
  def closed($t): if ([$have[] | select(.title == $t and .state == "closed")] | length) > 0
                  then " [closed milestone]" else "" end;
  ((.create_milestones // []) | map("CREATE milestone \(.title)") | join("\n")) as $c |
  ((.moves // []) | map("MOVE   #\(.issue) -> \(.to)\(closed(.to))") | join("\n")) as $m |
  ((.closed_moves // []) | map("FIX    #\(.issue) -> \(.to)\(closed(.to))  (closed_moves: no comment)")
   | join("\n")) as $f |
  ((.keep // []) | map("KEEP   #\(.issue)") | join("\n")) as $k |
  [$c, $m, $f, $k] | map(select(. != "")) | join("\n")' "$PLAN"
echo

if [ "$APPLY" -eq 0 ]; then
  echo "(nothing written)"
  exit 0
fi

# title -> number for every milestone, plus each one created below.
MS_MAP=$(printf '%s' "$EXISTING" | jq -c 'map({key: .title, value: .number}) | from_entries')
FAILED=0

# --- create milestones -----------------------------------------------------
# Rows are captured first, not read from a process substitution: a jq failure there would
# feed zero rows and read as "nothing to do".
CREATES=$(jq -c '.create_milestones // [] | .[]' "$PLAN")
while IFS= read -r row; do
  [ -n "$row" ] || continue
  title=$(printf '%s' "$row" | jq -r '.title // ""')
  desc=$(printf '%s' "$row" | jq -r '.description // ""')
  [ -n "$title" ] || continue
  if printf '%s' "$MS_MAP" | jq -e --arg t "$title" 'has($t)' >/dev/null; then
    echo "milestone $title: already exists, skipping create"
    continue
  fi
  if OUT=$(gh api "repos/$REPO/milestones" -X POST \
             -f title="$title" -f state="open" -f description="$desc" --jq '.number' 2>&1) \
     && printf '%s' "$OUT" | grep -Eq '^[0-9]+$'; then
    MS_MAP=$(printf '%s' "$MS_MAP" | jq -c --arg t "$title" --argjson n "$OUT" '. + {($t): $n}')
    echo "created milestone #$OUT: $title"
  else
    echo "milestone $title: FAILED to create — $(printf '%s' "$OUT" | tr '\n' ' ')" >&2
    FAILED=$((FAILED + 1))
  fi
done <<< "$CREATES"

# --- move (+ comment for moves) --------------------------------------------
# Each row is one JSON object, so a rationale keeps its newlines and tabs. (@tsv wrote them
# as the two characters \n and \t, and the comment showed the backslash.)
ROWS=$(jq -c '((.moves // []) | map(. + {kind: "move"}))
              + ((.closed_moves // []) | map(. + {kind: "closed"})) | .[]' "$PLAN")
while IFS= read -r row; do
  [ -n "$row" ] || continue
  num=$(printf '%s' "$row" | jq -r '.issue | tostring')
  target=$(printf '%s' "$row" | jq -r '.to')
  kind=$(printf '%s' "$row" | jq -r '.kind')
  msnum=$(printf '%s' "$MS_MAP" | jq -r --arg t "$target" '.[$t] // empty')
  if [ -z "$msnum" ]; then
    echo "  #$num -> $target: FAILED — milestone $target was not created (see above)" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  # REST by number: the only call that can assign a closed milestone.
  if ! ERR=$(gh api -X PATCH "repos/$REPO/issues/$num" -F milestone="$msnum" 2>&1 >/dev/null); then
    echo "  #$num -> $target: FAILED to set milestone — $(printf '%s' "$ERR" | tr '\n' ' ')" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  if [ "$kind" = "closed" ]; then
    # closed_moves fix a closed issue's release milestone: no rationale, no comment.
    echo "  #$num -> $target (closed_moves: no comment)"
    continue
  fi
  rationale=$(printf '%s' "$row" | jq -r '.rationale')
  # Comment failure must not read as success: the move without its reason is the
  # exact half-state this script exists to prevent.
  if ! ERR=$(printf '%s' "$rationale" | gh issue comment "$num" --repo "$REPO" --body-file - 2>&1 >/dev/null); then
    echo "  #$num: milestone set to $target but RATIONALE COMMENT FAILED — add it by hand: $(printf '%s' "$ERR" | tr '\n' ' ')" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  echo "  #$num -> $target (rationale posted)"
done <<< "$ROWS"

echo
if [ "$FAILED" -gt 0 ]; then
  echo "completed with $FAILED failure(s) — see above" >&2
  exit 1
fi
echo "done"
