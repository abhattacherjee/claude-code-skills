#!/usr/bin/env bash
#
# board-move.sh — move a GitHub issue/PR's Project (v2) card to a target Status column.
#
# Mid-lifecycle companion to promote-shipped (which only does release -> Done).
# Reuses the proven projectsV2 discovery + Status-field + updateProjectV2ItemFieldValue
# pattern. Requires the gh CLI authenticated with the 'project' scope to apply a move.
# Board and Status lookups are cached for 7 days (~/.cache/github-board). When a move fails, or
# the target column is not in the cached options, while cached ids are in use, the script drops
# them and re-runs itself once with fresh lookups. --no-cache skips the cache.
#
# Moving an ISSUE to a post-merge column also sets its milestone to the next-release one
# (lib/config.py next-release-milestone, #204). The card moves first; a milestone problem only
# warns and never changes the exit code. --pr moves and other columns touch no milestone.
#
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../../lib/config.sh"
ORIG_ARGS=("$@")
CACHE_USED=0

die() { echo "Error: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
board-move.sh — move an issue/PR's Project (v2) card to a target Status column.

USAGE:
  board-move.sh --issue <N> --to "<status>" [options]
  board-move.sh --pr <N> --to "<status>" [options]
  board-move.sh --list-status [options]

OPTIONS:
  --issue <N>         Issue number to move.
  --pr <N>            PR number to move (mutually exclusive with --issue).
  --to "<status>"     Target Status column. Matched case-insensitively: exact,
                      then unique substring (e.g. "in prog" -> "In Progress").
  --repo <owner/repo> Target repo (default: current repo via gh).
  --project <number>  Board number (required only if the repo has >1 open board).
  --add               Add the issue/PR to the board if it isn't already a card.
  --list-status       Print the board's Status options and exit.
  --dry-run           Show the resolved move without applying it.
  --no-cache          Skip the 7-day board/Status cache (~/.cache/github-board).
  -h, --help          This help.

MILESTONE:
  An --issue moved to a post-merge column also gets the next-release milestone:
  milestones.next_release["owner/repo"] in the github-board config, else the open
  milestone with the lowest version (vX.Y or vX.Y.Z). Post-merge columns are those
  named (any case) "Development Complete", "Dev Complete" or "Done in develop", or
  the list in move_card.post_merge_columns, which replaces those names. The card
  moves first; a milestone problem prints a warning and keeps the exit code.

EXAMPLES:
  board-move.sh --issue 28 --to "In Progress"
  board-move.sh --pr 31 --to "Development Complete"
  board-move.sh --issue 9 --to done --repo OWNER/REPO --project 7
  board-move.sh --list-status

EXIT CODES: 0 ok | 1 error | 2 usage | 3 missing gh 'project' auth scope
USAGE
  exit "${1:-2}"
}

REPO="" ISSUE="" PR="" TO="" PROJECT="" DRY_RUN=false ADD=false LIST=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue) ISSUE="${2:-}"; [[ -n "$ISSUE" ]] || usage 2; shift 2;;
    --pr) PR="${2:-}"; [[ -n "$PR" ]] || usage 2; shift 2;;
    --to) TO="${2:-}"; [[ -n "$TO" ]] || usage 2; shift 2;;
    --repo) REPO="${2:-}"; [[ -n "$REPO" ]] || usage 2; shift 2;;
    --project) PROJECT="${2:-}"; [[ -n "$PROJECT" ]] || usage 2; shift 2;;
    --add) ADD=true; shift;;
    --list-status) LIST=true; shift;;
    --dry-run) DRY_RUN=true; shift;;
    --no-cache) export GB_NO_CACHE=1; shift;;
    -h|--help) usage 0;;
    *) echo "Unknown argument: $1" >&2; usage 2;;
  esac
done

command -v gh >/dev/null || die "gh CLI not found."
command -v jq >/dev/null || die "jq not found."

# Auth scope. Every path hits the Projects API, so require at least read:project;
# applying a move (not --list-status / --dry-run) additionally needs write 'project'.
SCOPES=$(gh auth status 2>&1 | grep -i "Token scopes" || true)
case "$SCOPES" in
  *"read:project"*|*"'project'"*) ;;
  *) echo "Error: gh token lacks a GitHub Projects scope (need at least read:project)." >&2
     echo "Run: gh auth refresh -s read:project,project" >&2; exit 3;;
