#!/usr/bin/env bash
#
# git-flow-status.sh — Git Flow status diagnostic for any repository
#
# Usage:
#   git-flow-status.sh [--json] [--help]
#
# Detects Git Flow branch structure, shows sync status, active branches,
# version tags, and provides actionable recommendations.
#
# Exit codes:
#   0 — Success
#   1 — Error (not a git repo, no Git Flow structure)
#   2 — Usage error

set -eu

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

usage() {
  cat <<'EOF'
Usage: git-flow-status.sh [OPTIONS]

Options:
  --json       Output as JSON (for agent consumption)
  --help, -h   Show this help message

Examples:
  git-flow-status.sh            # Human-readable status
  git-flow-status.sh --json     # JSON for programmatic use
EOF
  exit 0
}

die() { echo "ERROR: $1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUTPUT=true; shift ;;
    --help|-h) usage ;;
    *) die "Unknown option: $1. Use --help for usage."; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

git rev-parse --is-inside-work-tree &>/dev/null || die "Not inside a git repository"

# Check for Git Flow structure (main + develop)
MAIN_BRANCH=""
for candidate in main master; do
  if git show-ref --verify --quiet "refs/heads/$candidate" 2>/dev/null || \
     git show-ref --verify --quiet "refs/remotes/origin/$candidate" 2>/dev/null; then
    MAIN_BRANCH="$candidate"
    break
  fi
done

DEVELOP_EXISTS=false
if git show-ref --verify --quiet "refs/heads/develop" 2>/dev/null || \
   git show-ref --verify --quiet "refs/remotes/origin/develop" 2>/dev/null; then
  DEVELOP_EXISTS=true
fi

# ---------------------------------------------------------------------------
# Gather data
# ---------------------------------------------------------------------------

CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "HEAD (detached)")
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")

# Branch type detection
BRANCH_TYPE="other"
BRANCH_ICON="📁"
MERGE_TARGET=""
case "$CURRENT_BRANCH" in
  main|master)
    BRANCH_TYPE="production"
    BRANCH_ICON="🏠"
    ;;
  develop)
    BRANCH_TYPE="integration"
    BRANCH_ICON="🔀"
    ;;
  feature/*)
    BRANCH_TYPE="feature"
    BRANCH_ICON="🌿"
    MERGE_TARGET="develop"
    ;;
  release/*)
    BRANCH_TYPE="release"
    BRANCH_ICON="🚀"
    MERGE_TARGET="main + develop"
    ;;
  hotfix/*)
    BRANCH_TYPE="hotfix"
    BRANCH_ICON="🔥"
    MERGE_TARGET="main + develop"
    ;;
esac

# Sync status
AHEAD=0
BEHIND=0
if git rev-parse --abbrev-ref '@{upstream}' &>/dev/null; then
  AHEAD=$(git rev-list '@{upstream}..HEAD' --count 2>/dev/null || echo 0)
  BEHIND=$(git rev-list 'HEAD..@{upstream}' --count 2>/dev/null || echo 0)
fi

# Working directory status
DIRTY_COUNT=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
MODIFIED=$(git status --porcelain 2>/dev/null | grep -c '^.M' || true)
ADDED=$(git status --porcelain 2>/dev/null | grep -c '^A' || true)
UNTRACKED=$(git status --porcelain 2>/dev/null | grep -c '^?' || true)

# Active branches
FEATURE_BRANCHES=$(git branch -a 2>/dev/null | grep -E 'feature/' | sed 's/^[ *]*//' | sed 's|remotes/origin/||' | sort -u)
RELEASE_BRANCHES=$(git branch -a 2>/dev/null | grep -E 'release/' | sed 's/^[ *]*//' | sed 's|remotes/origin/||' | sort -u)
HOTFIX_BRANCHES=$(git branch -a 2>/dev/null | grep -E 'hotfix/' | sed 's/^[ *]*//' | sed 's|remotes/origin/||' | sort -u)

count_lines() { if [[ -z "$1" ]]; then echo 0; else echo "$1" | wc -l | tr -d ' '; fi; }
FEATURE_COUNT=$(count_lines "$FEATURE_BRANCHES")
RELEASE_COUNT=$(count_lines "$RELEASE_BRANCHES")
HOTFIX_COUNT=$(count_lines "$HOTFIX_BRANCHES")

