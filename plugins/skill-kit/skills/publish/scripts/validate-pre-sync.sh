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
  1  One or more skills have version/CHANGELOG mismatches; on a plugin-only
     monorepo, a plugin fails validation or the catalogue has drift (see below)
  2  Usage error

Plugin-only monorepo (#190):
  A monorepo that has plugins/*/.claude-plugin/plugin.json and no top-level
  skill directory has no top-level skills to check. There this gate runs
  validate-plugin.sh on every plugin (standalone ones skipped) and then
  catalogue.py --check, and exits 1 if either fails. --add is refused (exit 1).
  --json keeps its shape (total, pass and fail count plugins; results has one
  {"plugin","status"} item each) and adds "layout": "plugin-only",
  "catalogue": "clean|drift|error" and "catalogue_lines".

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
# Whether --add was PASSED, not what it was passed: `--add ""` is an operator
# asking to add a skill and naming none. Gating on `-n` skipped the branch
# wholesale, making the run identical to one with no --add — the same silent
# no-op the `--add ,` guard below refuses, via a shorter argument.
ADD_GIVEN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --add)   ADD_SKILLS="$2"; ADD_GIVEN=true; shift 2 ;;
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

# #190: a plugin-only monorepo (see the note in _lib.sh) is checked plugin by
# plugin, then with catalogue.py --check, the same checks sync-monorepo.sh runs
# before it writes. It always exits here.
if is_plugin_only_monorepo "$MONOREPO_DIR"; then
  if $ADD_GIVEN; then
    echo "Error: validate-pre-sync.sh: --add: plugin-only monorepo has no top-level skills; edit plugins/<group>/skills/<name>/ and run sync" >&2
    exit 1
  fi
  STANDALONE_PLUGINS=""
  load_standalone_plugins "$SCRIPT_DIR" || exit 1
  PO_LINES="$(validate_all_plugins "$MONOREPO_DIR" "$SCRIPT_DIR/validate-plugin.sh" || true)"
  # run_catalogue (_lib.sh) turns a crash into exit 2, never drift.
  run_catalogue "$SCRIPT_DIR/catalogue.py" --check "$MONOREPO_DIR"
  if $JSON_MODE; then
    python3 - "$CAT_RC" "$CAT_OUT" "$PO_LINES" <<'PY'
import json, sys
rc, cat_out, lines = int(sys.argv[1]), sys.argv[2], sys.argv[3]
results = []
for l in lines.splitlines():
    parts = l.split()
    if len(parts) == 2 and parts[0] in ("PASS", "FAIL") and parts[1].startswith("plugins/"):
        results.append({"plugin": parts[1][len("plugins/"):], "status": parts[0].lower()})
fail = sum(1 for r in results if r["status"] == "fail")
print(json.dumps({
    "layout": "plugin-only",
    "total": len(results), "pass": len(results) - fail, "fail": fail,
    "missing_changelog": 0,
    "results": results,
    "catalogue": {0: "clean", 1: "drift"}.get(rc, "error"),
    "catalogue_lines": [l for l in cat_out.splitlines() if l],
}, indent=2))
PY
  else
    echo "=== Pre-Sync Validation (plugin-only monorepo) ==="
    echo ""
    printf '%s\n' "$PO_LINES"
    echo ""
    if [[ $CAT_RC -eq 0 ]]; then
      echo "catalogue.py --check: clean"
    else
      echo "catalogue.py --check: $([[ $CAT_RC -eq 1 ]] && echo drift || echo "cannot run")"
      printf '%s\n' "$CAT_OUT" | sed 's/^/  /'
    fi
  fi
  if printf '%s\n' "$PO_LINES" | grep -q '^  FAIL  plugins/' || [[ $CAT_RC -ne 0 ]]; then
    if ! $JSON_MODE; then
      echo ""
      echo "BLOCKED: fix the plugins and the catalogue above before syncing."
      echo "Run catalogue.py <monorepo> to write the catalogue; a skill or agent a plugin README does not name needs a hand edit."
    fi
    exit 1
  fi
  if ! $JSON_MODE; then
    echo ""
    echo "Every plugin passes and the catalogue is clean. Safe to sync."
  fi
  exit 0
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
SKILLS=$(list_top_level_candidates "$MONOREPO_DIR" | sort)

if $ADD_GIVEN; then
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
  # script blind to every in-repo-source-only skill (the spec-* family, and
  # github-board-move before it moved into the github-board plugin) — it fell
  # into the branch below, was silently skipped, and
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
