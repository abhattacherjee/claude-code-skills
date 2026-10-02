#!/usr/bin/env bash
# Phase 4: REPORT workflow state on a new ProjectV2.
#
# Measured 2026-09-16 (gh 2.96.0): `gh project copy` carries NO workflows. The
# six that appear on a copy are the defaults GitHub enables on every new
# project, including a bare `gh project create`. They are project-scoped and
# carry no repo filter, so nothing on them needs rewriting after a copy.
#
# "Auto-add to project" is the only repo-scoped workflow. It never survives a
# copy and no mutation can create or enable it (deleteProjectV2Workflow is the
# only workflow mutation), so it is checked EXPLICITLY here rather than derived
# from the template diff — the template deliberately does not have it enabled
# either, since it would be scoped to the wrong repo.

set -euo pipefail

SNAPSHOT=""
NEW_PROJECT_ID=""
NEW_OWNER=""
NEW_NUMBER=""
TGT_REPO=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --snapshot <path> --new-project-id <id> --new-owner <login> --new-number <n> --tgt-repo <owner/name>

Reports workflow state on the new project. ProjectV2 workflows cannot be
created or toggled via the public GraphQL API, so this reports only.

Two separate things are reported:
  missing_from_new  workflows enabled on the template but not on the new board
  auto_add_present  whether "Auto-add to project" is enabled. This is checked
                    explicitly, NOT derived from the template diff, because the
                    template does not carry it either.

Flags:
  --snapshot <path>       Template snapshot JSON from inspect-template.sh
  --new-project-id <id>   New project node id
  --new-owner <login>     New project owner login (for workflow lookup)
  --new-number <n>        New project number
  --tgt-repo <owner/name> Target repo string to rewrite to
  -h, --help              Show this help.

Output: JSON with enabled_now, missing_from_new, auto_add_present,
auto_add_filter, ui_url, target_repo, note.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --new-project-id) NEW_PROJECT_ID="$2"; shift 2 ;;
    --new-owner) NEW_OWNER="$2"; shift 2 ;;
    --new-number) NEW_NUMBER="$2"; shift 2 ;;
    --tgt-repo) TGT_REPO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -f "$SNAPSHOT" ] || { echo "Snapshot not found: $SNAPSHOT" >&2; exit 2; }
[ -n "$NEW_PROJECT_ID" ] || { echo "Missing --new-project-id" >&2; exit 2; }
[ -n "$NEW_OWNER" ] || { echo "Missing --new-owner" >&2; exit 2; }
[ -n "$NEW_NUMBER" ] || { echo "Missing --new-number" >&2; exit 2; }
[ -n "$TGT_REPO" ] || { echo "Missing --tgt-repo" >&2; exit 2; }

# Fetch new project's current workflows — check for .errors before trusting the
# response (gh api graphql exits 0 even on GraphQL field-level errors).
WF_QUERY='
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      workflows(first: 50) { nodes { id name enabled } }
    }
  }
}'
WF_RESP=$(gh api graphql -f query="$WF_QUERY" -F login="$NEW_OWNER" -F number="$NEW_NUMBER" 2>&1) || {
  echo "GraphQL request failed for user/$NEW_OWNER: $WF_RESP" >&2
  exit 1
}

if echo "$WF_RESP" | jq -e '.errors' >/dev/null 2>&1; then
  ERR_TYPE=$(echo "$WF_RESP" | jq -r '.errors[0].type // "UNKNOWN"')
  if [ "$ERR_TYPE" != "NOT_FOUND" ]; then
    echo "GraphQL error ($ERR_TYPE) reading workflows for user/$NEW_OWNER project $NEW_NUMBER:" >&2
    echo "$WF_RESP" | jq '.errors' >&2
    exit 1
  fi
  WF_RESP=""
fi

if [ -z "$WF_RESP" ] || echo "$WF_RESP" | jq -e '.data.user == null or .data.user.projectV2 == null' >/dev/null 2>&1; then
  ORG_WF_QUERY='