# Tags (semver only)
LATEST_TAG=$(git tag -l 'v[0-9]*' --sort=-v:refname 2>/dev/null | head -1)
if [[ -z "$LATEST_TAG" ]]; then
  # Try without v prefix
  LATEST_TAG=$(git tag -l '[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname 2>/dev/null | head -1)
fi
LATEST_TAG=${LATEST_TAG:-"(no tags)"}

RECENT_TAGS=$(git tag -l 'v[0-9]*' --sort=-v:refname 2>/dev/null | head -5)
if [[ -z "$RECENT_TAGS" ]]; then
  RECENT_TAGS=$(git tag -l '[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname 2>/dev/null | head -5)
fi

# Commits ahead of main (for develop/feature branches)
AHEAD_OF_MAIN=0
if [[ -n "$MAIN_BRANCH" ]] && [[ "$CURRENT_BRANCH" != "$MAIN_BRANCH" ]]; then
  AHEAD_OF_MAIN=$(git rev-list "origin/$MAIN_BRANCH..HEAD" --count 2>/dev/null || echo 0)
fi

# Last commit info
LAST_COMMIT_MSG=$(git log -1 --format='%s' 2>/dev/null || echo "")
LAST_COMMIT_AGO=$(git log -1 --format='%cr' 2>/dev/null || echo "")
LAST_COMMIT_SHA=$(git log -1 --format='%h' 2>/dev/null || echo "")

# Remote
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "(no remote)")

# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

if $JSON_OUTPUT; then
  # Build feature list as JSON array
  FEATURES_JSON="[]"
  if [[ -n "$FEATURE_BRANCHES" ]] && [[ "$FEATURE_COUNT" -gt 0 ]]; then
    FEATURES_JSON=$(echo "$FEATURE_BRANCHES" | awk '{printf "%s\"%s\"", (NR>1?",":""), $0}' | sed 's/^/[/;s/$/]/')
  fi

  RELEASES_JSON="[]"
  if [[ -n "$RELEASE_BRANCHES" ]] && [[ "$RELEASE_COUNT" -gt 0 ]]; then
    RELEASES_JSON=$(echo "$RELEASE_BRANCHES" | awk '{printf "%s\"%s\"", (NR>1?",":""), $0}' | sed 's/^/[/;s/$/]/')
  fi

  HOTFIXES_JSON="[]"
  if [[ -n "$HOTFIX_BRANCHES" ]] && [[ "$HOTFIX_COUNT" -gt 0 ]]; then
    HOTFIXES_JSON=$(echo "$HOTFIX_BRANCHES" | awk '{printf "%s\"%s\"", (NR>1?",":""), $0}' | sed 's/^/[/;s/$/]/')
  fi

  cat <<JSONEOF
{
  "repo": "$REPO_NAME",
  "currentBranch": "$CURRENT_BRANCH",
  "branchType": "$BRANCH_TYPE",
  "mergeTarget": "$MERGE_TARGET",
  "gitFlowDetected": $(${DEVELOP_EXISTS} && [[ -n "$MAIN_BRANCH" ]] && echo true || echo false),
  "mainBranch": "$MAIN_BRANCH",
  "sync": {
    "ahead": $AHEAD,
    "behind": $BEHIND
  },
  "workingDir": {
    "dirty": $DIRTY_COUNT,
    "modified": $MODIFIED,
    "added": $ADDED,
    "untracked": $UNTRACKED
  },
  "branches": {
    "features": $FEATURES_JSON,
    "featureCount": $FEATURE_COUNT,
    "releases": $RELEASES_JSON,
    "releaseCount": $RELEASE_COUNT,
    "hotfixes": $HOTFIXES_JSON,
    "hotfixCount": $HOTFIX_COUNT
  },
  "version": {
    "latestTag": "$LATEST_TAG",
    "aheadOfMain": $AHEAD_OF_MAIN
  },
  "lastCommit": {
    "sha": "$LAST_COMMIT_SHA",
    "message": $(echo "$LAST_COMMIT_MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"\""),
    "ago": "$LAST_COMMIT_AGO"
  },
  "remote": $(echo "$REMOTE_URL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"\"")
}
JSONEOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$BRANCH_ICON GIT FLOW STATUS — $REPO_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Git Flow detection
if ! $DEVELOP_EXISTS || [[ -z "$MAIN_BRANCH" ]]; then
  echo ""
  echo "⚠️  Git Flow structure not fully detected"
  [[ -z "$MAIN_BRANCH" ]] && echo "   Missing: main/master branch"
  $DEVELOP_EXISTS || echo "   Missing: develop branch"
  echo ""
  echo "   Initialize Git Flow:"
  echo "     git flow init"
  echo "   Or create branches manually:"
  [[ -z "$MAIN_BRANCH" ]] && echo "     git checkout -b main"
  $DEVELOP_EXISTS || echo "     git checkout -b develop"
  echo ""
fi

# Current branch
echo ""
echo "📍 CURRENT BRANCH"
echo "   $BRANCH_ICON $CURRENT_BRANCH"
echo "   Type: $BRANCH_TYPE"
[[ -n "$MERGE_TARGET" ]] && echo "   Merge target: $MERGE_TARGET"

# Sync status
echo ""
echo "🔄 SYNC STATUS"
if [[ $AHEAD -eq 0 ]] && [[ $BEHIND -eq 0 ]]; then
  echo "   ✓ Up to date with remote"
else
  [[ $AHEAD -gt 0 ]] && echo "   ↑ $AHEAD commits ahead of remote"
  [[ $BEHIND -gt 0 ]] && echo "   ↓ $BEHIND commits behind remote"
fi

# Working directory
echo ""
echo "📝 WORKING DIRECTORY"
if [[ $DIRTY_COUNT -eq 0 ]]; then
  echo "   ✓ Clean"
else
  echo "   $DIRTY_COUNT uncommitted changes"
  [[ $MODIFIED -gt 0 ]] && echo "   ● $MODIFIED modified"
  [[ $ADDED -gt 0 ]] && echo "   ✚ $ADDED added"
  [[ $UNTRACKED -gt 0 ]] && echo "   ? $UNTRACKED untracked"
fi

# Version info
echo ""
echo "🏷️  VERSION"
echo "   Latest tag: $LATEST_TAG"
[[ $AHEAD_OF_MAIN -gt 0 ]] && echo "   Commits ahead of $MAIN_BRANCH: $AHEAD_OF_MAIN"

# Active branches
echo ""
echo "📋 ACTIVE BRANCHES"
echo "   🌿 Features: $FEATURE_COUNT"
if [[ $FEATURE_COUNT -gt 0 ]] && [[ -n "$FEATURE_BRANCHES" ]]; then
  echo "$FEATURE_BRANCHES" | while read -r b; do
    echo "      $b"
  done
fi
echo "   🚀 Releases: $RELEASE_COUNT"
if [[ $RELEASE_COUNT -gt 0 ]] && [[ -n "$RELEASE_BRANCHES" ]]; then
  echo "$RELEASE_BRANCHES" | while read -r b; do
    echo "      $b"
  done
fi
echo "   🔥 Hotfixes: $HOTFIX_COUNT"
if [[ $HOTFIX_COUNT -gt 0 ]] && [[ -n "$HOTFIX_BRANCHES" ]]; then
  echo "$HOTFIX_BRANCHES" | while read -r b; do
    echo "      $b"
  done
fi

# Last commit
echo ""
echo "📈 LAST COMMIT"
echo "   $LAST_COMMIT_SHA $LAST_COMMIT_MSG"
echo "   $LAST_COMMIT_AGO"

# Recommendations
echo ""
echo "💡 RECOMMENDATIONS"

RECS=0
if [[ $DIRTY_COUNT -gt 0 ]]; then
  echo "   ⚠️  Commit or stash $DIRTY_COUNT uncommitted changes"
  RECS=$((RECS + 1))
fi
if [[ $AHEAD -gt 0 ]]; then
  echo "   ⚠️  Push $AHEAD unpushed commits: git push"
  RECS=$((RECS + 1))
fi
if [[ $BEHIND -gt 0 ]]; then
  echo "   ⚠️  Pull $BEHIND commits from remote: git pull"
  RECS=$((RECS + 1))
fi

case "$BRANCH_TYPE" in
  production)
    echo "   ⚠️  You are on the production branch — avoid direct commits"
    echo "   Use: /feature <name>, /release <version>, or /hotfix"
    RECS=$((RECS + 1))
    ;;
  feature)
    if [[ $DIRTY_COUNT -eq 0 ]] && [[ $AHEAD -eq 0 ]]; then
      echo "   ✓ Branch is clean and synced — ready to /finish"
    fi
    ;;
  release|hotfix)
    if [[ $DIRTY_COUNT -eq 0 ]] && [[ $AHEAD -eq 0 ]]; then
      echo "   ✓ Branch is clean and synced — ready to /finalize-release or /finish"
    fi
    ;;
  integration)
    echo "   Start new work: /feature <name>"
    [[ $AHEAD_OF_MAIN -gt 10 ]] && echo "   ℹ️  $AHEAD_OF_MAIN commits ahead of $MAIN_BRANCH — consider a release"
    ;;
esac

if [[ $RECS -eq 0 ]] && [[ "$BRANCH_TYPE" != "production" ]] && [[ "$BRANCH_TYPE" != "integration" ]]; then
  echo "   ✓ No issues detected"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
