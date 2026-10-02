#!/usr/bin/env bash
# Phase 2: copy a template ProjectV2 to a new owner via `gh project copy`.
# Outputs JSON with the new project's id, number, and url.

set -euo pipefail

SRC_OWNER=""
SRC_NUMBER=""
TGT_OWNER=""
TITLE=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --source-owner <login> --source-number <n> --target-owner <login> --title <string>

Wraps \`gh project copy\` and emits the new project's metadata as JSON.

Flags:
  --source-owner <login>   Template project owner. Required.
  --source-number <n>      Template project number. Required.
  --target-owner <login>   New project owner. Required.
  --title <string>         New project title. Required.
  -h, --help               Show this help.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --source-owner) SRC_OWNER="$2"; shift 2 ;;
    --source-number) SRC_NUMBER="$2"; shift 2 ;;
    --target-owner) TGT_OWNER="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$SRC_OWNER" ] || { echo "Missing --source-owner" >&2; exit 2; }
[ -n "$SRC_NUMBER" ] || { echo "Missing --source-number" >&2; exit 2; }
[ -n "$TGT_OWNER" ] || { echo "Missing --target-owner" >&2; exit 2; }
[ -n "$TITLE" ] || { echo "Missing --title" >&2; exit 2; }

OUTPUT=$(gh project copy "$SRC_NUMBER" \
  --source-owner "$SRC_OWNER" \
  --target-owner "$TGT_OWNER" \
  --title "$TITLE" \
  --format json)

echo "$OUTPUT" | jq -e '.id and .number and .url' >/dev/null || {
  echo "gh project copy returned unexpected output:" >&2
  echo "$OUTPUT" >&2
  exit 1
}

echo "$OUTPUT"
