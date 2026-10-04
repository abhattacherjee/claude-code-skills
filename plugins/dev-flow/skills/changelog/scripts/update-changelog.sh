#!/usr/bin/env bash
# update-changelog.sh — Generate or update CHANGELOG.md entries from git commits
# Reads commit history since last changelog entry and categorizes changes.
set -eu

TODAY=$(date +%Y-%m-%d)

# Defaults
DRY_RUN=false
REPO_DIR=""
SINCE=""
VERSION=""
MODE="unreleased"  # unreleased | version

usage() {
  cat <<'EOF'
Usage: update-changelog.sh [options] [repo-directory]

Generates CHANGELOG.md entries from git commit history.
Categorizes changes into Added/Changed/Fixed/Removed/Testing/Documentation.

Options:
  --dry-run              Preview changelog entry without writing
  --since <ref>          Git ref to start from (tag, branch or commit)
                         Default: auto-detect from last changelog version tag
  --version <ver>        Create a versioned entry (e.g., "1.2.0")
                         Default: update [Unreleased] section
  -h, --help             Show this help

Examples:
  update-changelog.sh                          # Update [Unreleased] in current dir
  update-changelog.sh --version 2.0.0          # Create versioned entry
  update-changelog.sh --since v1.0.0           # Changes since v1.0.0
  update-changelog.sh --dry-run ~/my-project   # Preview for specific repo
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=true; shift ;;
    --since)      [[ $# -ge 2 ]] || { echo "Error: --since needs a value" >&2; exit 1; }
                  SINCE="$2"; shift 2 ;;
    --version)    [[ $# -ge 2 ]] || { echo "Error: --version needs a value" >&2; exit 1; }
                  VERSION="$2"; MODE="version"; shift 2 ;;
    -h|--help)    usage ;;
    -*)           echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)            REPO_DIR="$1"; shift ;;
  esac
done

# Default to current directory
if [[ -z "$REPO_DIR" ]]; then
  REPO_DIR="$(pwd)"
fi

REPO_DIR="$(cd "$REPO_DIR" && pwd)"
CHANGELOG="$REPO_DIR/CHANGELOG.md"

# Verify it's a git repo (.git is a file, not a directory, in a worktree)
if ! git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: $REPO_DIR is not a git repository" >&2
  exit 1
fi

cd "$REPO_DIR"

# --- Resolve --since to a commit ---
# resolve_ref <name>: print the commit SHA for <name>, or fail. The name must look like a
# tag, branch or SHA and must not start with "-", so it can never act as a git option.
# Names come from the command line and from CHANGELOG.md, which is untrusted input.
resolve_ref() {
  local name="$1"
  [[ "$name" =~ ^[0-9A-Za-z._/-]+$ && "$name" != -* ]] || return 1
  git rev-parse --verify --quiet "${name}^{commit}"
}

SINCE_LABEL="$SINCE"
if [[ -n "$SINCE" ]]; then
  if ! SINCE=$(resolve_ref "$SINCE"); then
    echo "Error: --since '$SINCE_LABEL' is not a tag, branch or commit in this repository" >&2
    exit 1
  fi
else
  # Try: last semver tag reachable from HEAD (v1.2.3 or 1.2.3; not sync-2026-02-24 and the like)
  LAST_TAG=$(git tag -l 'v[0-9]*' '[0-9]*' --merged HEAD --sort=-v:refname 2>/dev/null | head -1 || true)
  if [[ -n "$LAST_TAG" ]] && SINCE=$(resolve_ref "$LAST_TAG"); then
    SINCE_LABEL="$LAST_TAG"
    echo "Auto-detected: changes since tag $SINCE_LABEL"
  else
    SINCE=""
    # Try: extract version from CHANGELOG.md
    if [[ -f "$CHANGELOG" ]]; then
      LAST_VERSION=$(grep -m1 '^## \[' "$CHANGELOG" | sed 's/## \[\(.*\)\].*/\1/' || echo "")
      # Only a plain name is tried. Anything else (spaces, a leading "-") is skipped.
      if [[ -n "$LAST_VERSION" && "$LAST_VERSION" != "Unreleased" && "$LAST_VERSION" =~ ^[0-9A-Za-z._-]+$ && "$LAST_VERSION" != -* ]]; then
        # Look for a matching tag
        for prefix in "v" ""; do
          if SINCE=$(resolve_ref "${prefix}${LAST_VERSION}"); then
            SINCE_LABEL="${prefix}${LAST_VERSION}"
            echo "Auto-detected: changes since $SINCE_LABEL (from CHANGELOG.md)"
            break
          fi
          SINCE=""
        done
      fi
    fi
    # Fallback: all commits
    if [[ -z "$SINCE" ]]; then
      # An empty SINCE means the whole history, root commit included ("root..HEAD" skips it).
      SINCE_LABEL="$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)"
      echo "No tags found, using all commits since initial"
    fi
  fi
