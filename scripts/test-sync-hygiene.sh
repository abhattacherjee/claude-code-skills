#!/usr/bin/env bash
set -euo pipefail

# test-sync-hygiene.sh — Regression harness for sync-monorepo.sh's monorepo
# hygiene fixes (issue #74). Three defects are locked in here:
#
#   1. discover_skills() treated every top-level monorepo directory as a skill,
#      so non-skill directories (docs/, build/) entered the sync loop and
#      produced spurious "ERROR: no SKILL.md" lines. Both directory-scan sites
#      now pipe through filter_skill_candidates().
#   2. The plugin auto-build stage built into ./build/<name> in the *caller's*
#      cwd, leaving an untracked build tree behind that the script's own
#      "Next steps: git add -A" banner would then commit. It now builds into a
#      mktemp -d stage removed by an EXIT trap.
#   3. Neither the repo's .gitignore nor the .gitignore template sync-monorepo.sh
#      writes into a freshly --init-ed monorepo listed build/.
#
# Every assertion below was proven to FAIL against the pre-fix script before
# being committed (see .superpowers/sdd/74-sync-monorepo-hygiene/task-3-report.md);
# an assertion that passes against unfixed code is worse than no assertion.
#
# The whole run is hermetic: a throwaway SKILLS_HOME and a throwaway monorepo
# are built under mktemp, and the sync is invoked from a throwaway cwd. The live
# repo is never passed to sync-monorepo.sh.
#
# Usage:
#   ./test-sync-hygiene.sh
#   SYNC_SCRIPT=/tmp/pre-fix/sync-monorepo.sh ./test-sync-hygiene.sh   # point at a different script build
#
# Note when overriding SYNC_SCRIPT: sync-monorepo.sh sources _lib.sh and shells
# out to prepare-plugin.sh from its own directory, so a copy must be placed in a
# directory holding the whole scripts/ set, not copied in isolation.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_SCRIPT="${SYNC_SCRIPT:-$REPO_ROOT/plugins/skill-publishing/skills/skill-publishing/scripts/sync-monorepo.sh}"

# The authoring source of truth for skill-publishing lives outside the repo.
# Checked when present (developer machines), reported as unavailable in CI.
LIVE_SYNC_SCRIPT="${LIVE_SYNC_SCRIPT:-$HOME/.claude/skills/skill-publishing/scripts/sync-monorepo.sh}"

# The harness runs under `set -euo pipefail`, so an unusable script under test
# would die with rc=127 and no summary — unhelpful for the documented
# "point this at a pre-fix build" workflow. Fail loudly instead.
if [[ ! -f "$SYNC_SCRIPT" ]]; then
    echo "FATAL: SYNC_SCRIPT points at a nonexistent file: $SYNC_SCRIPT" >&2
    exit 1
fi
if [[ ! -x "$SYNC_SCRIPT" ]]; then
    echo "FATAL: SYNC_SCRIPT is not executable: $SYNC_SCRIPT" >&2
    exit 1
fi

FAIL_COUNT=0
SKIPPED_COUNT=0

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

assert_contains() {
    local description="$1" needle="$2" haystack="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$haystack] to contain [$needle])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_not_contains() {
    local description="$1" needle="$2" haystack="$3"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$haystack] NOT to contain [$needle])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# Whole-line membership. Substring matching is too loose for the skill list:
# "build" is a substring of nothing here, but "docs" would match a future
# "docs-sync-on-pr" skill and quietly turn a real regression green.
assert_line_present() {
    local description="$1" needle="$2" haystack="$3"
    if printf '%s\n' "$haystack" | grep -qxF -- "$needle"; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected a line [$needle] in [$haystack])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_line_absent() {
    local description="$1" needle="$2" haystack="$3"
    if printf '%s\n' "$haystack" | grep -qxF -- "$needle"; then
        echo "FAIL: $description (found line [$needle] in [$haystack])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "PASS: $description"
    fi
}

