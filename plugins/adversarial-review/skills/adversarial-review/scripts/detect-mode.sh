#!/usr/bin/env bash
# detect-mode.sh — resolve PR/local mode, produce shared diff artifact
# Usage: detect-mode.sh [--force] [--help]
# Outputs KEY=VALUE pairs: MODE, PR, BASE, DIFF_FILE, FILES_FILE
# Exit codes: 0=ok, 1=error, 2=usage/large-diff, 3=adversary-unavailable

set -eu

FORCE=false
SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--force] [--help]

Detect whether a PR exists for the current branch, produce the shared
diff artifact and changed-file list, and print environment variables
for downstream use.

Options:
  --force   Bypass the large-diff cap (> 4000 lines) and proceed anyway
  --help    Show this help and exit

Output (stdout, KEY=VALUE):
  MODE=pr|local
  PR=<number>|-
  BASE=<branch>
  DIFF_FILE=<path>
  FILES_FILE=<path>

Exit codes:
  0  Success
  1  Error (git/gh command failure, etc.)
  2  Usage error or large-diff cap exceeded (use --force to bypass)
EOF
}

# ---- argument parsing ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --help)  usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ---- helpers ----
die() { echo "Error: $*" >&2; exit 1; }

# Resolve base branch from branch name prefix (pure logic, testable in isolation)
# Usage: resolve_base_from_prefix <branch> <default_base>
resolve_base_from_prefix() {
  local branch="$1"
  local default_base="$2"
  case "$branch" in
    feature/*) echo "develop" ;;
    release/*|hotfix/*) echo "main" ;;
    *) echo "$default_base" ;;
  esac
}

# Get the repo default branch via gh, fallback to main
get_repo_default_branch() {
  local default_branch
  if default_branch="$(gh repo view --json defaultBranchRef -q '.defaultBranchRef.name' 2>/dev/null)" && [[ -n "$default_branch" ]]; then
    echo "$default_branch"
  else
    echo "main"
  fi
}

# ---- main logic ----
# Get current branch
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || die "Not inside a git repository"
[[ "$BRANCH" == "HEAD" ]] && die "Detached HEAD state — cannot determine branch"

MODE=""
PR_NUMBER="-"
BASE=""

# Try PR mode first
if PR_NUMBER="$(gh pr view "$BRANCH" --json number -q '.number' 2>/dev/null)" && [[ -n "$PR_NUMBER" ]]; then
  BASE="$(gh pr view "$BRANCH" --json baseRefName -q '.baseRefName' 2>/dev/null)" || die "Could not retrieve PR base branch"
  MODE="pr"
else
  PR_NUMBER="-"
  MODE="local"
  DEFAULT_BASE="$(get_repo_default_branch)"
  BASE="$(resolve_base_from_prefix "$BRANCH" "$DEFAULT_BASE")"
fi

# ---- produce diff artifact ----
DIFF_FILE="$(mktemp /tmp/adversarial-review-diff.XXXXXX)"
FILES_FILE="$(mktemp /tmp/adversarial-review-files.XXXXXX)"

if [[ "$MODE" == "pr" ]]; then
  if ! gh pr diff "$PR_NUMBER" >"$DIFF_FILE" 2>/dev/null; then
    rm -f "$DIFF_FILE" "$FILES_FILE"
    die "Failed to fetch diff for PR #$PR_NUMBER"
  fi
  # Extract changed files from the diff
  grep '^+++ b/' "$DIFF_FILE" | sed 's|^+++ b/||' >"$FILES_FILE" || true
else
  # Verify base branch exists
  if ! git rev-parse --verify "refs/remotes/origin/$BASE" >/dev/null 2>&1 && \
     ! git rev-parse --verify "refs/heads/$BASE" >/dev/null 2>&1; then
    # Try without remote prefix
    if ! git rev-parse --verify "$BASE" >/dev/null 2>&1; then
      echo "Warning: base branch '$BASE' not found locally; diff may be empty" >&2
    fi
  fi
  if ! git diff "${BASE}...HEAD" >"$DIFF_FILE" 2>/dev/null; then
    rm -f "$DIFF_FILE" "$FILES_FILE"
    die "Failed to produce git diff from $BASE...HEAD"
  fi
  git diff --name-only "${BASE}...HEAD" >"$FILES_FILE" 2>/dev/null || true
fi

# ---- large-diff cap ----
DIFF_LINES="$(wc -l <"$DIFF_FILE")"
if [[ "$DIFF_LINES" -gt 4000 ]] && [[ "$FORCE" == "false" ]]; then
  echo "Warning: diff is $DIFF_LINES lines (cap: 4000). Use --force to proceed anyway." >&2
  rm -f "$DIFF_FILE" "$FILES_FILE"
  exit 2
fi

# ---- emit output ----
echo "MODE=$MODE"
echo "PR=$PR_NUMBER"
echo "BASE=$BASE"
echo "DIFF_FILE=$DIFF_FILE"
echo "FILES_FILE=$FILES_FILE"
