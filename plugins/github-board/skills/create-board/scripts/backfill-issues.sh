#!/usr/bin/env bash
# backfill-issues.sh — Add existing issues (and optionally PRs) from a repo to a GitHub ProjectV2 board.
# Usage: backfill-issues.sh --project <num> --target-owner <login> --repo <owner/name> [options]

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --project <num> --target-owner <login> --repo <owner/name> [options]

Required:
  --project <num>           ProjectV2 number to add items to
  --target-owner <login>    Owner (user or org) of the project
  --repo <owner/name>       Repository to pull issues from

Optional:
  --state <open|closed|all> Issue state filter (default: open)
  --limit <N>               Max issues to fetch (default: 200)
  --include-prs             Also add open PRs (default: off)
  --help|-h                 Show this help

Exit codes:
  0  All items added successfully (or nothing to add)
  1  One or more items failed to add, or the issue/PR list could not be read
EOF
}

# Defaults
PROJECT_NUM=""
TARGET_OWNER=""
REPO=""
STATE="open"
LIMIT=200
INCLUDE_PRS=false

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)       PROJECT_NUM="$2";   shift 2 ;;
    --target-owner)  TARGET_OWNER="$2";  shift 2 ;;
    --repo)          REPO="$2";          shift 2 ;;
    --state)         STATE="$2";         shift 2 ;;
    --limit)         LIMIT="$2";         shift 2 ;;
    --include-prs)   INCLUDE_PRS=true;   shift   ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Validate required args
if [[ -z "$PROJECT_NUM" || -z "$TARGET_OWNER" || -z "$REPO" ]]; then
  echo "Error: --project, --target-owner, and --repo are all required." >&2
  usage >&2
  exit 2
fi

echo "Fetching issues from ${REPO} (state=${STATE}, limit=${LIMIT})..."
URLS=()

# Fetch issues. The list is captured first, never read through `< <(...)`: set -e cannot see
# a failure inside process substitution, so a 401 used to look like an empty repo.
if ! LIST=$(gh issue list \
  --repo "$REPO" \
  --state "$STATE" \
  --limit "$LIMIT" \
  --json url \
  --jq '.[].url'); then
  echo "Error: could not list issues from ${REPO} (see above); nothing was added." >&2
  exit 1
fi
while IFS= read -r url; do
  [[ -n "$url" ]] && URLS+=("$url")
done <<<"$LIST"

# Optionally fetch PRs
if [[ "$INCLUDE_PRS" == true ]]; then
  echo "Fetching PRs from ${REPO} (state=${STATE}, limit=${LIMIT})..."
  if ! LIST=$(gh pr list \
    --repo "$REPO" \
    --state "$STATE" \
    --limit "$LIMIT" \
    --json url \
    --jq '.[].url'); then
    echo "Error: could not list PRs from ${REPO} (see above); nothing was added." >&2
    exit 1
  fi
  while IFS= read -r url; do
    [[ -n "$url" ]] && URLS+=("$url")
  done <<<"$LIST"
fi

TOTAL=${#URLS[@]}
if [[ "$TOTAL" -eq 0 ]]; then
  echo "No items found to backfill."
  echo "Backfilled 0 items (0 added, 0 failed) to project #${PROJECT_NUM}."
  exit 0
fi

echo "Adding ${TOTAL} item(s) to project #${PROJECT_NUM} (owner: ${TARGET_OWNER})..."

ADDED=0
FAILED=0

for url in "${URLS[@]}"; do
  if gh project item-add "$PROJECT_NUM" --owner "$TARGET_OWNER" --url "$url" > /dev/null 2>&1; then
    ADDED=$((ADDED + 1))
  else
    echo "  WARN: failed to add ${url}" >&2
    FAILED=$((FAILED + 1))
  fi
done

# item-add can exit 0 and still not land (seen 2026-10-02 on a board copied
# seconds earlier: "4 added", board empty). Read the board back; re-add once.
board_urls() {
  gh project item-list "$PROJECT_NUM" --owner "$TARGET_OWNER" --limit 1000 \
    --format json --jq '.items[].content.url'
}
missing_urls() {
  local on_board
  on_board=$(board_urls) || { echo "  WARN: could not read project #${PROJECT_NUM} back" >&2; printf '%s\n' "${URLS[@]}"; return; }
  for url in "${URLS[@]}"; do
    grep -qxF "$url" <<<"$on_board" || echo "$url"
  done
}
MISSING=$(missing_urls)
if [[ -n "$MISSING" ]]; then
  echo "  $(wc -l <<<"$MISSING" | tr -d ' ') item(s) not on the board after add; retrying once..." >&2
  sleep "${BACKFILL_RETRY_SLEEP:-5}"
  while IFS= read -r url; do
    gh project item-add "$PROJECT_NUM" --owner "$TARGET_OWNER" --url "$url" > /dev/null 2>&1
  done <<<"$MISSING"
  MISSING=$(missing_urls)
fi
if [[ -n "$MISSING" ]]; then
  NMISS=$(wc -l <<<"$MISSING" | tr -d ' ')
  while IFS= read -r url; do echo "  WARN: not on board: ${url}" >&2; done <<<"$MISSING"
  ADDED=$((TOTAL - FAILED - NMISS)); (( ADDED < 0 )) && ADDED=0
  FAILED=$((TOTAL - ADDED))
fi

echo "Backfilled ${TOTAL} items (${ADDED} added, ${FAILED} failed) to project #${PROJECT_NUM}."

if [[ "$FAILED" -gt 0 ]]; then
  exit 1
fi
exit 0
