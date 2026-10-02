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

# refetch_once: when ids or options came from the cache, drop them and re-run this script once
# without reading the cache. A stale option id or a renamed column fails with text that names
# no node, so any failure counts. The re-run sets GB_CACHE_REFRESH, so it can never loop.
refetch_once() {
  if [[ "$CACHE_USED" == 1 && -z "${GB_CACHE_REFRESH:-}" ]]; then
    echo "Cached board ids for $REPO look stale; refetching once." >&2
    gb_cache_drop "$BOARDS_KEY"
    gb_cache_drop "$STATUS_KEY"
    GB_CACHE_REFRESH=1 exec bash "${BASH_SOURCE[0]}" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}
  fi
}

BOARDS_KEY="move-boards-$OWNER-$NAME"
STATUS_KEY=""
# discover board (cached; an empty list is never cached)
if [[ -z "$PROJECT" ]]; then
  if BOARDS=$(gb_cache_get "$BOARDS_KEY"); then
    CACHE_USED=1
  else
    BOARDS=$(gql 'query($o:String!,$n:String!){repository(owner:$o,name:$n){projectsV2(first:100){nodes{number title closed}}}}' \
      -F o="$OWNER" -F n="$NAME" --jq '[.data.repository.projectsV2.nodes[]|select(.closed==false)]')
    if [[ "$(echo "$BOARDS" | jq 'length')" -ge 1 ]]; then printf '%s' "$BOARDS" | gb_cache_put "$BOARDS_KEY"; fi
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

STATUS_KEY="move-status-$OWNER-$NAME-$PROJECT"
PID="" FIELD_JSON=""
if CACHED=$(gb_cache_get "$STATUS_KEY"); then
  CACHE_USED=1
  PID=$(echo "$CACHED" | jq -r '.pid // empty')
  FIELD_JSON=$(echo "$CACHED" | jq -c '.field // empty')
fi
if [[ -z "${PID:-}" || -z "${FIELD_JSON:-}" ]]; then
  PID=$(gql 'query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){projectV2(number:$p){id}}}' \
    -F o="$OWNER" -F n="$NAME" -F p="$PROJECT" --jq '.data.repository.projectV2.id // empty')
  [[ -n "$PID" ]] || die "board #$PROJECT not found on $REPO."
  # Status field + options (exact 'Status', else first single-select named like status)
  FIELD_JSON=$(gql 'query($id:ID!){node(id:$id){... on ProjectV2{fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}' \
    -F id="$PID" --jq '.data.node.fields.nodes | map(select(.id!=null)) | (map(select((.name//"")|ascii_downcase=="status"))[0]) // empty')
  [[ -n "$FIELD_JSON" ]] || die "no single-select 'Status' field on board #$PROJECT."
  jq -cn --arg pid "$PID" --argjson field "$FIELD_JSON" '{pid: $pid, field: $field}' | gb_cache_put "$STATUS_KEY"
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
CONTENT=$(gql "query(\$o:String!,\$n:String!,\$num:Int!){repository(owner:\$o,name:\$n){$KIND(number:\$num){id projectItems(first:100){nodes{id project{number}}}}}}" \
  -F o="$OWNER" -F n="$NAME" -F num="$NUM")
CONTENT_ID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.id // empty")
[[ -n "$CONTENT_ID" ]] || die "$KIND #$NUM not found on $REPO."
IID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.projectItems.nodes | map(select(.project.number==$PROJECT))[0].id // empty")

if [[ -z "$IID" ]]; then
  if ! $ADD; then
    die "$KIND #$NUM is not a card on board #$PROJECT. Re-run with --add to add it first."
  fi
  if $DRY_RUN; then
    echo "[dry-run] would add $KIND #$NUM to board #$PROJECT, then set Status -> \"$ONAME\"."
    exit 0
  fi
  if ! IID=$(gql 'mutation($pid:ID!,$cid:ID!){addProjectV2ItemById(input:{projectId:$pid,contentId:$cid}){item{id}}}' \
    -F pid="$PID" -F cid="$CONTENT_ID" --jq '.data.addProjectV2ItemById.item.id // empty' 2>&1); then
    refetch_once
    die "failed to add $KIND #$NUM to board #$PROJECT: $IID"
  fi
  [[ -n "$IID" ]] || die "failed to add $KIND #$NUM to board #$PROJECT."
  echo "Added $KIND #$NUM to board #$PROJECT."
fi

if $DRY_RUN; then
  echo "[dry-run] would set $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT (item $IID)."
  exit 0
fi

if ! OUT=$(gql 'mutation($pid:ID!,$iid:ID!,$fid:ID!,$oid:String!){updateProjectV2ItemFieldValue(input:{projectId:$pid,itemId:$iid,fieldId:$fid,value:{singleSelectOptionId:$oid}}){projectV2Item{id}}}' \
  -F pid="$PID" -F iid="$IID" -F fid="$FID" -f oid="$OID" --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id' 2>&1); then
  refetch_once
  die "move failed: $OUT"
fi
echo "Moved $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT."
