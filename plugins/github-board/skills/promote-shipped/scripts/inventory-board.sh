#!/usr/bin/env bash
# inventory-board.sh — Dump Projects V2 board items, fields, and linked content.
#
# Usage:
#   inventory-board.sh --board-id <PVT_xxx>           # JSON inventory
#   inventory-board.sh --board-id <PVT_xxx> --human   # readable summary
#
# Outputs (JSON mode):
#   {
#     "project": {"id":"PVT_...", "title":"...", "number":N},
#     "statusField": {"id":"PVTSSF_...", "name":"Status",
#                     "options":[{"id":"...","name":"Done"}, ...],
#                     "doneOptionId":"..." or null},
#     "items": [
#       {"itemId":"PVTI_...", "status":"Dev Complete", "statusOptionId":"...",
#        "contentType":"Issue|PullRequest|DraftIssue",
#        "issue":{"number":N,"state":"CLOSED","stateReason":"COMPLETED|NOT_PLANNED",
#                 "url":"...","title":"...",
#                 "linkedPRs":[{"number":N,"merged":true,"baseRefName":"develop",...}]}}
#
# NOTE: linkedPRs uses includeClosedPrs:true, so it carries UNMERGED linked PRs too
# (each tagged with .merged / .state). find-promotable.sh relies on that to tell
# "no PR exists at all" apart from "a PR exists but hasn't merged" — do not narrow
# this to merged-only without updating that classifier.
#     ]
#   }
#
# Exit codes: 0=ok, 2=usage, 3=auth, 4=api, 5=no-status-field

set -eu
. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"

usage() {
  cat <<EOF
Usage: inventory-board.sh --board-id <PVT_xxx> [--human]

Pages through all items on the board (handles >100 items via cursor pagination).
Resolves linked content (Issue/PR), the Status field, and PRs that closed each issue.

Examples:
  inventory-board.sh --board-id PVT_kwHOAA... > /tmp/board.json
  inventory-board.sh --board-id PVT_kwHOAA... --human

Pass the board ID from discover-boards.sh, not the project number.
EOF
}

[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { usage; exit 0; }

BOARD_ID=""
HUMAN="false"
while [ $# -gt 0 ]; do
  case "$1" in
    --board-id)
      # Without this, `shift 2` with one arg left returns non-zero and `set -e`
      # exits 1 silently — no usage, no message. Same guard as --release-tag in
      # apply-promotions.sh and --base in find-promotable.sh.
      [ $# -ge 2 ] || { echo "ERROR: --board-id needs a value" >&2; usage >&2; exit 2; }
      BOARD_ID="$2"; shift 2 ;;
    --human) HUMAN="true"; shift ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -z "$BOARD_ID" ] && { usage >&2; exit 2; }

# Pre-flight: `read:project` on the account and host this run will query.
#
# The invocation is IDENTICAL in all three scripts (discover-boards.sh,
# inventory-board.sh, apply-promotions.sh) and must stay that way —
# test_scope_preflight_is_identical_across_scripts pins it. It drifted once:
# --active/--hostname went into the write path only, leaving these two passing
# whenever an unrelated GHES login held the scope.
#   --hostname  `gh auth status` reports on EVERY known host, and `gh api graphql`
#               talks to $GH_HOST (default github.com). Ask about that host only.
#   --active    one host can hold several accounts; only the active one is used.
SCOPES_LINE=$(gh auth status --active --hostname "${GH_HOST:-github.com}" 2>&1 \
              | grep -i "Token scopes" || true)
if [ -z "$SCOPES_LINE" ] || echo "$SCOPES_LINE" | grep -Eqi "scopes:[[:space:]]*('?none'?)?[[:space:]]*$"; then
  # Unreadable is not absent: a fine-grained PAT carries permissions rather than
  # OAuth scopes and reports "none"; a bare GH_TOKEN often prints no scopes line.
  # Both can read Projects, and `gh auth refresh` cannot fix either, so blocking
  # here would reject a valid setup with remediation that cannot work. Proceed and
  # let the query itself report a real permission problem.
  echo "WARN: could not read OAuth scopes for the active account (fine-grained PAT" >&2
  echo "      or GH_TOKEN?). 'read:project' is UNVERIFIED — if the token cannot read" >&2
  echo "      Projects, the query below fails and says so." >&2
elif ! echo "$SCOPES_LINE" | grep -Eq '(^|[^:[:alnum:]_-])(read:)?project([^:[:alnum:]_-]|$)'; then
  echo "ERROR: gh CLI lacks the 'read:project' scope (found:${SCOPES_LINE#*:})." >&2
  echo "OAuth login:    gh auth refresh -s read:project,project" >&2
  echo "Personal token: grant the token Projects read access in GitHub settings;" >&2
  echo "                gh auth refresh cannot change a PAT's permissions." >&2
  exit 3
fi

