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
  --since <ref>          Git ref to start from (tag, commit, date)
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
    --since)      SINCE="$2"; shift 2 ;;
    --version)    VERSION="$2"; MODE="version"; shift 2 ;;
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

# Verify it's a git repo
if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Error: $REPO_DIR is not a git repository" >&2
  exit 1
fi

cd "$REPO_DIR"

# --- Auto-detect --since if not provided ---
if [[ -z "$SINCE" ]]; then
  # Try: last version tag
  LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
  if [[ -n "$LAST_TAG" ]]; then
    SINCE="$LAST_TAG"
    echo "Auto-detected: changes since tag $SINCE"
  else
    # Try: extract version from CHANGELOG.md
    if [[ -f "$CHANGELOG" ]]; then
      LAST_VERSION=$(grep -m1 '^## \[' "$CHANGELOG" | sed 's/## \[\(.*\)\].*/\1/' || echo "")
      if [[ -n "$LAST_VERSION" && "$LAST_VERSION" != "Unreleased" ]]; then
        # Look for a matching tag
        for prefix in "v" ""; do
          if git rev-parse "${prefix}${LAST_VERSION}" >/dev/null 2>&1; then
            SINCE="${prefix}${LAST_VERSION}"
            echo "Auto-detected: changes since $SINCE (from CHANGELOG.md)"
            break
          fi
        done
      fi
    fi
    # Fallback: all commits
    if [[ -z "$SINCE" ]]; then
      SINCE=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
      echo "No tags found, using all commits since initial"
    fi
  fi
fi

# --- Gather commits ---
COMMITS=$(git log "$SINCE"..HEAD --pretty=format:"%s" --no-merges 2>/dev/null || echo "")
if [[ -z "$COMMITS" ]]; then
  echo "No new commits since $SINCE"
  exit 0
fi

COMMIT_COUNT=$(echo "$COMMITS" | wc -l | tr -d ' ')
echo "Found $COMMIT_COUNT commits since $SINCE"
echo ""

# --- Gather changed files for categorization ---
CHANGED_FILES=$(git diff --name-only "$SINCE"..HEAD 2>/dev/null || echo "")

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
    feat|add)     ADDED="${ADDED}- ${body}\n" ;;
    fix)          FIXED="${FIXED}- ${body}\n" ;;
    docs)         DOCS="${DOCS}- ${body}\n" ;;
    test)         TESTING="${TESTING}- ${body}\n" ;;
    refactor|perf|style|chore|build|ci)
                  CHANGED="${CHANGED}- ${body}\n" ;;
    revert)       REMOVED="${REMOVED}- ${body}\n" ;;
    *)            OTHER="${OTHER}- ${body}\n" ;;
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

$(echo -e "$ADDED")"
fi

if [[ -n "$CHANGED" ]]; then
  ENTRY="${ENTRY}
### Changed

$(echo -e "$CHANGED")"
fi

if [[ -n "$FIXED" ]]; then
  ENTRY="${ENTRY}
### Fixed

$(echo -e "$FIXED")"
fi

if [[ -n "$REMOVED" ]]; then
  ENTRY="${ENTRY}
### Removed

$(echo -e "$REMOVED")"
fi

if [[ -n "$TESTING" ]]; then
  ENTRY="${ENTRY}
### Testing

$(echo -e "$TESTING")"
fi

if [[ -n "$DOCS" ]]; then
  ENTRY="${ENTRY}
### Documentation

$(echo -e "$DOCS")"
fi

if [[ -n "$OTHER" ]]; then
  ENTRY="${ENTRY}
### Other

$(echo -e "$OTHER")"
fi

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
if [[ ! -f "$CHANGELOG" ]]; then
  # Create new changelog
  cat > "$CHANGELOG" <<EOF
# Changelog

All notable changes to this project will be documented in this file.

$ENTRY
EOF
  echo ""
  echo "Created $CHANGELOG"
else
  # Insert entry into existing changelog
  TMPFILE=$(mktemp)

  if [[ "$MODE" == "unreleased" ]]; then
    # Replace existing [Unreleased] section or insert after header
    if grep -q '^\## \[Unreleased\]' "$CHANGELOG"; then
      # Replace the [Unreleased] block (up to next ## [)
      awk -v entry="$ENTRY" '
        /^## \[Unreleased\]/ {
          print entry
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
      awk -v entry="$ENTRY" '
        !inserted && /^$/ && NR > 1 {
          print ""
          print entry
          inserted=1
        }
        { print }
      ' "$CHANGELOG" > "$TMPFILE"
    fi
  else
    # Version mode: insert after header, before first ## [
    awk -v entry="$ENTRY" '
      /^## \[Unreleased\]/ {
        print $0
        # Skip empty unreleased section
        next
      }
      /^## \[/ && !inserted {
        print entry
        print ""
        inserted=1
      }
      { print }
      END {
        if (!inserted) {
          print ""
          print entry
        }
      }
    ' "$CHANGELOG" > "$TMPFILE"
  fi

  mv "$TMPFILE" "$CHANGELOG"
  echo ""
  echo "Updated $CHANGELOG"
fi
