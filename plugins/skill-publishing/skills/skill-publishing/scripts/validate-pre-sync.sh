#!/usr/bin/env bash
# validate-pre-sync.sh — Pre-sync gate: verify each skill's CHANGELOG matches its version
# Catches the common failure where SKILL.md version is bumped but CHANGELOG.md is not updated.
#
# Usage:
#   ./scripts/validate-pre-sync.sh <monorepo-dir>             # Validate all synced skills
#   ./scripts/validate-pre-sync.sh <monorepo-dir> --fix        # Report what needs fixing
#   ./scripts/validate-pre-sync.sh <monorepo-dir> --json       # Machine-readable output
#   ./scripts/validate-pre-sync.sh --help
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"

# Load shared library
source "$SCRIPT_DIR/_lib.sh"
DRY_RUN=false  # Required by _lib.sh

usage() {
  cat <<'EOF'
Usage: validate-pre-sync.sh [options] <monorepo-dir>

Pre-sync validation gate. Checks that every skill about to be synced has:
  1. A CHANGELOG.md entry matching the version in SKILL.md frontmatter
  2. A CHANGELOG.md that exists (bare minimum)

Options:
  --fix     Show what needs to be fixed (does not auto-fix)
  --json    Machine-readable JSON output
  -h, --help  Show this help

Exit codes:
  0  All skills have matching CHANGELOG entries
  1  One or more skills have version/CHANGELOG mismatches
  2  Usage error

Examples:
  validate-pre-sync.sh ~/dev/claude-code-skills
  validate-pre-sync.sh ~/dev/claude-code-skills --fix
  validate-pre-sync.sh ~/dev/claude-code-skills --json
EOF
  exit 0
}

# --- Parse arguments ---
FIX_MODE=false
JSON_MODE=false
MONOREPO_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix)   FIX_MODE=true; shift ;;
    --json)  JSON_MODE=true; shift ;;
    -h|--help) usage ;;
    -*) echo "Error: Unknown option: $1" >&2; exit 2 ;;
    *)  MONOREPO_DIR="$1"; shift ;;
  esac
done

if [[ -z "$MONOREPO_DIR" ]]; then
  echo "Error: monorepo directory required. Use --help for usage." >&2
  exit 2
fi

if [[ ! -d "$MONOREPO_DIR" ]]; then
  echo "Error: $MONOREPO_DIR does not exist" >&2
  exit 2
fi

# --- Discover skills in monorepo ---
SKILLS=$(find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
  ! -name '.git' ! -name '.github' ! -name '.*' \
  ! -name 'plugins' ! -name 'scripts' \
  -exec basename {} \; 2>/dev/null | sort)

TOTAL=0
PASS=0
FAIL=0
MISSING_CL=0
RESULTS=""
JSON_ITEMS=""

for SKILL_NAME in $SKILLS; do
  SKILL_SRC="$SKILLS_HOME/$SKILL_NAME"
  SKILL_MD="$SKILL_SRC/SKILL.md"
  CHANGELOG="$SKILL_SRC/CHANGELOG.md"

  if [[ ! -f "$SKILL_MD" ]]; then
    continue  # Not a local skill (maybe only in monorepo)
  fi

  TOTAL=$((TOTAL + 1))
  VERSION=$(extract_version "$SKILL_MD")

  if [[ -z "$VERSION" ]]; then
    VERSION="(no version)"
  fi

  # Check 1: CHANGELOG exists
  if [[ ! -f "$CHANGELOG" ]]; then
    MISSING_CL=$((MISSING_CL + 1))
    FAIL=$((FAIL + 1))
    RESULTS="${RESULTS}FAIL  ${SKILL_NAME} v${VERSION} — no CHANGELOG.md\n"
    JSON_ITEMS="${JSON_ITEMS}{\"skill\":\"$SKILL_NAME\",\"version\":\"$VERSION\",\"status\":\"missing_changelog\",\"message\":\"No CHANGELOG.md found\"},"
    continue
  fi

  # Check 2: CHANGELOG has entry matching the SKILL.md version
  # Look for ## [VERSION] or ## [VERSION] - DATE
  if grep -qE "^## \[${VERSION}\]" "$CHANGELOG"; then
    PASS=$((PASS + 1))
    RESULTS="${RESULTS}PASS  ${SKILL_NAME} v${VERSION}\n"
    JSON_ITEMS="${JSON_ITEMS}{\"skill\":\"$SKILL_NAME\",\"version\":\"$VERSION\",\"status\":\"pass\",\"message\":\"CHANGELOG entry exists\"},"
  else
    FAIL=$((FAIL + 1))
    # Find what versions ARE in the CHANGELOG
    LATEST_CL_VERSION=$(grep -oE '^\#\# \[[0-9]+\.[0-9]+\.[0-9]+\]' "$CHANGELOG" | head -1 | sed 's/## \[//;s/\]//')
    if [[ -z "$LATEST_CL_VERSION" ]]; then
      LATEST_CL_VERSION="(none)"
    fi
    RESULTS="${RESULTS}FAIL  ${SKILL_NAME} — SKILL.md says v${VERSION} but CHANGELOG latest is v${LATEST_CL_VERSION}\n"
    JSON_ITEMS="${JSON_ITEMS}{\"skill\":\"$SKILL_NAME\",\"version\":\"$VERSION\",\"status\":\"version_mismatch\",\"changelog_version\":\"$LATEST_CL_VERSION\",\"message\":\"SKILL.md v$VERSION has no CHANGELOG entry (latest: v$LATEST_CL_VERSION)\"},"

    if $FIX_MODE; then
      RESULTS="${RESULTS}  FIX: Add a ## [$VERSION] entry to $CHANGELOG\n"
      RESULTS="${RESULTS}  Describe what changed from v${LATEST_CL_VERSION} to v${VERSION}\n"
    fi
  fi
done

# --- Output ---
if $JSON_MODE; then
  # Remove trailing comma from JSON items
  JSON_ITEMS="${JSON_ITEMS%,}"
  cat <<ENDJSON
{
  "total": $TOTAL,
  "pass": $PASS,
  "fail": $FAIL,
  "missing_changelog": $MISSING_CL,
  "results": [$JSON_ITEMS]
}
ENDJSON
else
  echo "=== Pre-Sync Validation ==="
  echo ""
  printf "$RESULTS"
  echo ""
  echo "Total: $TOTAL | Pass: $PASS | Fail: $FAIL"

  if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "BLOCKED: Fix the above issues before syncing to monorepo."
    echo "Each skill's CHANGELOG.md must have a ## [X.Y.Z] entry matching its SKILL.md version."
    if ! $FIX_MODE; then
      echo "Run with --fix for remediation guidance."
    fi
  else
    echo ""
    echo "All skills have matching CHANGELOG entries. Safe to sync."
  fi
fi

# Exit with error if any failures
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
