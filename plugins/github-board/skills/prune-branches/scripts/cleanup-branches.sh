#!/usr/bin/env bash
set -eu

# cleanup-branches.sh — Audit and clean stale git branches (local + remote)
#
# Identifies: merged feature branches, finished hotfix/release branches,
# orphan temp branches, superseded Dependabot branches, issue-tracked
# Dependabot PRs, and stale local tracking refs.
#
# Usage:
#   cleanup-branches.sh              # Dry-run (report only)
#   cleanup-branches.sh --delete     # Actually delete stale branches
#   cleanup-branches.sh --help       # Show usage

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=true

usage() {
  cat <<'EOF'
Usage: cleanup-branches.sh [OPTIONS]

Audit local and remote git branches for staleness, then optionally delete them.

Options:
  --delete    Actually delete stale branches (default: dry-run report only)
  --help, -h  Show this help message

Categories detected:
  1. Local branches whose remote tracking is [gone]
  2. Local branches from squash-merged PRs (verified via gh pr list)
  3. Remote hotfix/* and release/* branches already merged to main (with tags)
  4. Remote temp-* and temp-finish-* orphan branches (no open PR)
  5. Superseded Dependabot PRs (older version replaced by newer)
  6. Issue-tracked Dependabot PRs (triaged into GitHub issues, PR is stale)
  7. Stale local tracking refs (git fetch --prune)

Examples:
  cleanup-branches.sh              # See what would be cleaned
  cleanup-branches.sh --delete     # Clean everything

Requires: git, gh (GitHub CLI, authenticated), jq
EOF
  exit 0
}

# --- Parse args ---
for arg in "$@"; do
  case "$arg" in
    --delete) DRY_RUN=false ;;
    --help|-h) usage ;;
    *) echo "Unknown argument: $arg"; usage ;;
  esac
done

# --- Preflight ---
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo "ERROR: Not inside a git repository." >&2
  exit 1
fi

if ! command -v gh &>/dev/null; then
  echo "ERROR: gh (GitHub CLI) not found. Install: https://cli.github.com" >&2
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq not found (needed to match tracking issues). Install: brew install jq" >&2
  exit 1
fi

REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null) || {
  echo "ERROR: Could not determine GitHub repo. Run 'gh auth login' first." >&2
  exit 1
}
REPO_OWNER="${REPO%%/*}"
# Who may write a tracking issue: the repo owner, plus the logins in the optional config list
# prune_branches.tracking_issue_authors (e.g. a triage bot). No config means owner only. A
# bot is never trusted just for being a bot: any installed GitHub App can open issues.
. "$SCRIPT_DIR/../../../lib/config.sh"
if ! TRACKING_AUTHORS=$(gb_config_get prune_branches.tracking_issue_authors --lines --optional); then
  echo "ERROR: the github-board config is invalid (see above); nothing was changed." >&2
  exit 2
fi
AUTHORS_JSON=$(printf '%s\n%s\n' "$REPO_OWNER" "$TRACKING_AUTHORS" \
  | jq -R 'select(length > 0) | ascii_downcase' | jq -s 'unique')
CURRENT_BRANCH=$(git branch --show-current)

echo "=== Git Branch Cleanup Audit ==="
echo "Repo: $REPO"
echo "Current branch: $CURRENT_BRANCH"
echo "Mode: $($DRY_RUN && echo 'DRY RUN (use --delete to apply)' || echo 'DELETE')"
echo ""

DELETE_LOCAL=()
DELETE_REMOTE=()
CLOSE_PRS=()

# ─────────────────────────────────────────────────────────
# Category 1: Local branches with remote tracking [gone]
# ─────────────────────────────────────────────────────────
echo "--- Category 1: Local branches with remote [gone] ---"
while IFS= read -r line; do
  branch=$(echo "$line" | sed 's/^[* ]*//' | awk '{print $1}')
  # Skip protected branches
  [[ "$branch" == "main" || "$branch" == "develop" || "$branch" == "master" ]] && continue
  [[ "$branch" == "$CURRENT_BRANCH" ]] && continue
  echo "  STALE (local, remote gone): $branch"
  DELETE_LOCAL+=("$branch")
done < <(git branch -vv 2>/dev/null | grep ': gone]')

[[ ${#DELETE_LOCAL[@]} -eq 0 ]] && echo "  (none found)"
echo ""

# ─────────────────────────────────────────────────────────
# Category 2: Remote hotfix/release branches merged to main
# ─────────────────────────────────────────────────────────
echo "--- Category 2: Finished hotfix/release branches ---"
git fetch --prune origin &>/dev/null || true

for branch_ref in $(git branch -r 2>/dev/null | grep -E 'origin/(hotfix|release)/' | sed 's/^[ ]*//' ); do
  branch="${branch_ref#origin/}"
  # Check if merged into main
  if git merge-base --is-ancestor "$branch_ref" origin/main 2>/dev/null; then
    echo "  STALE (merged to main): $branch"
    DELETE_REMOTE+=("$branch")
  fi
done

[[ ${#DELETE_REMOTE[@]} -eq 0 ]] && echo "  (none found)"
echo ""

# ─────────────────────────────────────────────────────────
# Category 3: Orphan temp branches (no open PR)
# ─────────────────────────────────────────────────────────
echo "--- Category 3: Orphan temp branches ---"
for branch_ref in $(git branch -r 2>/dev/null | grep -E 'origin/(temp-|feature/temp-)' | sed 's/^[ ]*//'); do
  branch="${branch_ref#origin/}"
  open_prs=$(gh pr list --state open --head "$branch" --json number --jq 'length' 2>/dev/null || echo "0")
  if [[ "$open_prs" == "0" ]]; then
    echo "  ORPHAN (no open PR): $branch"
    DELETE_REMOTE+=("$branch")
  else
    echo "  ACTIVE (has open PR): $branch"
  fi
done

# Check for orphan temp branches at the end of Category 3 output
orphan_count=0
for branch_ref in $(git branch -r 2>/dev/null | grep -E 'origin/(temp-|feature/temp-)' | sed 's/^[ ]*//'); do
  orphan_count=$((orphan_count + 1))
done
[[ $orphan_count -eq 0 ]] && echo "  (none found)"
echo ""

# ─────────────────────────────────────────────────────────
# Category 4: Superseded Dependabot branches
# Uses temp files instead of associative arrays (bash 3.2 compat)
# ─────────────────────────────────────────────────────────
echo "--- Category 4: Superseded Dependabot PRs ---"

TMPDIR_CLEANUP=$(mktemp -d)
trap "rm -rf $TMPDIR_CLEANUP" EXIT

# Fetch all open Dependabot PRs: number|headRefName|title
gh pr list --state open --author "app/dependabot" \
  --json number,headRefName,title \
  --jq '.[] | "\(.number)|\(.headRefName)|\(.title)"' \
  2>/dev/null > "$TMPDIR_CLEANUP/dependabot_prs.txt" || true

# For each PR with a versioned branch name, extract dep_key and PR number
# Write: dep_key|pr_number|head_ref
while IFS='|' read -r number head_ref title; do
  number=$(echo "$number" | xargs)
  head_ref=$(echo "$head_ref" | xargs)

  # Strip dependabot prefix
  dep_path="${head_ref#dependabot/npm_and_yarn/}"
  last_segment="${dep_path##*/}"

  # Match name-X.Y.Z pattern
  if [[ "$last_segment" =~ ^(.+)-([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    dep_name="${BASH_REMATCH[1]}"
    dep_key="${dep_path%/*}/$dep_name"
    echo "${dep_key}|${number}|${head_ref}" >> "$TMPDIR_CLEANUP/versioned_prs.txt"
  fi
done < "$TMPDIR_CLEANUP/dependabot_prs.txt"

# Find superseded PRs: for each dep_key, the highest PR number wins
superseded_count=0
if [[ -f "$TMPDIR_CLEANUP/versioned_prs.txt" ]]; then
  # Get unique dep_keys
  cut -d'|' -f1 "$TMPDIR_CLEANUP/versioned_prs.txt" | sort -u > "$TMPDIR_CLEANUP/dep_keys.txt"

  while IFS= read -r dep_key; do
    # Get all PRs for this dep_key, sorted by PR number descending
    prs_for_key=$(grep "^${dep_key}|" "$TMPDIR_CLEANUP/versioned_prs.txt" | sort -t'|' -k2 -rn)
    pr_count=$(echo "$prs_for_key" | wc -l | tr -d ' ')

    if [[ "$pr_count" -gt 1 ]]; then
      # First line is the newest; rest are superseded
      newest_number=$(echo "$prs_for_key" | head -1 | cut -d'|' -f2)
      echo "$prs_for_key" | tail -n +2 | while IFS='|' read -r _key old_number old_ref; do
        echo "  SUPERSEDED: PR #$old_number ($old_ref) — newer: PR #$newest_number"
        # Write to file since we're in a subshell
        echo "${old_number}|${newest_number}" >> "$TMPDIR_CLEANUP/to_close.txt"
      done
      superseded_count=$((superseded_count + pr_count - 1))
    fi
  done < "$TMPDIR_CLEANUP/dep_keys.txt"
fi

# Read CLOSE_PRS from file (subshell wrote them)
if [[ -f "$TMPDIR_CLEANUP/to_close.txt" ]]; then
  while IFS='|' read -r pr_number newer_number; do
    CLOSE_PRS+=("${pr_number}|${newer_number}")
  done < "$TMPDIR_CLEANUP/to_close.txt"
fi

[[ $superseded_count -eq 0 ]] && echo "  (none found)"
echo ""

# ─────────────────────────────────────────────────────────
# Category 5: Issue-tracked Dependabot PRs
# Open Dependabot PRs whose updates are tracked through GitHub issues
# (created by dependabot-triage agent). The PR is stale because
# the work is being tracked/resolved via the issue instead. Only an issue by
# the repo owner (or an allowlisted login) that names the PR exactly
# (`PR #<n>` or its URL) counts.
# ─────────────────────────────────────────────────────────
echo "--- Category 5: Issue-tracked Dependabot PRs ---"

ISSUE_TRACKED_PRS=()
issue_tracked_count=0

# Re-read open Dependabot PRs (already fetched for Category 4)
if [[ -f "$TMPDIR_CLEANUP/dependabot_prs.txt" ]]; then
  while IFS='|' read -r number head_ref title; do
    number=$(echo "$number" | xargs)
    title=$(echo "$title" | xargs)

    # A tracking issue must name this PR exactly: the token `PR #<n>` (case-sensitive, at a
    # word boundary on both sides) or the PR's full URL, in its title or body. And it must be
    # written by the repo owner or a login in prune_branches.tracking_issue_authors. GitHub's search is fuzzy, so its
    # hits are only candidates; the filter below decides. There is deliberately no search by
    # package name: an issue that merely mentions the package says nothing about this PR, and
    # closing a PR on that evidence was a real defect.
    issue_refs=""
    if [[ "$number" =~ ^[0-9]+$ ]]; then
      if ! raw_issues=$(gh issue list --state all --search "PR #$number" --limit 100 \
          --json number,title,state,body,author 2>/dev/null); then
        echo "  WARN: could not search issues for PR #$number; leaving it open"
        continue
      fi
      issue_refs=$(printf '%s' "$raw_issues" | jq -r \
        --arg n "$number" --argjson authors "$AUTHORS_JSON" --arg url "https://github.com/$REPO/pull/$number" '
        .[]
        | select(((.title // "") + "\n" + (.body // ""))
                 | test("(^|[^A-Za-z0-9_])PR #" + $n + "([^0-9A-Za-z_]|$)")
                   or (index($url) as $i | $i != null
                       and ((.[($i + ($url | length)):] | test("^[0-9]")) | not)))
        | select(((.author.login // "") | ascii_downcase) as $a | $authors | index($a) != null)
        | "\(.number)|\(.title | gsub("[|\n\r]"; " "))|\(.state)"' 2>/dev/null) || {
        echo "  WARN: could not read the issue search for PR #$number; leaving it open"
        continue
      }
    fi

    # If we found tracking issues, this PR is issue-tracked
    if [[ -n "$issue_refs" ]]; then
      # Format issue references for the close comment
      issue_summary=""
      while IFS='|' read -r issue_num issue_title issue_state; do
        [[ -z "$issue_num" ]] && continue
        issue_summary="${issue_summary}  - #${issue_num} (${issue_state}): ${issue_title}\n"
      done <<< "$issue_refs"

      if [[ -n "$issue_summary" ]]; then
        echo "  ISSUE-TRACKED: PR #$number ($title)"
        echo "    Tracking issues:"
        echo -e "$issue_summary" | sed 's/^/    /'
        # Store: pr_number|issue_summary (newlines replaced with semicolons for storage)
        flat_issues=$(echo -e "$issue_summary" | tr '\n' ';' | sed 's/;$//')
        ISSUE_TRACKED_PRS+=("${number}|${flat_issues}")
        issue_tracked_count=$((issue_tracked_count + 1))
      fi
    fi
  done < "$TMPDIR_CLEANUP/dependabot_prs.txt"
fi

[[ $issue_tracked_count -eq 0 ]] && echo "  (none found)"
echo ""

# ─────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────
echo "=== Summary ==="
echo "  Local branches to delete:     ${#DELETE_LOCAL[@]}"
echo "  Remote branches to delete:    ${#DELETE_REMOTE[@]}"
echo "  Superseded Dependabot PRs:    ${#CLOSE_PRS[@]}"
echo "  Issue-tracked Dependabot PRs: ${#ISSUE_TRACKED_PRS[@]}"
echo ""

total=$((${#DELETE_LOCAL[@]} + ${#DELETE_REMOTE[@]} + ${#CLOSE_PRS[@]} + ${#ISSUE_TRACKED_PRS[@]}))
if [[ $total -eq 0 ]]; then
  echo "Nothing to clean up!"
  exit 0
fi

if $DRY_RUN; then
  echo "Run with --delete to apply these changes."
  exit 0
fi

# ─────────────────────────────────────────────────────────
# Execute deletions
# ─────────────────────────────────────────────────────────
echo "=== Executing cleanup ==="

# Delete local branches
for branch in ${DELETE_LOCAL[@]+"${DELETE_LOCAL[@]}"}; do
  # Try safe delete first, fall back to force delete after verifying PR merged
  if git branch -d "$branch" 2>/dev/null; then
    echo "  Deleted local: $branch"
  else
    # Check if it was squash-merged via a PR
    pr_state=$(gh pr list --state all --head "$branch" --json state --jq '.[0].state' 2>/dev/null || echo "")
    if [[ "$pr_state" == "MERGED" ]]; then
      git branch -D "$branch"
      echo "  Deleted local (squash-merged): $branch"
    else
      echo "  SKIPPED local (not verified merged): $branch"
    fi
  fi
done

# Delete remote branches
for branch in ${DELETE_REMOTE[@]+"${DELETE_REMOTE[@]}"}; do
  ref="heads/$branch"
  if gh api "repos/$REPO/git/refs/$ref" -X DELETE 2>/dev/null; then
    echo "  Deleted remote: $branch"
  else
    echo "  SKIPPED remote (already gone or protected): $branch"
  fi
done

# Close superseded Dependabot PRs
for entry in ${CLOSE_PRS[@]+"${CLOSE_PRS[@]}"}; do
  pr_number="${entry%%|*}"
  newer_pr="${entry##*|}"

  if gh pr close "$pr_number" --comment "Superseded by PR #$newer_pr (newer version). Closed by cleanup script." --delete-branch 2>/dev/null; then
    echo "  Closed PR #$pr_number (superseded by #$newer_pr)"
  else
    echo "  SKIPPED PR #$pr_number (could not close)"
  fi
done

# Close issue-tracked Dependabot PRs
for entry in ${ISSUE_TRACKED_PRS[@]+"${ISSUE_TRACKED_PRS[@]}"}; do
  pr_number="${entry%%|*}"
  issue_info="${entry#*|}"

  # Build a readable issue list for the close comment
  # issue_info is semicolon-separated lines like "  - #491 (OPEN): Migrate ESLint..."
  readable_issues=$(echo "$issue_info" | tr ';' '\n' | sed '/^$/d')

  close_comment="This Dependabot PR is tracked through GitHub issue(s) created during triage. The update will be handled through the issue workflow instead.

Tracking issues:
${readable_issues}

Closing this PR since the work is tracked via the issue(s) above. GitHub will auto-delete the branch.

---
*Closed by cleanup-branches.sh (Category 5: issue-tracked)*"

  if gh pr close "$pr_number" --comment "$close_comment" 2>/dev/null; then
    echo "  Closed PR #$pr_number (tracked via issues)"
  else
    echo "  SKIPPED PR #$pr_number (could not close)"
  fi
done

# Prune stale tracking refs
echo ""
echo "Pruning stale remote tracking refs..."
git fetch --prune origin 2>&1 | grep -E '^\s*-\s*\[deleted\]' || echo "  (no stale refs)"

echo ""
echo "=== Cleanup complete ==="