# Fetch project metadata + status field
META_QUERY='query($id:ID!) {
  node(id:$id) {
    ... on ProjectV2 {
      id
      title
      number
      fields(first:50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
  }
}'

# -f (not -F) for id/cursor throughout: both are ID!/String! and -F would type-infer.
META=$(gh api graphql -f query="$META_QUERY" -f id="$BOARD_ID" 2>&1) || {
  echo "ERROR: meta query failed: $META" >&2
  if echo "$META" | grep -Eq 'Could not resolve to (a|an) [A-Za-z0-9]+ with|NOT_FOUND'; then
    gb_cache_drop_containing "$BOARD_ID"
    echo "       Dropped any cached board list naming this id; re-run discover-boards.sh to refetch." >&2
  fi
  exit 4
}

PROJECT=$(echo "$META" | jq '.data.node | {id, title, number}')

# gh exits 0 on a GraphQL response whose `node` is null (wrong id, a non-ProjectV2
# node, or no access). Without this the run limps on to the "no Status field"
# error, which points at the board instead of at the id.
if [ -z "$PROJECT" ] || [ "$PROJECT" = "null" ] || [ "$(echo "$PROJECT" | jq -r '.id // "null"')" = "null" ]; then
  echo "ERROR: board id '$BOARD_ID' did not resolve to a ProjectV2 node." >&2
  echo "       Check the id (discover-boards.sh emits it) and your read:project access." >&2
  echo "       Response: $(echo "$META" | tr '\n' ' ' | cut -c1-300)" >&2
  gb_cache_drop_containing "$BOARD_ID"
  echo "       Dropped any cached board list naming this id; re-run discover-boards.sh to refetch." >&2
  exit 4
fi

# Identify the Status field. Prefer literal name "Status" (case-insensitive),
# else the first single-select field that contains a "Done"-ish option.
STATUS_FIELD=$(echo "$META" | jq '
  .data.node.fields.nodes
  | map(select(.id != null))
  | (map(select((.name // "") | ascii_downcase == "status"))[0] //
     map(select(.options // [] | any(.name | ascii_downcase | test("done|released|shipped"))))[0])
  // null
')

if [ "$STATUS_FIELD" = "null" ]; then
  echo "ERROR: board has no Status (single-select) field with a Done-like option." >&2
  exit 5
fi

DONE_OPTION_ID=$(echo "$STATUS_FIELD" | jq -r '
  .options
  | (map(select(.name == "Done"))[0].id //
     map(select(.name | ascii_downcase | test("^(done|✅ ?done|released|shipped)$")))[0].id //
     map(select(.name | ascii_downcase | test("done|released|shipped")))[0].id //
     null)
')

[ -z "$DONE_OPTION_ID" ] && DONE_OPTION_ID="null"

# --arg name is `doneid`, not `done`: shellcheck reads a bare `done` here as the
# loop keyword (SC1010) even though it is a jq variable name.
# doneOptionName travels with the id: tier 3 of the resolver is a bare substring
# match on done|released|shipped, on boards whose real columns include "Done in
# develop", and every human surface downstream printed only the opaque id.
STATUS_FIELD_ENRICHED=$(echo "$STATUS_FIELD" | jq --arg doneid "$DONE_OPTION_ID" '
  ($doneid | if . == "null" then null else . end) as $d
  | . + {doneOptionId: $d,
         doneOptionName: ([(.options // [])[] | select(.id == $d) | .name][0] // null)}')

# Page through items (max 100 per page)
ITEMS_QUERY='query($id:ID!, $cursor:String) {
  node(id:$id) {
    ... on ProjectV2 {
      items(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first:30) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { id name } }
                name
                optionId
              }
            }
          }
          content {
            __typename
            ... on Issue {
              number
              title
              state
              stateReason
              url
              repository { nameWithOwner }
              milestone { number title state }
              closedByPullRequestsReferences(first:10, includeClosedPrs:true) {
                pageInfo { hasNextPage }
                nodes {
                  number title url merged mergedAt baseRefName state
                  mergeCommit { oid }
                  repository { nameWithOwner }
                }
              }
            }
            ... on PullRequest {
              number
              title
              state
              url
              merged
              mergedAt
              baseRefName
              mergeCommit { oid }
              repository { nameWithOwner }
              milestone { number title state }
            }
            ... on DraftIssue { title }
          }
        }
      }
    }
  }
}'

ALL_NODES="[]"
CURSOR=""
PAGE=1
while : ; do
  if [ -z "$CURSOR" ]; then
    PAGE_RESP=$(gh api graphql -f query="$ITEMS_QUERY" -f id="$BOARD_ID" 2>&1) || {
      echo "ERROR: items page $PAGE failed: $PAGE_RESP" >&2; exit 4;
    }
  else
    PAGE_RESP=$(gh api graphql -f query="$ITEMS_QUERY" -f id="$BOARD_ID" -f cursor="$CURSOR" 2>&1) || {
      echo "ERROR: items page $PAGE failed: $PAGE_RESP" >&2; exit 4;
    }
  fi
  PAGE_NODES=$(echo "$PAGE_RESP" | jq '.data.node.items.nodes')
  # Same null-node hazard as the meta query: a null here would make the jq below
  # fail with a type error mid-pagination, or (worse) silently contribute nothing.
  if [ -z "$PAGE_NODES" ] || [ "$PAGE_NODES" = "null" ]; then
    echo "ERROR: items page $PAGE returned no node for board '$BOARD_ID'." >&2
    echo "       Response: $(echo "$PAGE_RESP" | tr '\n' ' ' | cut -c1-300)" >&2
    exit 4
  fi
  ALL_NODES=$(jq -n --argjson a "$ALL_NODES" --argjson b "$PAGE_NODES" '$a + $b')
  HAS_NEXT=$(echo "$PAGE_RESP" | jq -r '.data.node.items.pageInfo.hasNextPage')
  CURSOR=$(echo "$PAGE_RESP" | jq -r '.data.node.items.pageInfo.endCursor')
  [ "$HAS_NEXT" != "true" ] && break
  PAGE=$((PAGE + 1))
done

STATUS_FIELD_ID=$(echo "$STATUS_FIELD_ENRICHED" | jq -r '.id')

# Project items into a clean shape
ITEMS=$(echo "$ALL_NODES" | jq --arg sfid "$STATUS_FIELD_ID" '
  map(
    . as $node
    | (.fieldValues.nodes // []) as $fvs
    | ($fvs | map(select(.field.id == $sfid))[0]) as $sv
    | (.content // {}) as $c
    | {
        itemId: .id,
        status: ($sv.name // null),
        statusOptionId: ($sv.optionId // null),
        contentType: ($c.__typename // "Empty"),
        issue: (
          if $c.__typename == "Issue" then {
            number: $c.number,
            title: $c.title,
            state: $c.state,
            stateReason: ($c.stateReason // null),
            url: $c.url,
            repo: ($c.repository.nameWithOwner // null),
            milestone: ($c.milestone // null),
            linkedPRsTruncated: ($c.closedByPullRequestsReferences.pageInfo.hasNextPage // false),
            linkedPRs: [
              ($c.closedByPullRequestsReferences.nodes // [])[]
              | {number, title, url, merged, mergedAt, baseRefName, state,
                 mergeCommitOid: (.mergeCommit.oid // null),
                 repo: (.repository.nameWithOwner // null)}
            ]
          } else null end
        ),
        pullRequest: (
          if $c.__typename == "PullRequest" then {
            number: $c.number,
            title: $c.title,
            state: $c.state,
            url: $c.url,
            merged: $c.merged,
            mergedAt: $c.mergedAt,
            baseRefName: $c.baseRefName,
            mergeCommitOid: ($c.mergeCommit.oid // null),
            repo: ($c.repository.nameWithOwner // null),
            milestone: ($c.milestone // null)
          } else null end
        ),
        draftTitle: (if $c.__typename == "DraftIssue" then $c.title else null end)
      }
  )
')

OUT=$(jq -n \
  --argjson project "$PROJECT" \
  --argjson statusField "$STATUS_FIELD_ENRICHED" \
  --argjson items "$ITEMS" \
  '{project: $project, statusField: $statusField, items: $items}')

# Of the three unpaginated `first:` caps in this query, only this one can change a
# CLASSIFICATION: linkedPRs feeds .linkedPRCount, which is what separates a
# promoting "nopr" from a held "hold-unmerged-pr", and a truncated set can hide the
# merged PR entirely. The other two are left silent on purpose — a repo with >50
# linked boards or a board with >30 field values is not a real shape, and warning
# about them would be noise. Truncation here fails safe (fewer PRs seen -> the
# fallback discovery runs, and the ancestry guard still gates promotion) but it is
# worth saying out loud.
TRUNCATED=$(echo "$OUT" | jq -r '[.items[] | select(.issue.linkedPRsTruncated == true) | .issue.number] | join(", ")')
if [ -n "$TRUNCATED" ]; then
  echo "WARN: issue(s) $TRUNCATED have more than 10 linked PRs; only the first 10" >&2
  echo "      were read. Classification for those issues is based on a partial set." >&2
fi

if [ "$HUMAN" = "true" ]; then
  echo "$OUT" | jq -r '
    "Project: \(.project.title) (#\(.project.number))",
    "Status field: \(.statusField.name)  Done column: \(.statusField.doneOptionName // "(name unknown)") [\(.statusField.doneOptionId // "MISSING")]",
    "Total items: \(.items | length)",
    "",
    "Status breakdown:",
    (.items | group_by(.status) | map({status: (.[0].status // "(no status)"), count: length}) | .[] | "  \(.count | tostring | .[0:4]) | \(.status)"),
    "",
    "Item types:",
    (.items | group_by(.contentType) | map({type: .[0].contentType, count: length}) | .[] | "  \(.count | tostring | .[0:4]) | \(.type)")
  '
else
  echo "$OUT"
fi
