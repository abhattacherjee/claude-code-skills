#!/usr/bin/env bash
# Snapshot a ProjectV2's fields, views, and workflows to a JSON file.
# Used as Phase 1 input to the rest of the create-board pipeline.

set -euo pipefail

# Snapshots carry board structure and are written into a world-writable
# directory by default. Keep them owner-only.
umask 077

OWNER=""
NUMBER=""
OUT=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <login> --number <n> [--out <path>]

Writes a structural snapshot of a ProjectV2 to JSON. The snapshot is consumed
by copy-template.sh, sync-workflows.sh, and verify-board.sh.

Flags:
  --owner <login>   Project owner (user or org login). Required.
  --number <n>      Project number. Required.
  --out <path>      Output JSON path. Default: a fresh mktemp file, whose
                    path is printed on stdout.
  -h, --help        Show this help.

Exit codes:
  0  Snapshot written
  1  GraphQL or filesystem error
  2  Bad usage
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    --number) NUMBER="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$OWNER" ] || { echo "Missing --owner" >&2; exit 2; }
[ -n "$NUMBER" ] || { echo "Missing --number" >&2; exit 2; }
# Validate before either value reaches a path or a GraphQL variable.
[[ "$OWNER" =~ ^[A-Za-z0-9-]+$ ]] || { echo "Invalid --owner: $OWNER" >&2; exit 2; }
[[ "$NUMBER" =~ ^[0-9]+$ ]] || { echo "Invalid --number: $NUMBER" >&2; exit 2; }

# A predictable name in /tmp lets another local user pre-create the path as a
# symlink and have this script write through it. mktemp cannot be guessed.
# The path is echoed at the end, so callers capture it from stdout.
OUT="${OUT:-$(mktemp "${TMPDIR:-/tmp}/gh-board-template.XXXXXX")}"

QUERY='
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      id
      number
      title
      shortDescription
      readme
      public
      closed
      url
      views(first: 50) {
        nodes {
          id name number layout filter
          # Board columns. Read-only: no mutation sets these, so a copy is the
          # only way to reproduce them. Captured so verify/audit can prove the
          # copy actually carried them across.
          verticalGroupByFields(first: 10) { nodes { ... on ProjectV2FieldCommon { name } } }
          # Swimlanes. Read-only for the same reason.
          groupByFields(first: 10)         { nodes { ... on ProjectV2FieldCommon { name } } }
          sortByFields(first: 10)          { nodes { direction field { ... on ProjectV2FieldCommon { name } } } }
        }
      }
      workflows(first: 50) {
        nodes { id name number enabled }
      }
      fields(first: 50) {
        nodes {
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2IterationField {
            id name dataType
            configuration {
              duration startDay
              iterations { id title duration startDate }
            }
          }
          ... on ProjectV2SingleSelectField {
            id name dataType
            options { id name color description }
          }
        }
      }
    }
  }
}'

# Try user namespace first. Capture both stdout and stderr; check the response
# for a `.errors` envelope before trusting it (gh api graphql exits 0 even on
# GraphQL field-level errors like NOT_FOUND/FORBIDDEN).
RESP=$(gh api graphql -f query="$QUERY" -F login="$OWNER" -F number="$NUMBER" 2>&1) || {
  echo "GraphQL request failed for user/$OWNER: $RESP" >&2
  exit 1
}

# If the response has a `.errors` array, distinguish NOT_FOUND (try org fallback)
# from other errors (surface immediately).
if echo "$RESP" | jq -e '.errors' >/dev/null 2>&1; then
  ERR_TYPE=$(echo "$RESP" | jq -r '.errors[0].type // "UNKNOWN"')
  if [ "$ERR_TYPE" != "NOT_FOUND" ]; then
    echo "GraphQL error ($ERR_TYPE) reading user/$OWNER project $NUMBER:" >&2
    echo "$RESP" | jq '.errors' >&2
    exit 1
  fi
  RESP=""
fi

# If the response shape is null (could happen even without an errors envelope
# when the user exists but the project does not), fall back to the org query.
if [ -z "$RESP" ] || echo "$RESP" | jq -e '.data.user == null or .data.user.projectV2 == null' >/dev/null 2>&1; then
  ORG_QUERY="${QUERY/user(login: \$login)/organization(login: \$login)}"
  RESP=$(gh api graphql -f query="$ORG_QUERY" -F login="$OWNER" -F number="$NUMBER" 2>&1) || {
    echo "GraphQL request failed for orgs/$OWNER: $RESP" >&2
    exit 1
  }
  if echo "$RESP" | jq -e '.errors' >/dev/null 2>&1; then
    echo "GraphQL error reading project $OWNER/$NUMBER as user or organization:" >&2
    echo "$RESP" | jq '.errors' >&2
    exit 1
  fi
  if echo "$RESP" | jq -e '.data.organization == null or .data.organization.projectV2 == null' >/dev/null 2>&1; then
    echo "Project $OWNER/$NUMBER not found as user or organization. Check ownership and \`project\` scope." >&2
    exit 1
  fi
fi

# Stage in the SAME directory so the mv stays atomic (a rename across
# filesystems is a copy), but under a name nobody can predict either.
STAGE="$(mktemp "$(dirname "$OUT")/.gh-board-snap.XXXXXX")"
trap 'rm -f "$STAGE"' EXIT
echo "$RESP" > "$STAGE"
mv "$STAGE" "$OUT"
echo "$OUT"
