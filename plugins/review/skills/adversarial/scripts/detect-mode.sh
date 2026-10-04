#!/usr/bin/env bash
# detect-mode.sh — resolve PR/local mode, produce shared diff artifact
# Usage: detect-mode.sh [--force] [--base <branch>] [--include-untracked] [--help]
# Outputs KEY=VALUE pairs: MODE, PR, BASE, DIFF_FILE, FILES_FILE
# Exit codes: 0=ok, 1=error (git/gh failure, or no base branch found), 2=usage/large-diff
#
# PR mode: the diff is `gh pr diff`; the base is the PR's base. --base is ignored.
# Local mode (no PR): the base is --base if given, else a guess from the branch
# prefix (feature/* -> develop, release/* and hotfix/* -> main, else the repo
# default). A guess that names a missing branch falls back to the repo default
# branch (main when gh cannot say), with a note on stderr. If no base exists the
# script exits 1; it never writes an empty diff for a missing base.
# The local diff is the working tree against the merge base: committed, staged and
# unstaged changes to tracked files. Untracked files are left out unless
# --include-untracked is given, because the diff is sent to an external model and an
# untracked file may hold a secret. They are listed (paths only) on stderr. With the
# flag, files whose names look like secrets (SECRET_NAME_GLOBS below) are still left
# out and listed. The user's index is never changed; the flag path adds the untracked
# files with `git add -N` to a temporary copy of the index.

set -eu

FORCE=false
BASE_ARG=""
INCLUDE_UNTRACKED=false
# Untracked files with these names are never put in the diff, even with
# --include-untracked. Matched against the lower-cased file name (not the directory).
SECRET_NAME_GLOBS=('.env' '.env.*' '*.pem' '*.key' 'id_rsa*' 'id_ed25519*' '*credentials*' '*.p12' '*.pfx')
MAX_LISTED=20
SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--force] [--base <branch>] [--include-untracked] [--help]

Detect whether a PR exists for the current branch, produce the shared
diff artifact and changed-file list, and print environment variables
for downstream use.

Options:
  --force          Bypass the large-diff cap (> 4000 lines) and proceed anyway
  --base <branch>  Local mode: diff against this branch instead of guessing from
                   the branch prefix. Unknown branch -> exit 2. Ignored in PR mode.
  --include-untracked
                   Local mode: also put untracked (not ignored) files in the diff.
                   Names that look like secrets (.env, .env.*, *.pem, *.key, id_rsa*,
                   id_ed25519*, *credentials*, *.p12, *.pfx) are still left out.
  --help           Show this help and exit

Local mode diffs the working tree against the merge base: committed, staged and
unstaged changes to tracked files. Untracked files are left out and listed on stderr
(paths only), because the diff goes to an external model. Your index is not changed.

Output (stdout, KEY=VALUE):
  MODE=pr|local
  PR=<number>|-
  BASE=<branch>
  DIFF_FILE=<path>
  FILES_FILE=<path>

Exit codes:
  0  Success
  1  Error (git/gh command failure, no base branch found, etc.)
  2  Usage error (including an unknown --base) or large-diff cap exceeded
     (use --force to bypass)
EOF
}

# ---- argument parsing ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --include-untracked) INCLUDE_UNTRACKED=true; shift ;;
    --base)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: --base requires a branch name" >&2
        exit 2
      fi
      BASE_ARG="$2"; shift 2 ;;
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

# Print the ref to use for branch $1: the local branch, else origin's, else any
# ref git can resolve ($1 itself, e.g. a tag). Prints nothing and returns 1 when none.
base_ref() {
  local b="$1"
  if git rev-parse --verify --quiet "refs/heads/$b" >/dev/null 2>&1; then
    echo "refs/heads/$b"
  elif git rev-parse --verify --quiet "refs/remotes/origin/$b" >/dev/null 2>&1; then
    echo "refs/remotes/origin/$b"
  elif git rev-parse --verify --quiet "$b^{commit}" >/dev/null 2>&1; then
    echo "$b"
  else
    return 1
  fi
}

# True when the file name (last path part, lower-cased) matches SECRET_NAME_GLOBS.
is_secret_name() {
  local name glob
  name="$(basename "$1" | tr 'A-Z' 'a-z')"
  for glob in "${SECRET_NAME_GLOBS[@]}"; do
    # shellcheck disable=SC2254
    case "$name" in $glob) return 0 ;; esac
  done
  return 1
}

# Print up to MAX_LISTED paths from stdin (one per line), then "and N more".
list_paths() {
  local n=0 line
  while IFS= read -r line; do
    n=$((n + 1))
    if [[ $n -le $MAX_LISTED ]]; then echo "  $line" >&2; fi
  done
  if [[ $n -gt $MAX_LISTED ]]; then echo "  ... and $((n - MAX_LISTED)) more" >&2; fi
}