fi

# --- Gather commits ---
if [[ -n "$SINCE" ]]; then
  RANGE="$SINCE..HEAD"
  DIFF_FROM="$SINCE"
else
  RANGE="HEAD"
  DIFF_FROM="$(git hash-object -t tree /dev/null)"  # the empty tree
fi
COMMITS=$(git log "$RANGE" --pretty=format:"%s" --no-merges)
if [[ -z "$COMMITS" ]]; then
  echo "No new commits since $SINCE_LABEL"
  exit 0
fi

COMMIT_COUNT=$(echo "$COMMITS" | wc -l | tr -d ' ')
echo "Found $COMMIT_COUNT commits since $SINCE_LABEL"
echo ""

# --- Gather changed files for categorization ---
CHANGED_FILES=$(git diff --name-only "$DIFF_FROM" HEAD)

# --- Categorize commits by conventional commit prefix ---
ADDED=""
CHANGED=""
FIXED=""
REMOVED=""
TESTING=""
DOCS=""
OTHER=""

while IFS= read -r msg; do
  [[ -z "$msg" ]] && continue

  # Strip scope: "feat(auth): message" -> "feat" + "message"
  prefix=$(echo "$msg" | sed -nE 's/^([a-z]+)(\([^)]*\))?[!]?:.*/\1/p')
  body=$(echo "$msg" | sed -E 's/^[a-z]+(\([^)]*\))?[!]?:[[:space:]]*//')

  # If no conventional prefix, use the full message
  if [[ -z "$prefix" ]]; then
    body="$msg"
    prefix="other"
  fi

  # Categorize
  case "$prefix" in
    feat|add)     ADDED="${ADDED}- ${body}"$'\n' ;;
    fix)          FIXED="${FIXED}- ${body}"$'\n' ;;
    docs)         DOCS="${DOCS}- ${body}"$'\n' ;;
    test)         TESTING="${TESTING}- ${body}"$'\n' ;;
    refactor|perf|style|chore|build|ci)
                  CHANGED="${CHANGED}- ${body}"$'\n' ;;
    revert)       REMOVED="${REMOVED}- ${body}"$'\n' ;;
    *)            OTHER="${OTHER}- ${body}"$'\n' ;;
  esac
done <<< "$COMMITS"

