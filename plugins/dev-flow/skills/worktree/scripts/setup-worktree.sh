#!/usr/bin/env bash
set -eu

# setup-worktree.sh — Create an isolated git worktree for parallel Claude Code sessions
#
# Usage:
#   setup-worktree.sh list                          # List existing worktrees + feature branches
#   setup-worktree.sh create <branch>               # Create worktree for existing branch
#   setup-worktree.sh create --new <branch-name>    # Create new branch + worktree
#   setup-worktree.sh remove <branch> [--force]     # Remove a worktree
#   setup-worktree.sh --help

SCRIPT_NAME="$(basename "$0")"
# The absolute path of this script, for the commands it prints: they work when pasted.
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$SCRIPT_NAME"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME <command> [options]

Commands:
  list                          List existing worktrees and available feature branches
  create <branch>               Create a worktree for an existing branch (local, or
                                origin/<branch>)
  create --new <branch-name>    Create a new branch (feature/ is added unless it starts
                                with feature/, hotfix/ or release/) + worktree. Base:
                                origin/develop, else develop, else origin/HEAD's branch,
                                else main. The new branch has no upstream.
  remove <branch> [--force]     Remove the worktree of <branch> (keeps the branch).
                                Refused if it has uncommitted work: modified or
                                untracked files, or git-ignored files outside
                                node_modules/ (such as .env). --force removes it anyway
                                and discards that work.
  install <branch>              Run npm install in the worktree of <branch>

Options:
  --help, -h                    Show this help message
  --no-install                  Skip npm install after creating worktree

The worktree goes in a sibling directory, <repo>--<branch without feature/, / as ->.
Worktrees are found by branch (git worktree list), not by directory name. create
fails if that directory exists and is not the branch's worktree.

npm install runs in the worktree root and in each immediate subdirectory that has a
package.json and no node_modules. If any install fails, the command exits 1.

Examples:
  $SCRIPT_NAME list
  $SCRIPT_NAME create feature/story-10.11-view-consistency
  $SCRIPT_NAME create --new story-10.12-new-feature
  $SCRIPT_NAME remove feature/story-10.11-view-consistency
EOF
  exit 0
}

# Ensure we're in a git repo
ensure_git_repo() {
  if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "ERROR: Not in a git repository" >&2
    exit 1
  fi
}

# Get the repo root and name
get_repo_info() {
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  REPO_NAME="$(basename "$REPO_ROOT")"
  REPO_PARENT="$(dirname "$REPO_ROOT")"
}

# Convert branch name to the directory a new worktree goes in
branch_to_dir() {
  local branch="$1"
  # Strip feature/ prefix, replace / with -
  local suffix="${branch#feature/}"
  suffix="${suffix//\//-}"
  echo "${REPO_PARENT}/${REPO_NAME}--${suffix}"
}

# List command
cmd_list() {
  ensure_git_repo
  get_repo_info

  echo "=== Existing Worktrees ==="
  git worktree list
  echo ""

  echo "=== Feature Branches (local) ==="
  local branches
  branches=$(git branch --list 'feature/*' --format='%(refname:short)' 2>/dev/null)
  if [ -z "$branches" ]; then
    echo "  (none)"
  else
    while IFS= read -r branch; do
      local wt_dir
      wt_dir="$(find_worktree "$branch")"
      if [ -n "$wt_dir" ]; then
        echo "  $branch  [worktree: $wt_dir]"
      else
        echo "  $branch"
      fi
    done <<< "$branches"
  fi
  echo ""

  echo "=== Remote Feature Branches (not checked out locally) ==="
  local remote_branches
  remote_branches=$(git branch -r --list 'origin/feature/*' --format='%(refname:short)' 2>/dev/null | while read -r rb; do
    local local_name="${rb#origin/}"
    if ! git show-ref --verify --quiet "refs/heads/$local_name" 2>/dev/null; then
      echo "  $local_name"
    fi
  done)
  if [ -z "$remote_branches" ]; then
    echo "  (none)"
  else
    echo "$remote_branches"
  fi
}

# Print the path of the worktree that has <branch> checked out, or nothing.
find_worktree() {
  local want="refs/heads/$1" line path=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) path="${line#worktree }" ;;
      "branch "*)
        if [ "${line#branch }" = "$want" ]; then
          printf '%s\n' "$path"
          return 0
        fi
        ;;
    esac
  done < <(git worktree list --porcelain)
  return 0
}

