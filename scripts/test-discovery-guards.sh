#!/usr/bin/env bash
set -euo pipefail

# test-discovery-guards.sh — Regression harness for the discovery scripts'
# glob/existence guards (spec-creator's discover-conventions.sh, and
# discover-project-architecture.sh once its cases are appended).
#
# Each script under test gets its own fixtures + assertions section below.
# `assert_eq` records a PASS/FAIL line and tracks a running failure count;
# the script exits non-zero at the end if any assertion failed.
#
# Usage:
#   ./test-discovery-guards.sh
#   DISCOVER_CONVENTIONS_SCRIPT=/tmp/pre.sh ./test-discovery-guards.sh   # point at a different script build

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISCOVER_CONVENTIONS_SCRIPT="${DISCOVER_CONVENTIONS_SCRIPT:-$REPO_ROOT/spec-creator/scripts/discover-conventions.sh}"

FAIL_COUNT=0

SCRATCH_DIR="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_DIR"' EXIT

assert_eq() {
    local description="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$expected], got [$actual])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ============================================================
# discover-conventions.sh
# ============================================================

# --- Fixture: flat story-only layout (no epic-* dirs) ---
FLAT_DIR="$SCRATCH_DIR/flat-project"
mkdir -p "$FLAT_DIR/specs"
touch "$FLAT_DIR/specs/story-1.1-alpha.md" \
      "$FLAT_DIR/specs/story-1.2-beta.md" \
      "$FLAT_DIR/specs/story-2.1-gamma.md"

FLAT_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$FLAT_DIR" --json)
FLAT_EPIC_STRUCTURE=$(echo "$FLAT_JSON" | jq -r '.epicStructure')
FLAT_EPICS=$(echo "$FLAT_JSON" | jq -c '[.epics[].epic] | map(tonumber)')

assert_eq "flat story-only layout: epicStructure == flat" "flat" "$FLAT_EPIC_STRUCTURE"
assert_eq "flat story-only layout: epics == [1,2]" "[1,2]" "$FLAT_EPICS"

# --- Fixture: epic-* subdirs (positive control) ---
EPIC_SUBDIRS_DIR="$SCRATCH_DIR/epic-subdirs-project"
mkdir -p "$EPIC_SUBDIRS_DIR/specs/epic-1" "$EPIC_SUBDIRS_DIR/specs/epic-2"

EPIC_SUBDIRS_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$EPIC_SUBDIRS_DIR" --json)
EPIC_SUBDIRS_STRUCTURE=$(echo "$EPIC_SUBDIRS_JSON" | jq -r '.epicStructure')

assert_eq "epic-* subdirs (positive control): epicStructure == epic-subdirs" "epic-subdirs" "$EPIC_SUBDIRS_STRUCTURE"

# --- Fixture: numbered subdirs, no epic-* (positive control, guards line 77) ---
NUMBERED_SUBDIRS_DIR="$SCRATCH_DIR/numbered-subdirs-project"
mkdir -p "$NUMBERED_SUBDIRS_DIR/specs/1-foo" "$NUMBERED_SUBDIRS_DIR/specs/2-bar"

NUMBERED_SUBDIRS_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$NUMBERED_SUBDIRS_DIR" --json)
NUMBERED_SUBDIRS_STRUCTURE=$(echo "$NUMBERED_SUBDIRS_JSON" | jq -r '.epicStructure')

assert_eq "numbered subdirs, no epic-* (positive control): epicStructure == numbered-subdirs" "numbered-subdirs" "$NUMBERED_SUBDIRS_STRUCTURE"

# --- Fixture: empty specs/ ---
EMPTY_DIR="$SCRATCH_DIR/empty-project"
mkdir -p "$EMPTY_DIR/specs"

EMPTY_JSON=$("$DISCOVER_CONVENTIONS_SCRIPT" "$EMPTY_DIR" --json)
EMPTY_STRUCTURE=$(echo "$EMPTY_JSON" | jq -r '.epicStructure')

assert_eq "empty specs/: epicStructure == flat" "flat" "$EMPTY_STRUCTURE"

# ============================================================
# (discover-project-architecture.sh cases appended here by a later task)
# ============================================================

echo ""
if [[ "$FAIL_COUNT" -eq 0 ]]; then
    echo "All assertions passed."
    exit 0
else
    echo "$FAIL_COUNT assertion(s) failed."
    exit 1
fi