# If no conventional commits found, fall back to file-based categorization
if [[ -z "$ADDED" && -z "$CHANGED" && -z "$FIXED" && -z "$REMOVED" && -z "$TESTING" && -z "$DOCS" && -n "$OTHER" ]]; then
  # Re-categorize by looking at changed files
  has_src=false
  has_test=false
  has_docs=false

  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    case "$f" in
      *.test.*|*.spec.*|tests/*|test/*|__tests__/*) has_test=true ;;
      *.md|docs/*|README*|CHANGELOG*) has_docs=true ;;
      src/*|lib/*|scripts/*) has_src=true ;;
    esac
  done <<< "$CHANGED_FILES"

  # Move OTHER to most appropriate category
  if $has_src; then
    CHANGED="$OTHER"
    OTHER=""
  fi
fi

# --- Build changelog entry ---
if [[ "$MODE" == "version" ]]; then
  ENTRY_HEADER="## [$VERSION] - $TODAY"
else
  ENTRY_HEADER="## [Unreleased]"
fi

ENTRY="$ENTRY_HEADER"

# Add commit range summary
ENTRY="$ENTRY
"

if [[ -n "$ADDED" ]]; then
  ENTRY="${ENTRY}
### Added

${ADDED}"
fi

if [[ -n "$CHANGED" ]]; then
  ENTRY="${ENTRY}
### Changed

${CHANGED}"
fi

if [[ -n "$FIXED" ]]; then
  ENTRY="${ENTRY}
### Fixed

${FIXED}"
fi

if [[ -n "$REMOVED" ]]; then
  ENTRY="${ENTRY}
### Removed

${REMOVED}"
fi

if [[ -n "$TESTING" ]]; then
  ENTRY="${ENTRY}
### Testing

${TESTING}"
fi

if [[ -n "$DOCS" ]]; then
  ENTRY="${ENTRY}
### Documentation

${DOCS}"
fi

if [[ -n "$OTHER" ]]; then
  ENTRY="${ENTRY}
### Other

${OTHER}"
fi

# Each section ends with a newline, so a blank line separates it from the next heading.
ENTRY="${ENTRY%$'\n'}"

# --- Output ---
echo "Generated changelog entry:"
echo "─────────────────────────────"
echo "$ENTRY"
echo "─────────────────────────────"

if $DRY_RUN; then
  echo ""
  echo "Dry run — no files written."
  exit 0
fi

# --- Write to CHANGELOG.md ---
# Never write through a symlink: a CHANGELOG.md that points outside the repo would
# overwrite that file. The new content goes to a temp file in the same directory
# and is renamed over CHANGELOG.md.
if [[ -L "$CHANGELOG" ]]; then
  echo "Error: $CHANGELOG is a symlink; refusing to write through it" >&2
  exit 1
fi
TMPFILE=$(mktemp "$REPO_DIR/.CHANGELOG.XXXXXX")
trap 'rm -f "$TMPFILE"' EXIT

if [[ ! -f "$CHANGELOG" ]]; then
  # Create new changelog
  chmod 644 "$TMPFILE"
  printf '# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n%s\n' "$ENTRY" > "$TMPFILE"
  mv "$TMPFILE" "$CHANGELOG"
  echo ""
  echo "Created $CHANGELOG"
else
  # Insert entry into existing changelog. The entry goes to awk through the
  # environment: `awk -v` would turn a backslash in a commit subject into an escape.
  cp -p "$CHANGELOG" "$TMPFILE"
  export ENTRY

  if [[ "$MODE" == "unreleased" ]]; then
    # Replace existing [Unreleased] section or insert after header
    if grep -q '^\## \[Unreleased\]' "$CHANGELOG"; then
      # Replace the [Unreleased] block (up to next ## [)
      awk '
        /^## \[Unreleased\]/ {
          print ENVIRON["ENTRY"]
          skip=1
          next
        }
        /^## \[/ && skip {
          skip=0
          print ""
          print $0
          next
        }
        !skip { print }
      ' "$CHANGELOG" > "$TMPFILE"
    else
      # Insert after the header lines (first blank line after title)
      awk '
        !inserted && /^$/ && NR > 1 {
          print ""
          print ENVIRON["ENTRY"]
          inserted=1
        }
        { print }
      ' "$CHANGELOG" > "$TMPFILE"
    fi
  else
    # Version mode: insert after header, before first ## [
    awk '
      /^## \[Unreleased\]/ {
        print $0
        # Skip empty unreleased section
        next
      }
      /^## \[/ && !inserted {
        print ENVIRON["ENTRY"]
        print ""
        inserted=1
      }
      { print }
      END {
        if (!inserted) {
          print ""
          print ENVIRON["ENTRY"]
        }
      }
    ' "$CHANGELOG" > "$TMPFILE"
  fi

  mv "$TMPFILE" "$CHANGELOG"
  echo ""
  echo "Updated $CHANGELOG"
fi