esac
if ! $LIST && ! $DRY_RUN; then
  case "$SCOPES" in
    *"'project'"*) ;;
    *) echo "Error: gh token has read:project but not write 'project' (needed to modify a board)." >&2
       echo "Run: gh auth refresh -s read:project,project" >&2; exit 3;;
  esac
fi

# resolve repo
if [[ -z "$REPO" ]]; then
  REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner') || die "not in a GitHub repo; pass --repo owner/repo."
fi
OWNER=${REPO%/*}; NAME=${REPO#*/}

gql() { gh api graphql -f query="$1" "${@:2}"; }

# refetch_once [gh error text]: when ids or options came from the cache, drop them and re-run
# this script once without reading the cache. A stale option id or a renamed column fails with
# text that names no node, so any failure counts, except a rate-limit or missing-scope error
# (gb_error_kind): fresh ids cannot fix those, and a retry only burns budget. The re-run sets
# GB_CACHE_REFRESH, so it can never loop.
refetch_once() {
  if [[ -n "${1:-}" ]]; then
    case "$(gb_error_kind "$1")" in rate|scope) return 0 ;; esac
  fi
  if [[ "$CACHE_USED" == 1 && -z "${GB_CACHE_REFRESH:-}" ]]; then
    echo "Cached board ids for $REPO look stale; refetching once." >&2
    gb_cache_drop move-boards "$OWNER" "$NAME"
    [[ -n "$PROJECT" ]] && gb_cache_drop move-status "$OWNER" "$NAME" "$PROJECT"
    GB_CACHE_REFRESH=1 exec bash "${BASH_SOURCE[0]}" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
  fi
}

# discover board (cached; an empty list is never cached)
if [[ -z "$PROJECT" ]]; then
  # Cache keys are tuples (lib/config.sh), never a joined string.
  if BOARDS=$(gb_cache_get move-boards "$OWNER" "$NAME"); then
    CACHE_USED=1
  else
    BOARDS=$(gql 'query($o:String!,$n:String!){repository(owner:$o,name:$n){projectsV2(first:100){nodes{number title closed}}}}' \
      -f o="$OWNER" -f n="$NAME" --jq '[.data.repository.projectsV2.nodes[]|select(.closed==false)]')
    if [[ "$(echo "$BOARDS" | jq 'length')" -ge 1 ]]; then printf '%s' "$BOARDS" | gb_cache_put move-boards "$OWNER" "$NAME"; fi
  fi
  COUNT=$(echo "$BOARDS" | jq 'length')
  [[ "$COUNT" -ge 1 ]] || die "no open Project (v2) board linked to $REPO."
  if [[ "$COUNT" -gt 1 ]]; then
    echo "Multiple boards linked to $REPO — pass --project <number>:" >&2
    echo "$BOARDS" | jq -r '.[]|"  #\(.number) \(.title)"' >&2
    exit 1
  fi
  PROJECT=$(echo "$BOARDS" | jq -r '.[0].number')
fi
[[ "$PROJECT" =~ ^[0-9]+$ ]] || die "--project must be a number (got: $PROJECT)."

PID="" FIELD_JSON=""
if CACHED=$(gb_cache_get move-status "$OWNER" "$NAME" "$PROJECT"); then
  CACHE_USED=1
  PID=$(echo "$CACHED" | jq -r '.pid // empty')
  FIELD_JSON=$(echo "$CACHED" | jq -c '.field // empty')
fi
if [[ -z "${PID:-}" || -z "${FIELD_JSON:-}" ]]; then
  # The board number itself may come from a stale cached list (the board was deleted), so a
  # failed or empty lookup refetches once before dying.
  if ! PID=$(gql 'query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){projectV2(number:$p){id}}}' \
      -f o="$OWNER" -f n="$NAME" -F p="$PROJECT" --jq '.data.repository.projectV2.id // empty' 2>&1); then
    refetch_once "$PID"
    die "board #$PROJECT lookup failed on $REPO: $PID"
  fi
  [[ -n "$PID" ]] || { refetch_once; die "board #$PROJECT not found on $REPO."; }
  # Status field + options (exact 'Status', else first single-select named like status)
  FIELD_JSON=$(gql 'query($id:ID!){node(id:$id){... on ProjectV2{fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}' \
    -f id="$PID" --jq '.data.node.fields.nodes | map(select(.id!=null)) | (map(select((.name//"")|ascii_downcase=="status"))[0]) // empty')
  [[ -n "$FIELD_JSON" ]] || die "no single-select 'Status' field on board #$PROJECT."
  jq -cn --arg pid "$PID" --argjson field "$FIELD_JSON" '{pid: $pid, field: $field}' | gb_cache_put move-status "$OWNER" "$NAME" "$PROJECT"