# ---- main logic ----
# Get current branch
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || {
  if git rev-parse --git-dir >/dev/null 2>&1; then
    die "This branch has no commits yet; commit something first"
  fi
  die "Not inside a git repository"
}
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
  if [[ -n "$BASE_ARG" ]]; then
    BASE="$BASE_ARG"
    base_ref "$BASE" >/dev/null || { echo "Error: --base '$BASE' is not a branch or ref in this repository" >&2; exit 2; }
  else
    DEFAULT_BASE="$(get_repo_default_branch)"
    BASE="$(resolve_base_from_prefix "$BRANCH" "$DEFAULT_BASE")"
    if ! base_ref "$BASE" >/dev/null; then
      if [[ "$BASE" != "$DEFAULT_BASE" ]] && base_ref "$DEFAULT_BASE" >/dev/null; then
        echo "Note: base '$BASE' (guessed from branch '$BRANCH') does not exist; using the repo default branch '$DEFAULT_BASE'. Pass --base <branch> to choose another." >&2
        BASE="$DEFAULT_BASE"
      else
        die "No base branch found: '$BASE' and '$DEFAULT_BASE' both do not exist. Pass --base <branch>."
      fi
    fi
  fi
fi
if [[ "$MODE" == "pr" && -n "$BASE_ARG" ]]; then
  echo "Note: --base is ignored in PR mode; the PR's base is '$BASE'." >&2
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
  BASE_REF="$(base_ref "$BASE")" || die "Base '$BASE' disappeared"
  MERGE_BASE="$(git merge-base "$BASE_REF" HEAD 2>/dev/null)" || {
    rm -f "$DIFF_FILE" "$FILES_FILE"
    die "No merge base between '$BASE' and HEAD"
  }
  # Work from the repo root so paths are repo-relative.
  TOP="$(git rev-parse --show-toplevel)"
  cd "$TOP"
  # Guard 1: file names come from the working tree, so git must treat every name as a
  # literal path. Without this, an untracked file named `[.]env` or `*` is a glob when
  # it reaches `git add -N` and would pull a secret like `.env` into the diff.
  export GIT_LITERAL_PATHSPECS=1
  # Untracked, not-ignored files. Their contents would go to an external model, so
  # they are opt-in, and secret-looking names are never sent.
  UNTRACKED=()
  while IFS= read -r -d '' f; do UNTRACKED+=("$f"); done < <(git ls-files --others --exclude-standard -z --full-name 2>/dev/null)
  SEND=(); SKIP_SECRET=()
  if [[ "$INCLUDE_UNTRACKED" == "true" ]]; then
    for f in ${UNTRACKED[@]+"${UNTRACKED[@]}"}; do
      if is_secret_name "$f"; then SKIP_SECRET+=("$f"); else SEND+=("$f"); fi
    done
  fi
  if [[ "$INCLUDE_UNTRACKED" != "true" && ${#UNTRACKED[@]} -gt 0 ]]; then
    echo "Note: ${#UNTRACKED[@]} untracked file(s) were left out of the diff (their contents would go to the adversary model). Pass --include-untracked to review them. Left out:" >&2
    printf '%s\n' "${UNTRACKED[@]}" | list_paths
  fi
  if [[ ${#SKIP_SECRET[@]} -gt 0 ]]; then
    echo "Note: ${#SKIP_SECRET[@]} untracked file(s) with secret-looking names were left out even with --include-untracked:" >&2
    printf '%s\n' "${SKIP_SECRET[@]}" | list_paths
  fi
  if [[ ${#SEND[@]} -gt 0 ]]; then
    # Intent-to-add in a temporary copy of the index, never in the user's index.
    TMP_INDEX="$(mktemp /tmp/adversarial-review-index.XXXXXX)"
    trap 'rm -f "$TMP_INDEX"' EXIT
    IDX="$(git rev-parse --git-path index)"
    if [[ -f "$IDX" ]]; then cp "$IDX" "$TMP_INDEX"; else rm -f "$TMP_INDEX"; fi
    printf '%s\0' "${SEND[@]}" | GIT_INDEX_FILE="$TMP_INDEX" xargs -0 git add -N -- 2>/dev/null || true
    export GIT_INDEX_FILE="$TMP_INDEX"
  fi
  if ! git diff "$MERGE_BASE" >"$DIFF_FILE" 2>/dev/null; then
    rm -f "$DIFF_FILE" "$FILES_FILE"
    die "Failed to produce git diff against merge base of $BASE and HEAD"
  fi
  git diff --name-only "$MERGE_BASE" >"$FILES_FILE" 2>/dev/null || true
  # Guard 2 (fail closed): whatever went wrong above, no untracked path may be in the
  # diff unless it was chosen (SEND) and has a non-secret name. Check the paths the diff
  # really holds. On any hit, send nothing.
  SEND_LIST="$(printf '%s\n' ${SEND[@]+"${SEND[@]}"})"
  UNTRACKED_LIST="$(printf '%s\n' ${UNTRACKED[@]+"${UNTRACKED[@]}"})"
  while IFS= read -r -d '' p; do
    if printf '%s\n' "$UNTRACKED_LIST" | grep -qxF -- "$p"; then
      if is_secret_name "$p" || ! printf '%s\n' "$SEND_LIST" | grep -qxF -- "$p"; then
        rm -f "$DIFF_FILE" "$FILES_FILE"
        die "Refusing to send a partial or unsafe diff: untracked path '$p' is in the diff but was not chosen or has a secret-looking name. Nothing was written."
      fi
    fi
  done < <(git diff --name-only -z "$MERGE_BASE" 2>/dev/null)
fi

# ---- large-diff cap ----
# Use grep -c '' to count lines correctly even when the file lacks a trailing newline
DIFF_LINES="$(grep -c '' "$DIFF_FILE" || true)"
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
