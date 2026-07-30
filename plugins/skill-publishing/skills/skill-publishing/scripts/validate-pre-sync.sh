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
  --add <names>  Also validate these comma-separated skills, which need not be
                 in the monorepo yet. Named for sync-monorepo.sh --add, whose
                 skill set this gate cannot otherwise see: discovery below scans
                 the monorepo only. It matches that flag's SET, not its
                 strictness — a name that resolves nowhere is announced as a
                 SKIP here and the run can still report "Safe to sync", whereas
                 sync-monorepo.sh --add refuses an unresolvable name outright.
                 The sync is the gate that refuses; this one reports.
  --fix          Show what needs to be fixed (does not auto-fix)
  --json         Machine-readable JSON output
  -h, --help     Show this help

Exit codes:
  0  All skills have matching CHANGELOG entries
  1  One or more skills have version/CHANGELOG mismatches
  2  Usage error

Examples:
  validate-pre-sync.sh ~/dev/claude-code-skills
  validate-pre-sync.sh ~/dev/claude-code-skills --fix
  validate-pre-sync.sh ~/dev/claude-code-skills --json
  validate-pre-sync.sh --add brandnew ~/dev/claude-code-skills   # before --add
EOF
  exit 0
}

# --- Parse arguments ---
FIX_MODE=false
JSON_MODE=false
MONOREPO_DIR=""
ADD_SKILLS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --add)   ADD_SKILLS="$2"; shift 2 ;;
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

# --- Discover skills to validate ---
# The monorepo scan alone is blind to any skill that does not have a directory
# there yet — which is every `sync-monorepo.sh --add <new-skill>`, the single
# highest-risk case for the version/CHANGELOG mismatch this gate exists to
# catch. Measured before the fix: a `brandnew` skill at v2.0.0 whose newest
# CHANGELOG entry was 1.0.0 gave "Total: 1 | Pass: 1 | Fail: 0 … Safe to sync."
# at rc=0, and the very next command published that exact mismatch. #78 moved
# such a skill from "skipped silently mid-loop" to "never enumerated"; this
# closes the other half.
#
# Named skills are unioned in rather than enumerating all of $SKILLS_HOME.
# Enumerating the home would report on skills no sync is going to touch — a
# gate that fails on unrelated local work is a gate people stop running — and
# would not match any actual sync shape: a discovery run syncs the monorepo's
# skills, `--skills` syncs exactly what is named, and `--add` syncs the
# monorepo's plus what is named. This union is that third shape.
SKILLS=$(find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
  ! -name '.git' ! -name '.github' ! -name '.*' \
  ! -name 'plugins' ! -name 'scripts' \
  -exec basename {} \; 2>/dev/null | sort)

if [[ -n "$ADD_SKILLS" ]]; then
  # Only the user-typed value is comma-split; the discovered list stays
  # newline-separated, so a directory name containing a comma survives.
  #
  # The emptiness test is on the ADD-CONTRIBUTED names, not on the union. A
  # union test looks equivalent and is not: `--add ,` reduces to blank lines,
  # the union is still non-empty because the monorepo scan filled it, and the
  # run would silently degrade to "no extra skills" while reporting success.
  # Caught in this script's own first draft.
  #
  # An earlier version of this comment said sync-monorepo.sh "already refuses
  # by name for this exact argument". It did not — it had the union bug too,
  # and refused `--add ,` only against an EMPTY monorepo, where nothing was at
  # stake. Both sides now test the add-contributed names.
  ADD_SPLIT=$(printf '%s\n' "$ADD_SKILLS" | tr ',' '\n' | grep -v '^$' || true)
  if [[ -z "$ADD_SPLIT" ]]; then
    echo "Error: --add produced no skill names from: '$ADD_SKILLS'" >&2
    exit 2
  fi
  SKILLS=$(printf '%s\n%s\n' "$SKILLS" "$ADD_SPLIT" | sort -u | grep -v '^$' || true)
fi

TOTAL=0
PASS=0
FAIL=0
MISSING_CL=0
RESULTS=""
JSON_ITEMS=""

# Line-wise, not `for SKILL_NAME in $SKILLS` (issue #81's shape): unquoted word
# splitting would break on any skill name containing whitespace or a glob
# character. A here-string, not a pipe — TOTAL/PASS/FAIL/RESULTS/JSON_ITEMS all
# have to survive in the current shell, and a pipe would run the loop body in a
# subshell and silently discard every one of them.
#
# `<&3` / `3<<<`, not plain stdin: `done <<< "$SKILLS"` would make the skill
# list the loop BODY's stdin, and this body shells out to grep and sed (via
# extract_version) on every iteration. A child that reads stdin would eat the
# rest of the list, and the loop would exit early having examined only the
# skills read so far — while still printing "Safe to sync" over a TOTAL that
# agrees with the truncation, since TOTAL counts the same loop.
#
# `3<<<` plus `</dev/null`, and the two are not equally strong. fd 3 is
# INHERITED by children like any other descriptor, so a child that deliberately
# reads `<&3` still eats the list — measured. What fd 3 buys is that stdin is
# read by filters by nature while fd 3 is read by nothing unless written to.
# The `</dev/null` on the loop is what makes the stdin half unconditional: every
# child here (grep, sed, head) gets immediate EOF. Fuller reasoning at the main
# sync loop in sync-monorepo.sh; same treatment at every converted loop.
while IFS= read -r SKILL_NAME <&3; do
  [[ -z "$SKILL_NAME" ]] && continue

  # Resolve through skill_source_dir() (_lib.sh, issue #78) instead of
  # hardcoding "$SKILLS_HOME/$SKILL_NAME": that hardcoding is what made this
  # script blind to every in-repo-source-only skill (github-board-move, the
  # spec-* family) — it fell into the branch below, was silently skipped, and
  # never counted as anything, so the summary read "Safe to sync" without ever
  # having examined it. skill_source_dir() also doubles as the discovery
  # filter: a directory that is not a skill at all (docs/, build/) has no
  # SKILL.md under either $SKILLS_HOME or $MONOREPO_DIR either, so it resolves
  # empty and is skipped here exactly like a skill with no source anywhere —
  # neither is a failure, both are simply not examined.
  SKILL_SRC="$(skill_source_dir "$SKILL_NAME")"
  if [[ -z "$SKILL_SRC" ]]; then
    # Announce, don't silently drop — sync-monorepo.sh's filter_skill_candidates()
    # emits this same message shape for the same condition. A real skill that
    # has lost its source everywhere would otherwise vanish from the report
    # with no line to say so, a quieter instance of the exact defect #78 exists
    # to kill.
    printf '%s\n' "  SKIP (not a skill: no SKILL.md)  $SKILL_NAME" >&2
    continue
  fi
  SKILL_MD="$SKILL_SRC/SKILL.md"
  CHANGELOG="$SKILL_SRC/CHANGELOG.md"

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
done 3<<< "$SKILLS" </dev/null

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
  # '%b' — RESULTS is DATA, not a format string. It carries skill names and
  # CHANGELOG versions, so a directory named e.g. `pct%s-skill` had its `%s`
  # consumed as a conversion and printed as `pct-skill`: the operator is told a
  # directory name that does not exist on disk. Pre-existing, but #78 tripled
  # what flows through here by making in-repo-source skills reportable at all.
  # '%b' keeps the `\n` expansion the RESULTS strings rely on.
  printf '%b' "$RESULTS"
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
