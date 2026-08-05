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

# Extract a top-level field from SKILL.md YAML frontmatter, decoding the YAML
# scalar style it is written in.
# Usage: extract_field <skill_md_path> <field_name>
#
# The previous implementation was `grep "^field:" | head -1 | sed` with two
# unconditional quote strips, which had three defects at once (issues #37, #102,
# and one unfiled). All three share a root cause — reading the line as raw text
# rather than as a YAML scalar — so they are closed together:
#
#   >- / |-   a block scalar carries no text on its own line, so the old reader
#             returned the literal indicator ">-" and prepare-plugin.sh wrote
#             that into the generated README (#37). In Markdown ">-" renders as
#             an empty blockquote, so the failure was silent.
#   "\"…\""   only the OUTER quote pair was removed, so every internal \" was
#             emitted verbatim into the README (#102).
#   unfiled   `s/^["']//; s/["']$//` fires on the first and last character
#             unconditionally and independently, so a PLAIN scalar that merely
#             starts with a quote — `description: "quoted" is a word` — lost its
#             leading ". Quotes are now stripped only when the value genuinely
#             opens and closes with the same quote character.
#
# awk rather than a YAML library: awk is already a dependency of this file
# (extract_section, extract_headings) and of validate-skill.sh, so this adds no
# new runtime requirement. validate-skill.sh:96 has its OWN single-argument
# extract_field which folds block scalars but does not unescape; it is the
# reference for the folding logic here, not shared code — the signatures differ.
#
# Portability: POSIX awk only, so this runs on macOS BSD awk and gawk alike. The
# quote characters are written as the octal escapes \047 and \042 so that no
# literal ' has to appear inside the shell-single-quoted program body.
#
# Not handled, deliberately — this list is exhaustive as of the audit below, not
# a sample:
#   - a trailing `# comment` on a plain scalar is preserved rather than stripped
#     (the old reader kept it too; changing that is unrelated scope);
#   - flow collections/anchors/aliases are not parsed;
#   - a QUOTED scalar wrapped across several lines (valid YAML line folding) is
#     read as its first line only, so it keeps a leading quote and loses the
#     rest. Block scalars are the supported way to wrap, and are handled above.
#   - double-quoted \uXXXX / \xXX numeric escapes yield the literal letter, not
#     the code point; only \n, \t, \r are decoded specially.
# Audited across all 44 SKILL.md files in the monorepo: none uses a flow
# collection, anchor, numeric escape, or a multi-line quoted scalar for a
# top-level field, so every one of these is latent rather than live. Re-run that
# audit before relying on this list.
extract_field() {
  local skill_md="$1"
  local field="$2"
  awk -v field="$field" '
    BEGIN { SQ = "\047"; DQ = "\042" }

    # Double-quoted YAML: \n, \t and \r become the control characters; every
    # other \<c> yields a literal <c>, which is what turns \" into " and \\
    # into \. Scanned left to right in ONE pass so a trailing \\" cannot be
    # mistaken for an escaped quote.
    function unescape_double(s,   out, i, n, c) {
      out = ""; n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c == "\\" && i < n) {
          i++
          c = substr(s, i, 1)
          if (c == "n")      out = out "\n"
          else if (c == "t") out = out "\t"
          else if (c == "r") out = out "\r"
          else               out = out c
        } else {
          out = out c
        }
      }
      return out
    }

    # Single-quoted YAML has exactly one escape: a doubled quote.
    function unescape_single(s,   out, i, n, c) {
      out = ""; n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c == SQ && substr(s, i + 1, 1) == SQ) { out = out SQ; i++ }
        else out = out c
      }
      return out
    }

    # Collect the frontmatter into an array rather than streaming it: a block
    # scalar needs the lines AFTER the key, which a line-at-a-time reader
    # cannot see.
    $0 == "---" { d++; if (d >= 2) exit; next }
    d == 1 { fm[++nf] = $0 }

    END {
      pat = "^" field ":"
      for (i = 1; i <= nf; i++) if (fm[i] ~ pat) { idx = i; break }
      if (!idx) exit 0

      val = fm[idx]
      sub(pat "[ \t]*", "", val)
      sub(/[ \t]+$/, "", val)

      # Block scalar: > or |, with optional indentation and chomping indicators
      # and an optional trailing comment.
      if (val ~ /^[|>][0-9]*[+-]?[ \t]*(#.*)?$/) {
        fold = (substr(val, 1, 1) == ">")
        out = ""; first = 1
        for (i = idx + 1; i <= nf; i++) {
          line = fm[i]
          if (line ~ /^[^ \t]/) break        # a non-indented line ends the block
          if (line ~ /^[ \t]*$/) continue    # skip blanks (no double separators)
          sub(/^[ \t]+/, "", line)
          if (first) { out = line; first = 0 }
          else       { out = out (fold ? " " : "\n") line }
        }
        printf "%s\n", out
        exit 0
      }

      # Quoted scalar: strip ONLY when the same quote both opens and closes the
      # value. `"quoted" is a word` opens with a quote but does not close with
      # one, so it is a plain scalar and is returned untouched.
      n = length(val)
      if (n >= 2) {
        f = substr(val, 1, 1); l = substr(val, n, 1)
        if (f == DQ && l == DQ) { printf "%s\n", unescape_double(substr(val, 2, n - 2)); exit 0 }
        if (f == SQ && l == SQ) { printf "%s\n", unescape_single(substr(val, 2, n - 2)); exit 0 }
      }

      # printf "%s", never a bare value used as a format: descriptions contain %.
      printf "%s\n", val
    }
  ' "$skill_md"
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
#
# printf, not `echo "$1"`: bash's builtin echo consumes a leading -n/-e/-E as an
# option, so a description legitimately starting with one would lose it (and,
# for -n, the trailing newline too). Unreachable in today's catalogue, which is
# exactly why it would not be noticed when it stops being unreachable.
short_desc() {
  printf '%s\n' "$1" | sed 's/\. Use when:.*/\./'
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
# Requires: SKILLS_HOME set by the caller. Deliberately unwrapped, unlike
#   MONOREPO_DIR below — an unset SKILLS_HOME must abort rather than silently
#   resolve to "/<name>/SKILL.md".
#
#   An earlier version said "every current caller sets it before sourcing this
#   file". That is FALSE: "before sourcing this file" ties "caller" to the
#   scripts that source _lib.sh, and two of the six do not set SKILLS_HOME.
#   Measured, because the first correction of this comment ALSO got it wrong —
#   it said three, having inherited the list from the MONOREPO_DIR paragraph
#   below without re-deriving it:
#
#     script                     sets SKILLS_HOME   calls skill_source_dir
#     prepare-plugin.sh                 no                   no
#     prepare-skill-repo.sh             no                   no
#     release-monorepo.sh               yes                  no
#     sync-individual-repos.sh          yes                  no      <- sets it
#     sync-monorepo.sh                  yes                  yes
#     validate-pre-sync.sh              yes                  yes
#
#   What is true is narrower: every caller of this FUNCTION sets it. Sourcing
#   is not calling, and the two that do not set it never call it.
#
#   Note this is the same shape as the MONOREPO_DIR case documented two
#   paragraphs down — correct today only because the call site that would break
#   it does not exist yet. Stated here too so the two read consistently rather
#   than one carrying the caveat and the other implying a guarantee.
#
#   Hence the explicit guard below. `set -u` alone reports
#   "_lib.sh: line NNN: SKILLS_HOME: unbound variable", which blames THIS file
#   for a contract the caller broke; the guard names the calling script instead.
#   It does not disturb the ratified bare-$SKILLS_HOME decision — an unset value
#   still aborts loudly rather than silently resolving to "/<name>/SKILL.md".
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
  if [[ -z "${SKILLS_HOME:-}" ]]; then
    # rc 2, matching the usage-error code the entry-point scripts already use,
    # because this IS a usage error — a caller-contract breach, not a lookup
    # failure. $0 names the script that forgot, which is the whole point.
    echo "Error: skill_source_dir() requires SKILLS_HOME; it is unset (caller: $0)." >&2
    echo "       Sourcing _lib.sh does not set it. sync-monorepo.sh and" >&2
    echo "       validate-pre-sync.sh default it to \$HOME/.claude/skills." >&2
    return 2
  fi
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