# ============================================================
# Fixture
# ============================================================
#
#   skills-home/demo-skill/{SKILL.md,plugin-manifest.json}   the authoring source
#   monorepo/demo-skill/                                     local-source skill (positive control)
#   monorepo/inrepo-skill/SKILL.md                           in-repo-source-only skill (positive control)
#   monorepo/docs/                                           non-skill dir, must be filtered
#   monorepo/build/                                          non-skill dir, must be filtered
#   run-cwd/                                                 the sync is invoked from here
#
# monorepo/ deliberately has no .gitignore, so the sync CREATEs one and the
# embedded template is what gets asserted (write_file does not overwrite an
# existing .gitignore).
#
# The two positive-control skills are not redundant: skill_source_dir() has two
# branches, and demo-skill (which exists under BOTH skills-home/ and monorepo/)
# only ever exercises the first. inrepo-skill exists in the monorepo alone, so it
# is the only fixture that reaches the `elif [[ -f "$MONOREPO_DIR/$name/SKILL.md" ]]`
# fallback. That branch is load-bearing in the real repo — github-board-move and
# the three spec-* skills have no local copy and resolve through it exclusively —
# and losing it would drop all four from every sync behind a reassuring
# "SKIP (not a skill: no SKILL.md)" line.

SKILLS_HOME_FIXTURE="$SCRATCH_DIR/skills-home"
MONOREPO_FIXTURE="$SCRATCH_DIR/monorepo"
RUN_CWD="$SCRATCH_DIR/run-cwd"

mkdir -p "$SKILLS_HOME_FIXTURE/demo-skill" \
         "$MONOREPO_FIXTURE/demo-skill" \
         "$MONOREPO_FIXTURE/inrepo-skill" \
         "$MONOREPO_FIXTURE/docs" \
         "$MONOREPO_FIXTURE/build" \
         "$RUN_CWD"

cat > "$SKILLS_HOME_FIXTURE/demo-skill/SKILL.md" <<'EOF'
---
name: demo-skill
description: Throwaway fixture skill used only by the sync-hygiene regression harness.
version: 0.1.0
---

# Demo Skill

Fixture content.
EOF

# A plugin-manifest.json is what triggers the auto-build stage — the stage whose
# build directory used to land in the caller's cwd. Without it, the "no build/
# left behind" assertion would pass vacuously.
cat > "$SKILLS_HOME_FIXTURE/demo-skill/plugin-manifest.json" <<'EOF'
{
  "name": "demo-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin used only by the sync-hygiene regression harness.",
  "skills": [
    {
      "name": "demo-skill",
      "source": "."
    }
  ],
  "commands": []
}
EOF

# No skills-home counterpart — this skill's only source is the monorepo itself,
# which is what forces skill_source_dir() down its in-repo branch. The sync loop
# then takes its SKILL_IN_PLACE path (source == destination, nothing to copy).
cat > "$MONOREPO_FIXTURE/inrepo-skill/SKILL.md" <<'EOF'
---
name: inrepo-skill
description: Throwaway fixture skill sourced from the monorepo only — exercises skill_source_dir()'s in-repo branch.
version: 0.1.0
---

# In-repo Skill

Fixture content.
EOF

echo "fixture" > "$MONOREPO_FIXTURE/docs/notes.md"
echo "fixture" > "$MONOREPO_FIXTURE/build/stale-artifact.txt"

STDOUT_LOG="$SCRATCH_DIR/sync.stdout"
STDERR_LOG="$SCRATCH_DIR/sync.stderr"

# --github-user avoids the `gh api user` lookup, so the run is offline-clean.
SYNC_RC=0
(
    cd "$RUN_CWD"
    SKILLS_HOME="$SKILLS_HOME_FIXTURE" \
        "$SYNC_SCRIPT" --github-user harness-fixture-user "$MONOREPO_FIXTURE"
) >"$STDOUT_LOG" 2>"$STDERR_LOG" || SYNC_RC=$?

SYNC_STDOUT="$(cat "$STDOUT_LOG")"
SYNC_STDERR="$(cat "$STDERR_LOG")"

# ============================================================
# Run-level controls
# ============================================================
#
# Without these, a sync that died on line 1 would satisfy every "must not
# appear" assertion below and report a clean sweep.

assert_eq "sync run exits 0 on the fixture" "0" "$SYNC_RC"

assert_contains "control: the plugin auto-build stage actually ran" \
    "AUTO-SYNCED  plugins/demo-plugin/" "$SYNC_STDOUT"

# ============================================================
# Defect 1 — non-skill directories must not enter the sync loop
# ============================================================

# The list printed under "Skills to sync (N):", one bare name per line.
SYNCED_NAMES=$(printf '%s\n' "$SYNC_STDOUT" \
    | awk '/^Skills to sync /{f=1; next} f && /^$/{exit} f{print}' \
    | sed 's/^  - //')

