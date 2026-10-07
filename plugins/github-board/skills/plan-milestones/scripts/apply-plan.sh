#!/usr/bin/env bash
# apply-plan.sh — apply a milestone-focus plan: create target milestones, move issues,
# and comment the rationale on each moved issue. closed_moves fix the milestone of a
# closed issue with no comment. Every milestone write is REST by number
# (`gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`). Unlike
# `gh issue edit --milestone <title>`, REST by number can assign a closed milestone.
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

Refused before anything is written: moves, closed_moves, create_milestones or keep
that is not a list, or an entry that is not an object; a repo that is not OWNER/REPO
or has a . or .. part; an issue that is not a positive integer; a create_milestones
entry without a non-empty string title; an issue listed more than once; a target
that does not exist and is not in create_milestones; a target title held by two
milestones; an empty milestone list; and a closed_moves issue that is open or whose
state cannot be read. A create_milestones title that exists is not created again.

A write fails when gh fails (its error and the response body are printed) or when
the reply names another milestone. The rest of the plan still runs.

Exit codes: 0 ok · 1 error, or any write failed ("completed with N failure(s): #11 #12")
            · 2 usage
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

# --- validate the plan's shape before anything reads it ---------------------
# A list where an object belongs, or the other way round, used to crash a jq filter below
# (exit 5) instead of saying which key is wrong.
SHAPE=$(jq -r '
  if type != "object" then "  the plan is a \(type), not an object"
  else
    [ ("moves", "closed_moves", "create_milestones", "keep") as $k
      | .[$k] as $v
      | if $v == null then empty
        elif ($v | type) != "array" then "  \($k) is a \($v | type), not a list"
        else ($v | to_entries[] | select((.value | type) != "object")
              | "  \($k)[\(.key)] is a \(.value | type), not an object")
        end ]
    | join("\n")
  end' "$PLAN")
if [ -n "$SHAPE" ]; then
  echo "ERROR: the plan has the wrong shape:" >&2
  printf '%s\n' "$SHAPE" >&2
  exit 1
fi

REPO="${REPO_OVERRIDE:-$(jq -r '.repo // empty' "$PLAN")}"
[ -n "$REPO" ] || { echo "ERROR: no repo in plan and --repo not given" >&2; exit 1; }

# The repo goes into REST paths: extra segments, or a `.` or `..` part, would send the
# calls below to another endpoint.
if ! printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
  echo "ERROR: repo must be OWNER/REPO, got: $REPO" >&2
  exit 1
fi
case "/$REPO/" in
  */./*|*/../*) echo "ERROR: repo must be OWNER/REPO with no . or .. part, got: $REPO" >&2; exit 1 ;;
esac

# --- validate before touching anything -------------------------------------
BAD=$(jq -r '[.moves // [] | .[] | select((.rationale // "") | tostring | length < 10)
              | "  #\(.issue) -> \(.to): missing or too-short rationale"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: every move needs a real rationale (>=10 chars):" >&2
  printf '%s\n' "$BAD" >&2
  exit 1
fi

# The issue number goes into a REST path, so it must be a plain positive integer: "11/lock"
# would PATCH another endpoint. A target must be a non-empty title.
BAD=$(jq -r '
  [((.moves // []) + (.closed_moves // []))[]
   | select(((.issue | tostring | test("^[1-9][0-9]*$")) and ((.to | type) == "string")
             and ((.to // "") != "")) | not)
   | "  \(.issue // "(no issue)") -> \(.to // "(no target)")"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: each move needs an issue number and a target milestone title:" >&2
  printf '%s\n' "$BAD" >&2
  exit 1
fi

BAD=$(jq -r '[.create_milestones // [] | to_entries[]
              | select((.value.title | type) != "string" or .value.title == "")
              | "  create_milestones[\(.key)]: \(.value.title // "(no title)")"] | join("\n")' "$PLAN")
if [ -n "$BAD" ]; then
  echo "ERROR: each create_milestones entry needs a non-empty string title:" >&2
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

ERRF=$(mktemp)
trap 'rm -f "$ERRF"' EXIT

# No --jq here: gh applies --jq to each page, so past 100 milestones it printed one array per
# page and `jq --argjson` below failed. `jq -s add` joins the pages whether gh merged them into
# one array or printed them back to back. A failed read stops the script: an empty list would
# report real milestones as unknown, or try to create them again. Empty output with exit 0 is
# not an empty list either (gh prints [] for that).
if ! MS_RAW=$(gh api "repos/$REPO/milestones?state=all&per_page=100" --paginate) || [ -z "$MS_RAW" ]; then
  echo "ERROR: could not list milestones for $REPO (see above); nothing was changed." >&2
  exit 1
fi
# Every state, with its number. Unlike `gh issue edit --milestone`, REST by number can
# assign a closed milestone.
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
# Resolve by exact title. GitHub rejects duplicate titles, so two milestones with one title
# should not exist; if they do (or one has no number), refuse instead of picking one.
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

# closed_moves skip the rationale comment, so they are for closed issues only. Read each
# issue's state now, before any write; an unreadable state is not "closed".
# Captured first: a jq failure inside `for ... in $(...)` would run zero checks silently.
CLOSED_ISSUES=$(jq -r '.closed_moves // [] | .[].issue | tostring' "$PLAN")
OPEN=""; UNREAD=""
for num in $CLOSED_ISSUES; do
  if ! ST=$(gh api "repos/$REPO/issues/$num" --jq .state 2>"$ERRF"); then
    UNREAD="$UNREAD
  #$num: $(tr '\n' ' ' < "$ERRF")"
  elif [ "$ST" != "closed" ]; then
    OPEN="$OPEN #$num"
  fi
done
if [ -n "$UNREAD" ]; then
  echo "ERROR: could not read the state of these closed_moves issues; nothing was changed:$UNREAD" >&2
  exit 1
fi
if [ -n "$OPEN" ]; then
  echo "ERROR: closed_moves are for closed issues, and these are open:$OPEN" >&2
  echo "       put an open issue in moves, with a rationale." >&2
  exit 1
fi

# --- report ----------------------------------------------------------------
echo "repo: $REPO"
[ "$APPLY" -eq 1 ] && echo "mode: APPLY" || echo "mode: DRY-RUN (pass --apply to write)"
echo

jq -r --argjson have "$EXISTING" '
  def closed($t): if ([$have[] | select(.title == $t and .state == "closed")] | length) > 0
                  then " [closed milestone]" else "" end;
  ((.create_milestones // [])
   | map(.title as $t | [$have[] | select(.title == $t)][0] as $e
         | if $e then "CREATE milestone \($t): EXISTS (\($e.state)), will not create"
           else "CREATE milestone \($t)" end)
   | join("\n")) as $c |
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
FAILED_LIST=""
fail() { FAILED=$((FAILED + 1)); FAILED_LIST="$FAILED_LIST $1"; }

# --- create milestones -----------------------------------------------------
# Rows are captured first, not read from a process substitution: a jq failure there would
# feed zero rows and read as "nothing to do".
CREATES=$(jq -c '.create_milestones // [] | .[]' "$PLAN")
while IFS= read -r row; do
  [ -n "$row" ] || continue
  title=$(printf '%s' "$row" | jq -r '.title')
  desc=$(printf '%s' "$row" | jq -r '.description // ""')
  state=$(printf '%s' "$EXISTING" | jq -r --arg t "$title" '[.[] | select(.title == $t)][0].state // empty')
  if [ -n "$state" ]; then
    echo "milestone $title: EXISTS ($state), will not create"
    continue
  fi
  # stdout and stderr apart: a gh warning on stderr must not become part of the number.
  # The whole of stdout must be digits (a newline is not one).
  if OUT=$(gh api "repos/$REPO/milestones" -X POST \
             -f title="$title" -f state="open" -f description="$desc" --jq '.number' 2>"$ERRF"); then
    case "$OUT" in
      ''|*[!0-9]*)
        echo "milestone $title: FAILED to create — unexpected reply: $(printf '%s' "$OUT" | tr '\n' ' ') $(tr '\n' ' ' < "$ERRF")" >&2
        fail "milestone:$title" ;;
      *)
        MS_MAP=$(printf '%s' "$MS_MAP" | jq -c --arg t "$title" --argjson n "$OUT" '. + {($t): $n}')
        echo "created milestone #$OUT: $title" ;;
    esac
  else
    echo "milestone $title: FAILED to create — $(tr '\n' ' ' < "$ERRF") $(printf '%s' "$OUT" | tr '\n' ' ')" >&2
    fail "milestone:$title"
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
    fail "#$num"
    continue
  fi
  # Unlike `gh issue edit --milestone`, REST by number can assign a closed milestone.
  # The reply's milestone number must be the one sent. On an HTTP error gh prints the
  # response body on stdout (a 422 carries its errors[] there), so keep both streams.
  if GOT=$(gh api -X PATCH "repos/$REPO/issues/$num" -F milestone="$msnum" --jq '.milestone.number' 2>"$ERRF"); then
    if [ "$GOT" != "$msnum" ]; then
      echo "  #$num -> $target: FAILED — GitHub reports milestone '$(printf '%s' "$GOT" | tr '\n' ' ')', not $msnum" >&2
      fail "#$num"
      continue
    fi
  else
    echo "  #$num -> $target: FAILED to set milestone — $(tr '\n' ' ' < "$ERRF") $(printf '%s' "$GOT" | tr '\n' ' ')" >&2
    fail "#$num"
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
    fail "#$num"
    continue
  fi
  echo "  #$num -> $target (rationale posted)"
done <<< "$ROWS"

echo
if [ "$FAILED" -gt 0 ]; then
  echo "completed with $FAILED failure(s):$FAILED_LIST" >&2
  exit 1
fi
echo "done"