# Print the base for a new branch: origin/develop, develop, origin/HEAD's branch, or main.
pick_base() {
  local head_ref
  if git show-ref --verify --quiet refs/remotes/origin/develop; then
    echo "origin/develop"
  elif git show-ref --verify --quiet refs/heads/develop; then
    echo "develop"
  elif head_ref="$(git symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null)"; then
    echo "${head_ref#refs/remotes/}"
  elif git show-ref --verify --quiet refs/heads/main; then
    echo "main"
  else
    return 1
  fi
}

# Create command
cmd_create() {
  ensure_git_repo
  get_repo_info

  local new_branch=false
  local skip_install=false
  local branch=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --new)
        new_branch=true
        shift
        ;;
      --no-install)
        skip_install=true
        shift
        ;;
      *)
        branch="$1"
        shift
        ;;
    esac
  done

  if [ -z "$branch" ]; then
    echo "ERROR: Branch name required" >&2
    echo "Usage: $SCRIPT_NAME create [--new] <branch-name>" >&2
    exit 1
  fi

  # Auto-prefix with feature/ if not already prefixed
  if $new_branch && [[ "$branch" != feature/* ]] && [[ "$branch" != hotfix/* ]] && [[ "$branch" != release/* ]]; then
    branch="feature/$branch"
  fi

  # A worktree that already has this branch checked out: point at it.
  local existing
  existing="$(find_worktree "$branch")"
  if [ -n "$existing" ]; then
    echo "Worktree already exists: $existing"
    echo ""
    echo "To use it, start Claude Code there:"
    printf '  cd %q && claude\n' "$existing"
    exit 0
  fi

  local wt_dir
  wt_dir="$(branch_to_dir "$branch")"

  # Something else is in the way: another branch's worktree, or a plain directory.
  if [ -e "$wt_dir" ]; then
    echo "ERROR: $wt_dir already exists and is not the worktree of '$branch'" >&2
    echo "  Move it away, or remove that worktree first." >&2
    exit 1
  fi

  if $new_branch; then
    if git remote get-url origin >/dev/null 2>&1; then
      if ! git fetch --quiet origin; then
        echo "WARNING: git fetch origin failed; the base branch may be out of date" >&2
      fi
    fi
    local base
    if ! base="$(pick_base)"; then
      echo "ERROR: No base branch for '$branch': found no origin/develop, develop, origin/HEAD or main" >&2
      exit 1
    fi
    echo "Creating new branch '$branch' from $base..."
    git worktree add --no-track -b "$branch" "$wt_dir" "$base"
  else
    # Check if branch exists locally
    if git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
      echo "Creating worktree for local branch '$branch'..."
      git worktree add "$wt_dir" "$branch"
    elif git show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
      echo "Creating worktree for remote branch 'origin/$branch'..."
      git worktree add --track -b "$branch" "$wt_dir" "origin/$branch"
    else
      echo "ERROR: Branch '$branch' not found locally or on remote" >&2
      printf '  Use --new to create a new branch: %q create --new %q\n' "$SCRIPT_PATH" "$branch" >&2
      exit 1
    fi
  fi

  echo ""
  echo "Worktree created: $wt_dir"

  # Install dependencies if needed
  local install_ok=true
  if ! $skip_install; then
    echo ""
    install_deps "$wt_dir" "$branch" || install_ok=false
  fi

  echo ""
  echo "========================================="
  if $install_ok; then
    echo "  Worktree ready!"
  else
    echo "  Worktree created, but npm install failed"
  fi
  echo "========================================="
  echo ""
  echo "Start a new Claude Code session:"
  printf '  cd %q && claude\n' "$wt_dir"
  echo ""
  echo "Or open in your editor:"
  printf '  code %q\n' "$wt_dir"
  echo ""
  echo "When done, remove the worktree:"
  printf '  cd %q && %q remove %q\n' "$REPO_ROOT" "$SCRIPT_PATH" "$branch"

  $install_ok || exit 1
}

# install_deps <worktree> <branch>: install dependencies in the root and each immediate
# subdirectory that has a package.json and no node_modules. Returns 1 if any install failed.
install_deps() {
  local wt_dir="$1" branch="$2"
  local installed=0
  local failed=""
  local dir name

  for dir in "$wt_dir" "$wt_dir"/*/; do
    dir="${dir%/}"
    [ -d "$dir" ] || continue
    if [ "$dir" = "$wt_dir" ]; then
      name="."
    else
      name="${dir##*/}"
      [ "$name" = node_modules ] && continue
    fi
    if [ -f "$dir/package.json" ] && [ ! -d "$dir/node_modules" ]; then
      echo "Installing dependencies in $name..."
      if (cd "$dir" && npm install --silent); then
        installed=$((installed + 1))
      else
        failed="$failed $name"
      fi
    fi
  done

  if [ -n "$failed" ]; then
    [ "$installed" -gt 0 ] && echo "Installed dependencies in $installed package(s)."
    echo "ERROR: npm install failed in:$failed. Retry by hand, or run:" >&2
    printf '  cd %q && %q install %q\n' "$REPO_ROOT" "$SCRIPT_PATH" "$branch" >&2
    return 1
  fi
  if [ "$installed" -eq 0 ]; then
    echo "All packages already have node_modules installed."
  else
    echo "Installed dependencies in $installed package(s)."
  fi
}

# Install command (standalone)
cmd_install() {
  ensure_git_repo
  get_repo_info

  local branch="${1:-}"
  if [ -z "$branch" ]; then
    echo "ERROR: Branch name required" >&2
    exit 1
  fi

  local wt_dir
  wt_dir="$(find_worktree "$branch")"
  if [ -z "$wt_dir" ]; then
    echo "ERROR: Worktree not found for branch '$branch'" >&2
    exit 1
  fi

  install_deps "$wt_dir" "$branch"
}

# Remove command
cmd_remove() {
  ensure_git_repo
  get_repo_info

  local force=false
  local branch=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --force) force=true; shift ;;
      *) branch="$1"; shift ;;
    esac
  done
  if [ -z "$branch" ]; then
    echo "ERROR: Branch name required" >&2
    echo "Usage: $SCRIPT_NAME remove <branch> [--force]" >&2
    exit 1
  fi

  local wt_dir
  wt_dir="$(find_worktree "$branch")"
  if [ -z "$wt_dir" ]; then
    echo "ERROR: Worktree not found for branch '$branch'" >&2
    echo "Existing worktrees:" >&2
    git worktree list >&2
    exit 1
  fi
  if [ "$wt_dir" = "$(git worktree list --porcelain | sed -n '1s/^worktree //p')" ]; then
    echo "ERROR: '$branch' is checked out in the main worktree ($wt_dir); not removing it" >&2
    exit 1
  fi

  # git worktree remove deletes git-ignored files (.env, local config) without a word, so
  # without --force they count as work to keep. node_modules/ is left out: it can be
  # installed again.
  if ! $force; then
    local status ignored n
    if ! status="$(git -C "$wt_dir" status --porcelain --ignored)"; then
      echo "ERROR: git status failed in $wt_dir; not removing it" >&2
      exit 1
    fi
    ignored="$(printf '%s\n' "$status" | sed -n 's/^!! //p' \
      | grep -Ev '(^|/)node_modules(/|$)' || true)"
    if [ -n "$ignored" ]; then
      n="$(printf '%s\n' "$ignored" | wc -l | tr -d ' ')"
      echo "ERROR: $wt_dir has $n git-ignored file(s) or folder(s) that remove would delete:" >&2
      printf '%s\n' "$ignored" | head -10 | sed 's/^/  /' >&2
      [ "$n" -gt 10 ] && echo "  ... and $((n - 10)) more" >&2
      echo "  Copy what you need, or discard it with:" >&2
      printf '  cd %q && %q remove --force %q\n' "$REPO_ROOT" "$SCRIPT_PATH" "$branch" >&2
      exit 1
    fi
  fi

  echo "Removing worktree: $wt_dir"
  local rc=0
  if $force; then
    git worktree remove --force "$wt_dir" || rc=$?
  else
    git worktree remove "$wt_dir" || rc=$?
  fi
  if [ "$rc" -ne 0 ]; then
    echo "ERROR: git did not remove the worktree (see above). If it has uncommitted work you" >&2
    echo "  want to discard, run:" >&2
    printf '  cd %q && %q remove --force %q\n' "$REPO_ROOT" "$SCRIPT_PATH" "$branch" >&2
    exit "$rc"
  fi
  echo "Worktree removed. Branch '$branch' is preserved."
  echo ""
  echo "To also delete the branch:"
  printf '  git branch -d %q\n' "$branch"
}

# Main dispatch
case "${1:---help}" in
  --help|-h)
    usage
    ;;
  list)
    shift
    cmd_list "$@"
    ;;
  create)
    shift
    cmd_create "$@"
    ;;
  remove)
    shift
    cmd_remove "$@"
    ;;
  install)
    shift
    cmd_install "$@"
    ;;
  *)
    echo "ERROR: Unknown command '$1'" >&2
    printf 'Run %q --help for usage\n' "$SCRIPT_PATH" >&2
    exit 2
    ;;
esac