query($login: String!, $number: Int!) {
  organization(login: $login) {
    projectV2(number: $number) {
      workflows(first: 50) { nodes { id name enabled } }
    }
  }
}'
  WF_RESP=$(gh api graphql -f query="$ORG_WF_QUERY" -F login="$NEW_OWNER" -F number="$NEW_NUMBER" 2>&1) || {
    echo "GraphQL request failed for orgs/$NEW_OWNER: $WF_RESP" >&2
    exit 1
  }
  if echo "$WF_RESP" | jq -e '.errors' >/dev/null 2>&1; then
    echo "GraphQL error reading workflows for project $NEW_OWNER/$NEW_NUMBER as user or organization:" >&2
    echo "$WF_RESP" | jq '.errors' >&2
    exit 1
  fi
  if echo "$WF_RESP" | jq -e '.data.organization == null or .data.organization.projectV2 == null' >/dev/null 2>&1; then
    echo "Project $NEW_OWNER/$NEW_NUMBER not found as user or organization. Check ownership and \`project\` scope." >&2
    exit 1
  fi
fi

NEW_WORKFLOWS=$(echo "$WF_RESP" | jq '.data.user.projectV2.workflows.nodes // .data.organization.projectV2.workflows.nodes')

# Write to a temp file with proper cleanup.
TMPFILE=$(mktemp "${TMPDIR:-/tmp}/gh-board-new-workflows.XXXXXX")
trap 'rm -f "$TMPFILE"' EXIT
echo "$NEW_WORKFLOWS" > "$TMPFILE"

# Detect owner kind so the UI URL is correct (orgs use /orgs/<login>/, users use /users/<login>/).
if gh api "/users/${NEW_OWNER}" --jq '.type' 2>/dev/null | grep -qx "Organization"; then
  UI_URL="https://github.com/orgs/${NEW_OWNER}/projects/${NEW_NUMBER}/workflows"
else
  UI_URL="https://github.com/users/${NEW_OWNER}/projects/${NEW_NUMBER}/workflows"
fi

# Build sorted JSON arrays of enabled workflow names from template and new project.
TEMPLATE_ENABLED=$(jq -c '[
  (.data.user.projectV2.workflows.nodes // .data.organization.projectV2.workflows.nodes // [])
  | .[] | select(.enabled == true) | .name
] | sort' "$SNAPSHOT")

NEW_ENABLED=$(jq -c '[.[] | select(.enabled == true) | .name] | sort' "$TMPFILE")

# Compute missing = template_enabled - new_enabled (set difference).
MISSING=$(jq -cn --argjson tmpl "$TEMPLATE_ENABLED" --argjson new "$NEW_ENABLED" '
  [$tmpl[] | select(. as $n | $new | index($n) | not)]
')

# "Auto-add to project" is checked explicitly, not via the template diff: the
# template does not enable it either, so a diff would always report it clean.
AUTO_ADD_NAME="Auto-add to project"
AUTO_ADD_PRESENT=$(echo "$NEW_ENABLED" | jq --arg n "$AUTO_ADD_NAME" 'index($n) != null')
AUTO_ADD_FILTER="repo:${TGT_REPO} is:issue,pr is:open"

# Print a stderr line per missing workflow.
echo "$MISSING" | jq -r '.[]' | while read -r NAME; do
  echo "  MANUAL: $NAME — enable at $UI_URL" >&2
done

if [ "$AUTO_ADD_PRESENT" != "true" ]; then
  echo "  MANUAL: $AUTO_ADD_NAME — enable at $UI_URL with filter: $AUTO_ADD_FILTER" >&2
fi

jq -n \
  --argjson enabled_now "$NEW_ENABLED" \
  --argjson missing "$MISSING" \
  --argjson auto_add_present "$AUTO_ADD_PRESENT" \
  --arg auto_add_name "$AUTO_ADD_NAME" \
  --arg auto_add_filter "$AUTO_ADD_FILTER" \
  --arg ui "$UI_URL" \
  --arg tgt "$TGT_REPO" \
  '{
     enabled_now: $enabled_now,
     missing_from_new: $missing,
     auto_add_name: $auto_add_name,
     auto_add_present: $auto_add_present,
     auto_add_filter: $auto_add_filter,
     ui_url: $ui,
     target_repo: $tgt,
     note: "gh project copy carries no workflows; the six on a new board are GitHub defaults with no repo filter. Only \"Auto-add to project\" is repo-scoped, and no mutation can create or enable it — deleteProjectV2Workflow is the only workflow mutation. Enable it in the web UI."
   }'
