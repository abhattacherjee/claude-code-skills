#!/usr/bin/env bash
#
# board-move.sh — move a GitHub issue/PR's Project (v2) card to a target Status column.
#
# Mid-lifecycle companion to github-release-board-promote (which only does release -> Done).
# Reuses the proven projectsV2 discovery + Status-field + updateProjectV2ItemFieldValue
# pattern. Requires the gh CLI authenticated with the 'project' scope to apply a move.
#
set -euo pipefail

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
  -h, --help          This help.

EXAMPLES:
  board-move.sh --issue 28 --to "In Progress"
  board-move.sh --pr 31 --to "Development Complete"
  board-move.sh --issue 9 --to done --repo abhattacherjee/foo --project 7
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
    -h|--help) usage 0;;
    *) echo "Unknown argument: $1" >&2; usage 2;;
  esac
done

command -v gh >/dev/null || die "gh CLI not found."
command -v jq >/dev/null || die "jq not found."

# auth scope: read:project for discovery; project for mutation.
SCOPES=$(gh auth status 2>&1 | grep -i "Token scopes" || true)
if ! $LIST && ! $DRY_RUN; then
  case "$SCOPES" in
    *"'project'"*) ;;
    *) echo "Error: gh token lacks the 'project' scope (needed to modify a board)." >&2
       echo "Run: gh auth refresh -s project" >&2; exit 3;;
  esac
fi

# resolve repo
if [[ -z "$REPO" ]]; then
  REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner') || die "not in a GitHub repo; pass --repo owner/repo."
fi
OWNER=${REPO%/*}; NAME=${REPO#*/}

gql() { gh api graphql -f query="$1" "${@:2}"; }

# discover board
if [[ -z "$PROJECT" ]]; then
  BOARDS=$(gql 'query($o:String!,$n:String!){repository(owner:$o,name:$n){projectsV2(first:50){nodes{number title closed}}}}' \
    -F o="$OWNER" -F n="$NAME" --jq '[.data.repository.projectsV2.nodes[]|select(.closed==false)]')
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

PID=$(gql 'query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){projectV2(number:$p){id}}}' \
  -F o="$OWNER" -F n="$NAME" -F p="$PROJECT" --jq '.data.repository.projectV2.id // empty')
[[ -n "$PID" ]] || die "board #$PROJECT not found on $REPO."

# Status field + options (exact 'Status', else first single-select named like status)
FIELD_JSON=$(gql 'query($id:ID!){node(id:$id){... on ProjectV2{fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}' \
  -F id="$PID" --jq '.data.node.fields.nodes | map(select(.id!=null)) | (map(select((.name//"")|ascii_downcase=="status"))[0]) // empty')
[[ -n "$FIELD_JSON" ]] || die "no single-select 'Status' field on board #$PROJECT."
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
  echo "Error: --to \"$TO\" did not uniquely match a Status option. Available:" >&2
  echo "$FIELD_JSON" | jq -r '.options[]|"  - \(.name)"' >&2
  exit 1
fi
ONAME=$(echo "$FIELD_JSON" | jq -r --arg id "$OID" '.options[]|select(.id==$id).name')

if [[ -n "$ISSUE" ]]; then KIND=issue; NUM="$ISSUE"; else KIND=pullRequest; NUM="$PR"; fi
[[ "$NUM" =~ ^[0-9]+$ ]] || die "issue/PR number must be numeric (got: $NUM)."
CONTENT=$(gql "query(\$o:String!,\$n:String!,\$num:Int!){repository(owner:\$o,name:\$n){$KIND(number:\$num){id projectItems(first:50){nodes{id project{number}}}}}}" \
  -F o="$OWNER" -F n="$NAME" -F num="$NUM")
CONTENT_ID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.id // empty")
[[ -n "$CONTENT_ID" ]] || die "$KIND #$NUM not found on $REPO."
IID=$(echo "$CONTENT" | jq -r ".data.repository.$KIND.projectItems.nodes | map(select(.project.number==$PROJECT))[0].id // empty")

if [[ -z "$IID" ]]; then
  if $ADD; then
    IID=$(gql 'mutation($pid:ID!,$cid:ID!){addProjectV2ItemById(input:{projectId:$pid,contentId:$cid}){item{id}}}' \
      -F pid="$PID" -F cid="$CONTENT_ID" --jq '.data.addProjectV2ItemById.item.id // empty')
    [[ -n "$IID" ]] || die "failed to add $KIND #$NUM to board #$PROJECT."
    echo "Added $KIND #$NUM to board #$PROJECT."
  else
    die "$KIND #$NUM is not a card on board #$PROJECT. Re-run with --add to add it first."
  fi
fi

if $DRY_RUN; then
  echo "[dry-run] would set $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT (item $IID)."
  exit 0
fi

gql 'mutation($pid:ID!,$iid:ID!,$fid:ID!,$oid:String!){updateProjectV2ItemFieldValue(input:{projectId:$pid,itemId:$iid,fieldId:$fid,value:{singleSelectOptionId:$oid}}){projectV2Item{id}}}' \
  -F pid="$PID" -F iid="$IID" -F fid="$FID" -f oid="$OID" --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id' >/dev/null \
  && echo "Moved $KIND #$NUM -> \"$ONAME\" on $REPO board #$PROJECT."