fi
FID=$(echo "$FIELD_JSON" | jq -r '.id')

if $LIST; then
  echo "Status options on $REPO board #$PROJECT:"
  echo "$FIELD_JSON" | jq -r '.options[]|"  - \(.name)"'
  exit 0
fi

[[ -n "$TO" ]] || { echo "Error: --to <status> required." >&2; usage 2; }
[[ -n "$ISSUE" || -n "$PR" ]] || { echo "Error: one of --issue/--pr required." >&2; usage 2; }
[[ -n "$ISSUE" && -n "$PR" ]] && { echo "Error: --issue and --pr are mutually exclusive." >&2; usage 2; }

# match target option: exact (ci) then unique substring (ci)
OID=$(echo "$FIELD_JSON" | jq -r --arg t "$TO" '
  .options as $o
  | ([$o[]|select((.name|ascii_downcase)==($t|ascii_downcase))]) as $exact
  | ([$o[]|select((.name|ascii_downcase)|contains($t|ascii_downcase))]) as $sub
  | if ($exact|length)==1 then $exact[0].id
    elif ($sub|length)==1 then $sub[0].id
    else "" end')
if [[ -z "$OID" ]]; then
  refetch_once          # a column added since the options were cached
  echo "Error: --to \"$TO\" did not uniquely match a Status option. Available:" >&2
  echo "$FIELD_JSON" | jq -r '.options[]|"  - \(.name)"' >&2
  exit 1
fi
ONAME=$(echo "$FIELD_JSON" | jq -r --arg id "$OID" '.options[]|select(.id==$id).name')

if [[ -n "$ISSUE" ]]; then KIND=issue; NUM="$ISSUE"; else KIND=pullRequest; NUM="$PR"; fi
[[ "$NUM" =~ ^[0-9]+$ ]] || die "issue/PR number must be numeric (got: $NUM)."
# Note: projectItems is capped at 100 (un-paginated). An item on >100 boards is not supported.
CONTENT=$(gql "query(\$o:String!,\$n:String!,\$num:Int!){repository(owner:\$o,name:\$n){$KIND(number:\$num){id milestone{number title} projectItems(first:100){nodes{id project{number}}}}}}" \
  -f o="$OWNER" -f n="$NAME" -F num="$NUM")
CONTENT_ID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.id // empty")
[[ -n "$CONTENT_ID" ]] || die "$KIND #$NUM not found on $REPO."
IID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.projectItems.nodes | map(select(.project.number==$PROJECT))[0].id // empty")

# --- next-release milestone (#204) ------------------------------------------------------
# Only an issue moved to a post-merge column. The column is judged by its RESOLVED name, so
# `--to complete` that resolves to "Development Complete" counts. A set config list replaces
# the built-in names; an empty list turns this off.
MS_POST_MERGE=false
if [[ "$KIND" == issue ]]; then
  # stdout only: anything on stderr (a Python warning) would corrupt the JSON list.
  PM_ERR=$(mktemp)
  if ! PM_COLS=$(gb_config_get move_card.post_merge_columns --optional 2>"$PM_ERR"); then
    echo "Warning: milestone not set: cannot read move_card.post_merge_columns: $(tr '\n' ' ' < "$PM_ERR")" >&2
  else
    cat "$PM_ERR" >&2
    [[ -n "$PM_COLS" ]] || PM_COLS='["development complete","dev complete","done in develop"]'
    PM_HIT=$(printf '%s' "$PM_COLS" | jq -r --arg n "$ONAME" '
          def norm: ascii_downcase | gsub("^\\s+|\\s+$"; "");
          ($n | norm) as $want
          | if type == "array" and ([.[] | select(type == "string") | norm | select(. == $want)]
                                     | length) > 0
            then "yes" else "no" end' 2>/dev/null || true)
    case "$PM_HIT" in
      yes) MS_POST_MERGE=true ;;
      no) ;;
      *) echo "Warning: milestone not set: move_card.post_merge_columns is not a JSON list: $PM_COLS" >&2 ;;
    esac
  fi
  rm -f "$PM_ERR"
