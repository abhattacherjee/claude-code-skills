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

  # Source and destination are the same file (in-repo source directory):
  # `cp a a` fails, and under `set -e` that aborts the whole sync. `-ef`
  # compares device + inode, so symlink and hardlink aliases are caught too.
  if [[ "$src" -ef "$dst" ]]; then
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

# Resolve a manifest-declared source path.
#   $1 = the raw source string from the manifest
#   $2 = the directory containing the manifest
# A leading ~ expands to $HOME. An absolute path is returned unchanged. A
# relative path resolves against the MANIFEST's directory, not the caller's
# cwd, so in-repo-source manifests work from anywhere. An empty source stays
# empty so callers report "source not found" rather than silently assembling
# the manifest's own directory.
resolve_source_path() {
  local raw="$1" manifest_dir="$2" expanded
  if [[ -z "$raw" ]]; then
    echo ""
    return
  fi
  expanded="$(resolve_tilde "$raw")"
  case "$expanded" in
    /*) echo "$expanded" ;;
    *)  echo "${manifest_dir%/}/$expanded" ;;
  esac
}

# Resolve a skill's authoring source: the local skills home if present, else an
# in-repo top-level directory (the arrangement introduced when skills moved into
# the monorepo). Local-first precedence keeps behaviour identical while both
# copies exist, and hands over automatically once the local copy is removed.
# Echoes nothing when the skill has no source anywhere.
# Usage: skill_source_dir <skill-name>
# Requires: SKILLS_HOME set by the caller (deliberately unwrapped, unlike
#   MONOREPO_DIR below — an unset SKILLS_HOME should abort loudly under
#   `set -u`, not silently resolve; every current caller sets it before
#   sourcing this file).
#
# References ${MONOREPO_DIR:-}, not $MONOREPO_DIR: this file is sourced by
# scripts (prepare-plugin.sh, prepare-skill-repo.sh, sync-individual-repos.sh)
# that never set MONOREPO_DIR, and under `set -u` an unset variable referenced
# inside a *called* function still aborts the script. Callers that do have a
# monorepo directory (sync-monorepo.sh, validate-pre-sync.sh) already set
# MONOREPO_DIR before calling this, so their behaviour is unchanged.
#
# The elif guards with `-n` explicitly rather than relying on `-f "${x:-}/…"`
# alone: with MONOREPO_DIR unset, "${MONOREPO_DIR:-}/$name/SKILL.md" collapses
# to "/$name/SKILL.md" — a root-relative path outside both trees that a
# caller with no monorepo directory could still match by accident (e.g.
# name=tmp against a real /tmp/SKILL.md). Unreachable today only because no
# current caller without MONOREPO_DIR set calls this function at all — which
# is exactly the "correct only because the next call site doesn't exist yet"
# shape this batch exists to close.
skill_source_dir() {
  local name="$1"
  if [[ -f "$SKILLS_HOME/$name/SKILL.md" ]]; then
    echo "$SKILLS_HOME/$name"
  elif [[ -n "${MONOREPO_DIR:-}" && -f "${MONOREPO_DIR}/$name/SKILL.md" ]]; then
    echo "${MONOREPO_DIR}/$name"
  fi
}

# --- Manifest shape (issue #73) ----------------------------------------------
#
# A legacy plugin-manifest.json declares skills as bare strings:
#     "skills": ["my-skill"]
# rather than the current object form:
#     "skills": [{"name": "my-skill", "source": "."}]
# A bare string means "the skill lives in this manifest's own directory", so
# {"name": <string>, "source": "."} is the faithful normalisation —
# resolve_source_path "." "$MANIFEST_DIR" yields the manifest's own directory.
#
# Bare strings are normalisable in skills[] ONLY. A skill's source is a
# directory, so "." has a meaning there; commands[] and agents[] sources are
# *files*, for which there is no defensible default. Callers reject a bare
# string in those rather than guessing — see prepare-plugin.sh.

# Write a shape-normalised copy of a manifest.
#   $1 = source manifest, $2 = destination path (overwritten)
# Callers point every subsequent `.skills[…]` read at the copy instead of
# teaching each read site the legacy shape: prepare-plugin.sh has eight such
# reads, and a fix that converts some of them still dies with
# `jq: error … Cannot index string with "name"` from whichever it missed.
#
# `.skills = ((.skills // []) | map(…))`, deliberately not the terser
# `(.skills // []) |= map(…)`: the latter is not a valid path expression when
# `.skills` is absent — jq 1.7.1 fails with "Invalid path expression with
# result []" — which would turn a manifest declaring no skills at all (legal
# today: `.skills | length` is 0) into a hard error.
normalize_manifest() {
  local src="$1" dst="$2"
  jq '.skills = ((.skills // []) | map(if type == "string" then {name: ., source: "."} else . end))' \
    "$src" > "$dst"
}

# Emit a manifest's skill names, one per line, tolerating the legacy
# bare-string form. For callers that need only the names and so do not need a
# normalised copy on disk. Entries with no name are skipped rather than
# emitting a blank line.
manifest_skill_names() {
  jq -r '(.skills // [])[] | (if type == "string" then . else .name end) // empty' "$1"
}

# Emit the bare-string entries of manifest $1's array $2 ("commands"/"agents"),
# comma-joined; empty when the array is absent or fully object-form.
manifest_bare_entries() {
  jq -r --arg key "$2" \
    '[(.[$key] // [])[] | select(type == "string")] | join(", ")' "$1"
}