assert_line_present "positive control: a local-source skill is still synced" "demo-skill" "$SYNCED_NAMES"
assert_line_present "positive control: an in-repo-source-only skill is still synced" "inrepo-skill" "$SYNCED_NAMES"
assert_line_absent "docs/ is not in the \"Skills to sync\" list" "docs" "$SYNCED_NAMES"
assert_line_absent "build/ is not in the \"Skills to sync\" list" "build" "$SYNCED_NAMES"

# The filter announces what it dropped rather than dropping it silently — a
# silent filter and a broken filter look identical from the outside.
assert_contains "docs/ is announced as skipped (not silently dropped)" \
    "SKIP (not a skill: no SKILL.md)  docs" "$SYNC_STDERR"
assert_contains "build/ is announced as skipped (not silently dropped)" \
    "SKIP (not a skill: no SKILL.md)  build" "$SYNC_STDERR"

# Both streams: the SKIP notice goes to stderr while the sync loop's ERROR lines
# go to stdout, and a regression could surface on either.
ERROR_LINES=$(printf '%s\n%s\n' "$SYNC_STDOUT" "$SYNC_STDERR" | grep 'ERROR' || true)

assert_not_contains "no ERROR line mentions docs" "docs" "$ERROR_LINES"
assert_not_contains "no ERROR line mentions build" "build" "$ERROR_LINES"

# ============================================================
# Defect 2 — the auto-build stage must not write into the caller's cwd
# ============================================================

BUILD_IN_CWD="ABSENT"
[[ -e "$RUN_CWD/build" ]] && BUILD_IN_CWD="PRESENT"

assert_eq "no build/ left in the directory the sync was run from" "ABSENT" "$BUILD_IN_CWD"

# ============================================================
# Defect 3 — build/ must be gitignored, in both .gitignore sites
# ============================================================

# Site A: the template embedded in sync-monorepo.sh, which is what a freshly
# --init-ed monorepo receives. Fixing only the repo's own file below would leave
# every newly generated monorepo carrying the defect.
GENERATED_GITIGNORE="$(cat "$MONOREPO_FIXTURE/.gitignore" 2>/dev/null || true)"

assert_line_present "generated monorepo .gitignore lists build/" "build/" "$GENERATED_GITIGNORE"

# Site B: this repo's own .gitignore. Asserted through git itself rather than by
# grepping the file, so any equivalent pattern (build, /build/, …) counts.
#
# The trailing slash is load-bearing. A `build/` pattern matches directories
# only, and for a path that does not exist on disk git cannot tell that `build`
# is one — `check-ignore -q build` therefore reports NOT-IGNORED on a fresh CI
# checkout (where the untracked build tree is absent) while passing on a
# developer machine that happens to have one. `build/` states the directory-ness
# explicitly and matches in both cases.
REPO_IGNORES_BUILD="NOT-IGNORED"
if git -C "$REPO_ROOT" check-ignore -q "build/"; then
    REPO_IGNORES_BUILD="IGNORED"
fi

assert_eq "this repo's .gitignore matches build/" "IGNORED" "$REPO_IGNORES_BUILD"

# ============================================================
# Authoring-source parity
# ============================================================
#
# skill-publishing is authored outside the repo and published into plugins/**.
# A fix applied to only one copy is a fix that either nobody receives or the
# next sync silently reverts. The live copy does not exist in CI.

if [[ -f "$LIVE_SYNC_SCRIPT" ]]; then
    assert_eq "live authoring copy is byte-identical to the in-repo copy" "" \
        "$(diff -q "$LIVE_SYNC_SCRIPT" "$REPO_ROOT/plugins/skill-publishing/skills/skill-publishing/scripts/sync-monorepo.sh" >/dev/null 2>&1 || echo DIFFERS)"
else
    echo "SKIP: live authoring copy not present, parity check skipped: $LIVE_SYNC_SCRIPT"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
fi

# The summary reports skips explicitly: without the count, a run where an
# assertion was skipped and a run where it passed both print the same
# "All assertions passed." line, so a check that silently stopped running looks
# exactly like a check that is green.
echo ""
if [[ "$FAIL_COUNT" -eq 0 ]]; then
    if [[ "$SKIPPED_COUNT" -eq 0 ]]; then
        echo "All assertions passed."
    else
        echo "All assertions passed ($SKIPPED_COUNT skipped)."
    fi
    exit 0
else
    echo "$FAIL_COUNT assertion(s) failed."
    exit 1
fi
