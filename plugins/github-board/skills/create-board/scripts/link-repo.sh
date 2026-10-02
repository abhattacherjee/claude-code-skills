#!/usr/bin/env bash
# Phase 3: link a ProjectV2 to a repository so the repo's issues/PRs can be added.

set -euo pipefail

PROJECT_ID=""
REPO=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --project-id <PVT_id> --repo <owner/name>

Calls linkProjectV2ToRepository.

Flags:
  --project-id <id>     ProjectV2 node id (e.g. PVT_kwHO...). Required.
  --repo <owner/name>   Target repository. Required.
  -h, --help            Show this help.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$PROJECT_ID" ] || { echo "Missing --project-id" >&2; exit 2; }
[ -n "$REPO" ] || { echo "Missing --repo" >&2; exit 2; }

REPO_ID=$(gh repo view "$REPO" --json id --jq .id 2>&1) || {
  echo "Could not resolve repo id for $REPO: $REPO_ID" >&2
  exit 1
}
[ -n "$REPO_ID" ] || { echo "Empty repo id returned for $REPO (auth/scope issue?)" >&2; exit 1; }

RESP=$(gh api graphql -f query='
mutation($pid: ID!, $rid: ID!) {
  linkProjectV2ToRepository(input: { projectId: $pid, repositoryId: $rid }) {
    repository { nameWithOwner }
  }
}' -F pid="$PROJECT_ID" -F rid="$REPO_ID")

if echo "$RESP" | jq -e '.errors' >/dev/null 2>&1; then
  echo "linkProjectV2ToRepository failed:" >&2
  echo "$RESP" | jq '.errors' >&2
  exit 1
fi

echo "$RESP"