fi
MS_CUR_NUM=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.milestone.number // empty")
MS_CUR=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.milestone.title // \"none\"")

# milestone_step dry|apply. Never fails the script: every problem is a warning.
milestone_step() {
  $MS_POST_MERGE || return 0
  local out rc=0 num title got errf
  # stderr passes through: the fallback note names the pick, and a failure says why.
  out=$(gb_next_release --repo "$REPO") || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "Warning: milestone not set: could not read the next-release milestone of $REPO (see above)." >&2
    return 0
  fi
  if [[ -z "$out" ]]; then
    echo "Warning: milestone not set: $REPO has no next-release milestone (see above)." >&2
    return 0
  fi
  num=${out%%$'\t'*}; title=${out#*$'\t'}
  if [[ "$num" == "$MS_CUR_NUM" ]]; then
    if [[ "$1" == dry ]]; then echo "[dry-run] milestone: unchanged ($title)"; else echo "milestone: unchanged ($title)"; fi
    return 0
  fi
  if [[ "$1" == dry ]]; then
    echo "[dry-run] would set milestone: $MS_CUR -> $title"
    return 0
  fi
  # REST by number, like apply-plan.sh and apply-promotions.sh. The reply must name the number
  # sent. On an HTTP error gh prints the response body on stdout, so keep both streams.
  errf=$(mktemp)
  rc=0
  got=$(gh api -X PATCH "repos/$REPO/issues/$NUM" -F milestone="$num" --jq .milestone.number 2>"$errf") || rc=$?
  if [[ $rc -eq 0 && "$got" == "$num" ]]; then
    echo "milestone: $MS_CUR -> $title"
  elif [[ $rc -ne 0 ]]; then
    echo "Warning: milestone not set: $(tr '\n' ' ' < "$errf")$(printf '%s' "$got" | tr '\n' ' ' | cut -c1-300) (the card still moved)" >&2
  else
    echo "Warning: milestone not set: GitHub reports milestone '$(printf '%s' "$got" | tr '\n' ' ')', not $num (the card still moved)" >&2
  fi
  rm -f "$errf"
  return 0
}

if [[ -z "$IID" ]]; then
  # The board number may come from a cached list that is out of date (the card sits on a board
  # linked since). Refetch once before saying it is not a card, and before adding it to what
  # may be the wrong board.
  refetch_once
  if ! $ADD; then
    die "$KIND #$NUM is not a card on board #$PROJECT. Re-run with --add to add it first."
  fi
  if $DRY_RUN; then
    echo "[dry-run] would add $KIND #$NUM to board #$PROJECT, then set Status -> \"$ONAME\"."
    milestone_step dry
    exit 0
  fi
  if ! IID=$(gql 'mutation($pid:ID!,$cid:ID!){addProjectV2ItemById(input:{projectId:$pid,contentId:$cid}){item{id}}}' \
    -f pid="$PID" -f cid="$CONTENT_ID" --jq '.data.addProjectV2ItemById.item.id // empty' 2>&1); then
    refetch_once "$IID"
    die "failed to add $KIND #$NUM to board #$PROJECT: $IID"
  fi
  [[ -n "$IID" ]] || die "failed to add $KIND #$NUM to board #$PROJECT."
  echo "Added $KIND #$NUM to board #$PROJECT."
fi

if $DRY_RUN; then
  echo "[dry-run] would set $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT (item $IID)."
  milestone_step dry
  exit 0
fi

if ! OUT=$(gql 'mutation($pid:ID!,$iid:ID!,$fid:ID!,$oid:String!){updateProjectV2ItemFieldValue(input:{projectId:$pid,itemId:$iid,fieldId:$fid,value:{singleSelectOptionId:$oid}}){projectV2Item{id}}}' \
  -f pid="$PID" -f iid="$IID" -f fid="$FID" -f oid="$OID" --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id' 2>&1); then
  refetch_once "$OUT"
  die "move failed: $OUT"
fi
echo "Moved $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT."
milestone_step apply
