#!/usr/bin/env bash
# _lib.sh — Shared utility functions for skill-publishing scripts
# Source this file: source "$SCRIPT_DIR/_lib.sh"
# Requires: DRY_RUN variable set by the caller (default: false)

# Guard: prevent direct execution
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Error: source this file, don't execute it directly" >&2
  echo "Usage: source \"\$SCRIPT_DIR/_lib.sh\"" >&2
  exit 1
fi

# ============================================================
# Frontmatter extraction
# ============================================================

# Extract a top-level field from SKILL.md YAML frontmatter
# Usage: extract_field <skill_md_path> <field_name>
extract_field() {
  local skill_md="$1"
  local field="$2"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "^${field}:" | head -1 | \
    sed "s/^${field}:[[:space:]]*//; s/^[\"']//; s/[\"']$//"
}

# Extract metadata.version from SKILL.md frontmatter
# Usage: extract_version <skill_md_path>
extract_version() {
  local skill_md="$1"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "version:" | head -1 | \
    sed 's/.*version:[[:space:]]*//; s/^[\"'"'"']//; s/[\"'"'"']$//'
}

# Trim description at "Use when:" to produce a short description
# Usage: short_desc <description_text>
short_desc() {
  echo "$1" | sed 's/\. Use when:.*/\./'
}

# Extract content under a ## heading (returns lines until next ## or EOF)
# Uses awk for BSD/GNU portability, perl for blank-line trimming.
# Usage: extract_section <file> <heading_text>
# Example: extract_section SKILL.md "Quick Check"
extract_section() {
  local file="$1"
  local heading="$2"
  awk -v h="$heading" '
    $0 == "## " h { found=1; next }
    found && /^## / { exit }
    found { print }
  ' "$file" 2>/dev/null | perl -0777 -pe 's/\A\s*\n//; s/\n\s*\z//'
}

# Extract ## heading titles from markdown (after frontmatter)
# Usage: extract_headings <file> [max_count]
# Returns one heading per line, frontmatter skipped
extract_headings() {
  local file="$1"
  local max="${2:-10}"
  awk '/^---$/{fm++; next} fm>=2{print}' "$file" 2>/dev/null | \
    grep '^## ' | head -"$max" | sed 's/^## //'
}

# ============================================================
# File operations (DRY_RUN-aware)
# ============================================================

# Write content to a file (skip if exists, unless overwrite=true)
# Usage: write_file <filepath> <content> <label> [overwrite]
# Requires: DRY_RUN variable in calling scope
write_file() {
  local filepath="$1"
  local content="$2"
  local label="$3"
  local overwrite="${4:-false}"

  if [[ -f "$filepath" ]] && [[ "$overwrite" != "true" ]]; then
    echo "  SKIP    $label (already exists)"
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$filepath" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD CREATE  $label"
    fi
  else
    mkdir -p "$(dirname "$filepath")"
    echo "$content" > "$filepath"
    if [[ "$overwrite" == "true" ]]; then
      echo "  SYNCED  $label"
    else
      echo "  CREATED $label"
    fi
  fi
}

# Copy a single file
# Usage: copy_file <src> <dst> <label>
# Requires: DRY_RUN variable in calling scope
copy_file() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -f "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$dst" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD COPY    $label"
    fi
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  SYNCED  $label"
  fi
}

# Copy a directory via rsync (excluding .git, .claude, .DS_Store)
# Usage: copy_dir <src> <dst> <label>
# Requires: DRY_RUN variable in calling scope
copy_dir() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -d "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    local count
    count=$(find "$src" -type f | wc -l | tr -d ' ')
    echo "  WOULD COPY    $label ($count files)"
  else
    mkdir -p "$dst"
    rsync -a --delete --exclude='.git' --exclude='.claude' --exclude='.DS_Store' "$src/" "$dst/"
    echo "  SYNCED  $label"
  fi
}

# ============================================================
# GitHub / path utilities
# ============================================================

# Auto-detect GitHub username via gh CLI
# Usage: resolve_github_user
# Sets GITHUB_USER in caller scope (expects it to exist, possibly empty)
resolve_github_user() {
  if [[ -z "$GITHUB_USER" ]]; then
    GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
    if [[ -z "$GITHUB_USER" ]]; then
      echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
      exit 1
    fi
  fi
}

# Expand ~ to $HOME in a path
# Usage: resolve_tilde <path>
resolve_tilde() {
  echo "${1/#\~/$HOME}"
}
