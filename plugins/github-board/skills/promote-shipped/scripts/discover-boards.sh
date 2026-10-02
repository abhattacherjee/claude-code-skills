#!/usr/bin/env bash
# discover-boards.sh — List GitHub Projects V2 boards linked to a repo.
#
# Usage:
#   discover-boards.sh <owner> <repo> [--json] [--no-cache]
#     (no flag: human-readable; --json: JSON for scripting)
# The board list is cached for 7 days (~/.cache/github-board); --no-cache skips the cache.
# An empty list is never cached, so a board linked later shows up at once; a second board
# linked while one is cached shows up when the entry ages out (or with --no-cache).
#
# Exit codes: 0=ok (any number of boards, including 0), 2=usage, 3=auth, 4=api

set -eu

usage() {
  cat <<EOF
Usage: discover-boards.sh <owner> <repo> [--json] [--no-cache]

Lists Projects V2 boards linked to the given repository.

Examples:
  discover-boards.sh OWNER REPO
  discover-boards.sh OWNER REPO --json | jq

Requires: gh CLI authenticated with read:project scope.
  gh auth refresh -s read:project,project
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then usage; exit 0; fi
if [ $# -lt 2 ]; then usage >&2; exit 2; fi

OWNER="$1"
REPO="$2"
shift 2
JSON_MODE="false"
for arg in "$@"; do
  case "$arg" in
    --json) JSON_MODE="true" ;;
    --no-cache) export GB_NO_CACHE=1 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"

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

CACHE_KEY="promote-boards-$OWNER-$REPO"
if ! BOARDS=$(gb_cache_get "$CACHE_KEY"); then
  QUERY='query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    projectsV2(first:50) {
      nodes { id title number url closed }
    }
  }
}'

  # -f (not -F): owner/name are String!. -F does type inference, so an all-numeric
  # owner or repo name would be sent as an Int and rejected by the schema.
  RESPONSE=$(gh api graphql -f query="$QUERY" -f owner="$OWNER" -f name="$REPO" 2>&1) || {
    echo "ERROR: GraphQL query failed:" >&2
    echo "$RESPONSE" >&2
    exit 4
  }

  # Filter out closed boards and project the shape we want.
  BOARDS=$(echo "$RESPONSE" | jq '{
  owner: "'"$OWNER"'",
  repo: "'"$REPO"'",
  boards: [
    .data.repository.projectsV2.nodes[]
    | select(.closed == false)
    | {id, number, title, url}
  ]
}')
  # An empty list is never cached, so a board linked later shows up at once.
  if [ "$(echo "$BOARDS" | jq '.boards | length')" -gt 0 ]; then
    printf '%s' "$BOARDS" | gb_cache_put "$CACHE_KEY"
  fi
fi

if [ "$JSON_MODE" = "true" ]; then
  echo "$BOARDS"
  exit 0
fi

COUNT=$(echo "$BOARDS" | jq '.boards | length')
echo "Repository: $OWNER/$REPO"
echo "Open Projects V2 boards: $COUNT"
if [ "$COUNT" = "0" ]; then
  echo "(no boards — skill is a no-op for this repo)"
  exit 0
fi
echo ""
echo "$BOARDS" | jq -r '.boards[] | "  #\(.number)  \(.title)\n         \(.url)"'
