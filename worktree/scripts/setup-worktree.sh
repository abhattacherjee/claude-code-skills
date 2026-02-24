#!/usr/bin/env bash
set -eu

# setup-worktree.sh — Create an isolated git worktree for parallel Claude Code sessions
#
# Usage:
#   setup-worktree.sh list                          # List existing worktrees + feature branches
#   setup-worktree.sh create <branch>               # Create worktree for existing branch
#   setup-worktree.sh create --new <branch-name>    # Create new branch from develop + worktree
#   setup-worktree.sh remove <branch>               # Remove a worktree
#   setup-worktree.sh --help

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME <command> [options]

Commands:
  list                          List existing worktrees and available feature branches
  create <branch>               Create a worktree for an existing branch
  create --new <branch-name>    Create a new feature branch from develop + worktree
  remove <branch>               Remove a worktree (keeps branch)
  install <branch>              Run npm install in all packages for a worktree

Options:
  --help, -h                    Show this help message
  --no-install                  Skip npm install after creating worktree

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

# Convert branch name to worktree directory name
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
      wt_dir="$(branch_to_dir "$branch")"
      if [ -d "$wt_dir" ]; then
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

  local wt_dir
  wt_dir="$(branch_to_dir "$branch")"

  # Check if worktree already exists
  if [ -d "$wt_dir" ]; then
    echo "Worktree already exists: $wt_dir"
    echo ""
    echo "To use it, start Claude Code there:"
    echo "  cd $wt_dir && claude"
    exit 0
  fi

  if $new_branch; then
    echo "Creating new branch '$branch' from develop..."
    # Fetch latest develop
    git fetch origin develop 2>/dev/null || true
    # Create worktree with new branch based on develop
    git worktree add "$wt_dir" -b "$branch" origin/develop
  else
    # Check if branch exists locally
    if git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
      echo "Creating worktree for local branch '$branch'..."
      git worktree add "$wt_dir" "$branch"
    elif git show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
      echo "Creating worktree for remote branch 'origin/$branch'..."
      git worktree add "$wt_dir" --track -b "$branch" "origin/$branch"
    else
      echo "ERROR: Branch '$branch' not found locally or on remote" >&2
      echo "  Use --new to create a new branch: $SCRIPT_NAME create --new $branch" >&2
      exit 1
    fi
  fi

  echo ""
  echo "Worktree created: $wt_dir"

  # Install dependencies if needed
  if ! $skip_install; then
    echo ""
    install_deps "$wt_dir"
  fi

  echo ""
  echo "========================================="
  echo "  Worktree ready!"
  echo "========================================="
  echo ""
  echo "Start a new Claude Code session:"
  echo "  cd $wt_dir && claude"
  echo ""
  echo "Or open in your editor:"
  echo "  code $wt_dir"
  echo ""
  echo "When done, remove the worktree:"
  echo "  $SCRIPT_NAME remove $branch"
}

# Install dependencies in a worktree
install_deps() {
  local wt_dir="$1"

  local packages=("backend" "frontend" "mcp-events-server")
  local installed=0

  for pkg in "${packages[@]}"; do
    local pkg_dir="$wt_dir/$pkg"
    if [ -f "$pkg_dir/package.json" ] && [ ! -d "$pkg_dir/node_modules" ]; then
      echo "Installing dependencies in $pkg..."
      (cd "$pkg_dir" && npm install --silent 2>&1) || {
        echo "WARNING: npm install failed in $pkg (you can retry manually)" >&2
      }
      installed=$((installed + 1))
    fi
  done

  if [ $installed -eq 0 ]; then
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
  wt_dir="$(branch_to_dir "$branch")"

  if [ ! -d "$wt_dir" ]; then
    echo "ERROR: Worktree not found: $wt_dir" >&2
    exit 1
  fi

  install_deps "$wt_dir"
}

# Remove command
cmd_remove() {
  ensure_git_repo
  get_repo_info

  local branch="${1:-}"
  if [ -z "$branch" ]; then
    echo "ERROR: Branch name required" >&2
    exit 1
  fi

  local wt_dir
  wt_dir="$(branch_to_dir "$branch")"

  if [ ! -d "$wt_dir" ]; then
    echo "ERROR: Worktree not found: $wt_dir" >&2
    echo "Existing worktrees:"
    git worktree list
    exit 1
  fi

  echo "Removing worktree: $wt_dir"
  git worktree remove "$wt_dir" --force
  echo "Worktree removed. Branch '$branch' is preserved."
  echo ""
  echo "To also delete the branch:"
  echo "  git branch -d $branch"
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
    echo "Run '$SCRIPT_NAME --help' for usage" >&2
    exit 2
    ;;
esac
