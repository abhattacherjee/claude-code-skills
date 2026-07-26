#!/usr/bin/env bash
set -euo pipefail

# test-sync-hygiene.sh — Regression harness for sync-monorepo.sh's monorepo
# hygiene fixes (issue #74). Five defects are locked in here:
#
#   1. discover_skills() treated every top-level monorepo directory as a skill,
#      so non-skill directories (docs/, build/) entered the sync loop and
#      produced spurious "ERROR: no SKILL.md" lines. Both directory-scan sites
#      now pipe through filter_skill_candidates() — the plain scan AND the
#      `--add` branch's `existing=` scan, which is why this harness makes a
#      second sync invocation with --add.
#   2. The plugin auto-build stage built into ./build/<name> in the *caller's*
#      cwd, leaving an untracked build tree behind that the script's own
#      "Next steps: git add -A" banner would then commit. It now builds into a
#      mktemp -d stage removed by an EXIT trap.
#   3. Neither the repo's .gitignore nor the .gitignore template sync-monorepo.sh
#      writes into a freshly --init-ed monorepo listed build/.
#   4. The CHANGELOG stage read its first entry through `echo … | head -1`,
#      which takes EPIPE on a large CHANGELOG (see the fixture note below).
#   5. An empty skill list printed "Skills to sync (1):" and a bare "  - "
#      bullet, because `echo ""` still emits a newline for `wc -l` to count.
#
# Every assertion below was proven to FAIL against a deliberately un-fixed build
# of sync-monorepo.sh before being committed: the guarded change was reverted in
# a scratch copy, SYNC_SCRIPT was pointed at that copy, and the assertion was
# confirmed red. An assertion that passes against unfixed code is worse than no
# assertion.
#
#   6. filter_skill_candidates emitted surviving names through `echo`, which
#      would consume a directory named -n/-e/-E as its own option and drop it
#      with no SKIP line — the one thing an announcing filter must not do.
#
# The whole run is hermetic: a throwaway SKILLS_HOME and four throwaway
# monorepos are built under mktemp, the syncs are invoked from a throwaway cwd,
# and `gh` is shimmed off PATH so nothing reaches the network. The live repo is
# never passed to sync-monorepo.sh.
#
# Usage:
#   ./test-sync-hygiene.sh
#   SYNC_SCRIPT=/tmp/pre-fix/sync-monorepo.sh ./test-sync-hygiene.sh   # point at a different script build
#
# Note when overriding SYNC_SCRIPT: sync-monorepo.sh sources _lib.sh and shells
# out to prepare-plugin.sh from its own directory, and resolves TEMPLATE_DIR as
# ../references relative to that directory. A copy therefore needs the whole
# skill directory around it — scripts/ *and* references/ — not just the
# scripts/ set: a scripts-only copy still runs, but degrades to
# "Warning: monorepo-readme-template.md not found" and silently stops syncing
# CONTRIBUTING.md, the PR template, and the workflow.

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

TODAY="$(date +%Y-%m-%d)"

# Failure diagnostics are only useful if they are readable. The CHANGELOG
# haystacks are ~154 KiB; dumping one verbatim buries the summary line and every
# other result under 900 padding entries.
render_haystack() {
    local haystack="$1"
    if [[ "${#haystack}" -le 2000 ]]; then
        printf '%s' "$haystack"
    else
        printf '<%s-byte haystack, first 2000 bytes>\n%s…' "${#haystack}" "${haystack:0:2000}"
    fi
}

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
        echo "FAIL: $description (expected [$(render_haystack "$haystack")] to contain [$needle])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_not_contains() {
    local description="$1" needle="$2" haystack="$3"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected [$(render_haystack "$haystack")] NOT to contain [$needle])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# Whole-line membership. Substring matching is too loose for the skill list:
# "build" is a substring of nothing here, but "docs" would match a future
# "docs-sync-on-pr" skill and quietly turn a real regression green.
#
# Herestring, not `printf … | grep -q` — the harness would otherwise carry the
# very defect it is testing for. `grep -q` exits at the first match, so on the
# ~154 KiB CHANGELOG haystack the writer takes EPIPE, and under `pipefail` the
# pipeline reports 141 even though grep matched: a present line reported ABSENT.
# A herestring is backed by a temp file, so there is no reader to race.
assert_line_present() {
    local description="$1" needle="$2" haystack="$3"
    if grep -qxF -- "$needle" <<< "$haystack"; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (expected a line [$needle] in [$(render_haystack "$haystack")])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_line_absent() {
    local description="$1" needle="$2" haystack="$3"
    if grep -qxF -- "$needle" <<< "$haystack"; then
        echo "FAIL: $description (found line [$needle] in [$(render_haystack "$haystack")])"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo "PASS: $description"
    fi
}

assert_file_exists() {
    local description="$1" path="$2"
    if [[ -f "$path" ]]; then
        echo "PASS: $description"
    else
        echo "FAIL: $description (no such file: $path)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# The bare name list printed under "Skills to sync (N):", one per line.
synced_names() {
    awk '/^Skills to sync /{f=1; next} f && /^$/{exit} f{print}' <<< "$1" \
        | sed 's/^  - //'
}

# The N the script printed in that header, so it can be compared against the
# list it actually printed underneath.
printed_skill_count() {
    sed -n 's/^Skills to sync (\([0-9]*\)):$/\1/p' <<< "$1"
}

listed_skill_count() {
    if [[ -z "$1" ]]; then
        echo 0
    else
        printf '%s\n' "$1" | wc -l | tr -d ' '
    fi
}

# ============================================================
# gh shim — keeps the run genuinely offline
# ============================================================
#
# Three `gh` calls happen per sync even with --github-user supplied:
# sync-monorepo.sh's `gh repo view <user>/<skill>` probe (once per synced skill)
# and the auto-build child prepare-plugin.sh's `gh api user` lookup, which the
# auto-build stage does not forward --github-user to. All three are
# failure-tolerant, so a non-zero stub reproduces the unauthenticated-CI path
# exactly while guaranteeing no network I/O. GH_SHIM_LOG records each call so
# the "offline" claim can be asserted rather than asserted-in-a-comment.
GH_SHIM_DIR="$SCRATCH_DIR/shim-bin"
GH_SHIM_LOG="$SCRATCH_DIR/gh-invocations.log"
mkdir -p "$GH_SHIM_DIR"
: > "$GH_SHIM_LOG"

cat > "$GH_SHIM_DIR/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_SHIM_LOG"
exit 1
EOF
chmod +x "$GH_SHIM_DIR/gh"

# ============================================================
# Fixtures
# ============================================================
#
#   skills-home/demo-skill/{SKILL.md,plugin-manifest.json}   the authoring source
#   skills-home/added-skill/SKILL.md                         source for the --add run only
#   monorepo/demo-skill/                                     local-source skill (positive control)
#   monorepo/inrepo-skill/SKILL.md                           in-repo-source-only skill (positive control)
#   monorepo/docs/                                           non-skill dir, must be filtered
#   monorepo/build/                                          non-skill dir, must be filtered
#   monorepo-add/                                            same shape; target of the --add run
#   monorepo-empty/docs/                                     only a non-skill dir: empty skill list
#   run-cwd/                                                 every sync is invoked from here
#
# The monorepos deliberately have no .gitignore, so the sync CREATEs one and the
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
#
# monorepo-add/ is a separate tree rather than a second pass over monorepo/ so
# that the --add assertions cannot be satisfied by leftovers from the first run.

SKILLS_HOME_FIXTURE="$SCRATCH_DIR/skills-home"
MONOREPO_FIXTURE="$SCRATCH_DIR/monorepo"
MONOREPO_ADD_FIXTURE="$SCRATCH_DIR/monorepo-add"
MONOREPO_EMPTY_FIXTURE="$SCRATCH_DIR/monorepo-empty"
MONOREPO_DASHN_FIXTURE="$SCRATCH_DIR/monorepo-dashn"
RUN_CWD="$SCRATCH_DIR/run-cwd"

mkdir -p "$SKILLS_HOME_FIXTURE/demo-skill" \
         "$SKILLS_HOME_FIXTURE/added-skill" \
         "$MONOREPO_FIXTURE/demo-skill" \
         "$MONOREPO_FIXTURE/inrepo-skill" \
         "$MONOREPO_FIXTURE/docs" \
         "$MONOREPO_FIXTURE/build" \
         "$MONOREPO_ADD_FIXTURE/demo-skill" \
         "$MONOREPO_ADD_FIXTURE/inrepo-skill" \
         "$MONOREPO_ADD_FIXTURE/docs" \
         "$MONOREPO_ADD_FIXTURE/build" \
         "$MONOREPO_EMPTY_FIXTURE/docs" \
         "$SKILLS_HOME_FIXTURE/-n" \
         "$MONOREPO_DASHN_FIXTURE/-n" \
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

# Only ever named by `--add`; no monorepo directory exists for it beforehand,
# which is the point — the --add branch has to bring it in.
cat > "$SKILLS_HOME_FIXTURE/added-skill/SKILL.md" <<'EOF'
---
name: added-skill
description: Throwaway fixture skill used only by the sync-hygiene harness's --add invocation.
version: 0.1.0
---

# Added Skill

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
INREPO_SKILL_MD='---
name: inrepo-skill
description: Throwaway fixture skill sourced from the monorepo only — exercises skill_source_dir()'"'"'s in-repo branch.
version: 0.1.0
---

# In-repo Skill

Fixture content.'

printf '%s\n' "$INREPO_SKILL_MD" > "$MONOREPO_FIXTURE/inrepo-skill/SKILL.md"
printf '%s\n' "$INREPO_SKILL_MD" > "$MONOREPO_ADD_FIXTURE/inrepo-skill/SKILL.md"

echo "fixture" > "$MONOREPO_FIXTURE/docs/notes.md"
echo "fixture" > "$MONOREPO_FIXTURE/build/stale-artifact.txt"
echo "fixture" > "$MONOREPO_ADD_FIXTURE/docs/notes.md"
echo "fixture" > "$MONOREPO_ADD_FIXTURE/build/stale-artifact.txt"
echo "fixture" > "$MONOREPO_EMPTY_FIXTURE/docs/notes.md"

# A skill directory literally named "-n". filter_skill_candidates emits each
# surviving name on stdout, and bash's `echo` would consume this one as its
# own suppress-newline option: the name disappears from the list with no SKIP
# line either, which is the one failure mode this function exists to prevent.
# Absurd as a real skill name, cheap as a guard on a filter whose entire job is
# to not drop things silently. Isolated in its own monorepo so it cannot perturb
# the skill counts every other assertion depends on.
cat > "$SKILLS_HOME_FIXTURE/-n/SKILL.md" <<'EOF'
---
name: dash-n
description: Throwaway fixture skill in a directory named -n, guarding filter_skill_candidates against echo option-eating.
version: 0.1.0
---

# Dash-N Skill

Fixture content.
EOF

# A deliberately oversized CHANGELOG: 157,576 bytes of extracted entry text
# (measured; ~154 KiB), well past the 64 KiB pipe buffer. Two separate defects
# key off its shape.
#
# (a) Broken pipe. The sync reads this file to decide whether today's entry
#     already exists; a `cmd | head -1` over that text makes the writer take
#     EPIPE, which a registered EXIT trap surfaces as a visible
#     "write error: Broken pipe" on stderr instead of a silent SIGPIPE death.
#     This is a write/reader race, not a threshold: measured 0/50 reproductions
#     below 64 KiB, ~53% at 84 KiB, and 10/10 at this fixture's size. A small
#     fixture cannot catch the class at all — the pipe buffer swallows the whole
#     payload and nothing ever blocks.
#
# (b) FIRST_ENTRY semantics. The top entry is a non-today release, and a
#     today-dated "— Monorepo sync" entry is buried further down. A correct
#     FIRST_ENTRY (first line only) does not match today's sync marker, so the
#     sync prepends and keeps everything. A FIRST_ENTRY that carries the whole
#     document — the plausible "just drop the pipe" simplification
#     FIRST_ENTRY="$ALL_ENTRIES" — matches the buried marker, takes the replace
#     branch, and its `count>=2` filter silently drops the top entry.
{
    echo "# Changelog"
    echo ""
    echo "## [9.9.9] - 2026-01-01"
    echo ""
    echo "### Added"
    echo ""
    echo "- Top entry. Not today-dated and not a Monorepo sync entry, so a"
    echo "  correct run must preserve it verbatim."
    echo ""
    for ((_i = 1; _i <= 900; _i++)); do
        echo "## [0.0.$_i] - 2026-01-01"
        echo ""
        echo "### Fixed"
        echo ""
        echo "- Padding entry $_i, present only to push the extracted entry text"
        echo "  past the 64 KiB pipe buffer. See the broken-pipe assertions below."
        echo ""
        if [[ "$_i" -eq 450 ]]; then
            echo "## [$TODAY] — Monorepo sync"
            echo ""
            echo "Stale sync entry, deliberately NOT the top entry. Only a"
            echo "FIRST_ENTRY that spans the whole document can see this."
            echo ""
        fi
    done
} > "$MONOREPO_FIXTURE/CHANGELOG.md"

# ============================================================
# Sync invocations
# ============================================================
#
# Three runs, all from the same throwaway cwd:
#   1. plain sync of monorepo/         — the main hygiene surface
#   2. --add added-skill on monorepo-add/ — the SECOND filter site (line ~191)
#   3. plain sync of monorepo-empty/   — the empty-skill-list branch
#
# Run 2 exists because sync-monorepo.sh filters at two independent sites and a
# single no-`--add` invocation executes only one of them. Reverting the filter
# on the --add branch alone reproduces #74 verbatim while every run-1 assertion
# stays green.

run_sync() {
    local monorepo="$1" stdout_log="$2" stderr_log="$3"
    shift 3
    local rc=0
    (
        cd "$RUN_CWD"
        PATH="$GH_SHIM_DIR:$PATH" \
        SKILLS_HOME="$SKILLS_HOME_FIXTURE" \
            "$SYNC_SCRIPT" --github-user harness-fixture-user "$@" "$monorepo"
    ) >"$stdout_log" 2>"$stderr_log" || rc=$?
    return "$rc"
}

# Snapshot the directory mktemp -d actually writes into, so the auto-build
# temp-stage cleanup can be asserted behaviourally. The parent is probed at
# runtime rather than assumed to be ${TMPDIR:-/tmp}: BSD mktemp on macOS ignores
# TMPDIR (verified — it resolves _CS_DARWIN_USER_TEMP_DIR instead) while GNU
# mktemp honours it, so a TMPDIR-scoped assertion would be live in CI and a
# silent no-op on a developer machine.
_MKTEMP_PROBE="$(mktemp -d)"
MKTEMP_PARENT="$(dirname "$_MKTEMP_PROBE")"
rmdir "$_MKTEMP_PROBE"

snapshot_mktemp_parent() {
    find "$MKTEMP_PARENT" -maxdepth 1 -mindepth 1 2>/dev/null | sort
}

TMP_BEFORE="$SCRATCH_DIR/mktemp-parent.before"
TMP_AFTER="$SCRATCH_DIR/mktemp-parent.after"
snapshot_mktemp_parent > "$TMP_BEFORE"

STDOUT_LOG="$SCRATCH_DIR/sync.stdout"
STDERR_LOG="$SCRATCH_DIR/sync.stderr"
SYNC_RC=0
run_sync "$MONOREPO_FIXTURE" "$STDOUT_LOG" "$STDERR_LOG" || SYNC_RC=$?
SYNC_STDOUT="$(cat "$STDOUT_LOG")"
SYNC_STDERR="$(cat "$STDERR_LOG")"

ADD_STDOUT_LOG="$SCRATCH_DIR/add.stdout"
ADD_STDERR_LOG="$SCRATCH_DIR/add.stderr"
ADD_RC=0
run_sync "$MONOREPO_ADD_FIXTURE" "$ADD_STDOUT_LOG" "$ADD_STDERR_LOG" --add added-skill || ADD_RC=$?
ADD_STDOUT="$(cat "$ADD_STDOUT_LOG")"

EMPTY_STDOUT_LOG="$SCRATCH_DIR/empty.stdout"
EMPTY_STDERR_LOG="$SCRATCH_DIR/empty.stderr"
EMPTY_RC=0
run_sync "$MONOREPO_EMPTY_FIXTURE" "$EMPTY_STDOUT_LOG" "$EMPTY_STDERR_LOG" || EMPTY_RC=$?
EMPTY_STDOUT="$(cat "$EMPTY_STDOUT_LOG")"

DASHN_STDOUT_LOG="$SCRATCH_DIR/dashn.stdout"
DASHN_STDERR_LOG="$SCRATCH_DIR/dashn.stderr"
DASHN_RC=0
run_sync "$MONOREPO_DASHN_FIXTURE" "$DASHN_STDOUT_LOG" "$DASHN_STDERR_LOG" || DASHN_RC=$?
DASHN_STDOUT="$(cat "$DASHN_STDOUT_LOG")"

snapshot_mktemp_parent > "$TMP_AFTER"

# ============================================================
# Run-level controls
# ============================================================
#
# Without these, a sync that died on line 1 would satisfy every "must not
# appear" assertion below and report a clean sweep.

assert_eq "sync run exits 0 on the fixture" "0" "$SYNC_RC"
assert_eq "--add run exits 0 on the fixture" "0" "$ADD_RC"
assert_eq "empty-monorepo run exits 0 on the fixture" "0" "$EMPTY_RC"
assert_eq "dash-named-skill run exits 0 on the fixture" "0" "$DASHN_RC"

assert_contains "control: the plugin auto-build stage actually ran" \
    "AUTO-SYNCED  plugins/demo-plugin/" "$SYNC_STDOUT"

# Proves the offline claim in this file's header is live rather than asserted in
# prose: if the shim ever falls off PATH, these calls go to the real gh and this
# control goes red. Should sync-monorepo.sh legitimately stop shelling out to gh
# entirely, this is the assertion that will say so.
GH_SHIM_CALLS=$(wc -l < "$GH_SHIM_LOG" | tr -d ' ')
if [[ "$GH_SHIM_CALLS" -gt 0 ]]; then
    echo "PASS: control: gh is shimmed off PATH for every sync ($GH_SHIM_CALLS call(s) intercepted)"
else
    echo "FAIL: control: gh is shimmed off PATH for every sync (shim never invoked — either gh is no longer called, or the shim is not on PATH and the run is reaching the network)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# A clean run writes nothing to stderr but its own SKIP notices. Broken-pipe
# noise is worth its own assertion rather than a blanket "stderr is empty"
# check: it appears only under an EXIT trap, only on a large payload, and it
# is invisible in the exit status — the run still succeeds. This branch exists to
# remove spurious error output, so emitting a line containing "error" on every
# run would defeat its own purpose.
#
# The control immediately below is what keeps these two honest. They detect the
# defect only because the CHANGELOG stage runs at all; a fixture-path change that
# stopped the sync before it read CHANGELOG.md would turn both into silent no-ops
# that still print PASS.
assert_not_contains "no 'Broken pipe' on stderr" "Broken pipe" "$SYNC_STDERR"
assert_not_contains "no 'write error' on stderr" "write error" "$SYNC_STDERR"

assert_contains "control: the CHANGELOG stage actually ran (broken-pipe assertions are not vacuous)" \
    "SYNCED  CHANGELOG.md" "$SYNC_STDOUT"

# ============================================================
# Defect 1 — non-skill directories must not enter the sync loop
# ============================================================

SYNCED_NAMES="$(synced_names "$SYNC_STDOUT")"

assert_line_present "positive control: a local-source skill is still synced" "demo-skill" "$SYNCED_NAMES"
assert_line_present "positive control: an in-repo-source-only skill is still synced" "inrepo-skill" "$SYNCED_NAMES"

# Appearing in a printed list is not the same as being written. Without these,
# a regression that printed a correct list and then synced nothing would pass
# both positive controls above.
assert_file_exists "positive control: the local-source skill was written to disk" \
    "$MONOREPO_FIXTURE/demo-skill/SKILL.md"
assert_file_exists "positive control: the local-source skill's README was generated" \
    "$MONOREPO_FIXTURE/demo-skill/README.md"
assert_file_exists "positive control: the in-repo-source-only skill was processed (README generated)" \
    "$MONOREPO_FIXTURE/inrepo-skill/README.md"

assert_line_absent "docs/ is not in the \"Skills to sync\" list" "docs" "$SYNCED_NAMES"
assert_line_absent "build/ is not in the \"Skills to sync\" list" "build" "$SYNCED_NAMES"

# The header's count and the list under it are produced from the same variable
# but by different code paths, and only the list is checked above: a regression
# printing "Skills to sync (4):" over a correct 2-line list would otherwise pass.
assert_eq "the printed skill count matches the printed list" \
    "$(listed_skill_count "$SYNCED_NAMES")" "$(printed_skill_count "$SYNC_STDOUT")"

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
# Defect 1b — the --add discovery site filters too
# ============================================================
#
# discover_skills() returns early for --add, through its own `existing=` scan.
# Everything above exercises the other site only.

ADD_SYNCED_NAMES="$(synced_names "$ADD_STDOUT")"

# Load-bearing pair: without them an --add run that died before printing its list
# would satisfy the two absence assertions trivially.
assert_line_present "--add: the added skill is synced" "added-skill" "$ADD_SYNCED_NAMES"
assert_line_present "--add: a pre-existing skill is retained" "demo-skill" "$ADD_SYNCED_NAMES"
assert_file_exists "--add: the added skill was written to disk" \
    "$MONOREPO_ADD_FIXTURE/added-skill/SKILL.md"

assert_line_absent "--add: docs/ is not in the \"Skills to sync\" list" "docs" "$ADD_SYNCED_NAMES"
assert_line_absent "--add: build/ is not in the \"Skills to sync\" list" "build" "$ADD_SYNCED_NAMES"

ADD_ERROR_LINES=$(printf '%s\n%s\n' "$ADD_STDOUT" "$(cat "$ADD_STDERR_LOG")" | grep 'ERROR' || true)
assert_not_contains "--add: no ERROR line mentions docs" "docs" "$ADD_ERROR_LINES"
assert_not_contains "--add: no ERROR line mentions build" "build" "$ADD_ERROR_LINES"

# ============================================================
# Defect 2 — the auto-build stage must not write into the caller's cwd,
#            and must not leave its temp stage behind either
# ============================================================

BUILD_IN_CWD="ABSENT"
[[ -e "$RUN_CWD/build" ]] && BUILD_IN_CWD="PRESENT"

assert_eq "no build/ left in the directory the sync was run from" "ABSENT" "$BUILD_IN_CWD"

# Moving the build out of the caller's cwd only relocates the mess unless the
# EXIT trap fires: without it every sync leaks a full plugin build tree into the
# temp directory. Leaks are attributed by content (a surviving stage holds
# demo-plugin/) rather than by name, so an unrelated process creating a temp
# directory mid-run cannot turn this red.
LEAKED_BUILD_STAGES=""
while IFS= read -r _entry; do
    [[ -z "$_entry" ]] && continue
    if [[ -d "$_entry/demo-plugin" ]]; then
        LEAKED_BUILD_STAGES="${LEAKED_BUILD_STAGES}${_entry} "
    fi
done < <(comm -13 "$TMP_BEFORE" "$TMP_AFTER")

assert_eq "no auto-build temp stage left behind under $MKTEMP_PARENT" \
    "" "${LEAKED_BUILD_STAGES% }"

# ============================================================
# Defect 3 — build/ must be gitignored, in both .gitignore sites
# ============================================================

# Site A: the template embedded in sync-monorepo.sh, which is what a freshly
# --init-ed monorepo receives. Fixing only the repo's own file below would leave
# every newly generated monorepo carrying the defect.
#
# The leading slash is load-bearing in the other direction from the trailing one:
# an unanchored `build/` matches at every depth, so a plugin that ever ships a
# build/ subdirectory would be silently excluded from the `git add -A` in the
# script's own Next-steps banner.
GENERATED_GITIGNORE="$(cat "$MONOREPO_FIXTURE/.gitignore" 2>/dev/null || true)"

assert_line_present "generated monorepo .gitignore anchors build/ to the root" "/build/" "$GENERATED_GITIGNORE"

# Site B: this repo's own .gitignore. Asserted through git itself rather than by
# grepping the file, so any equivalent pattern (/build/, build, …) counts.
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
# Defect 4 — the CHANGELOG's top entry must survive a sync
# ============================================================
#
# The broken-pipe assertions above cover the *symptom* of the old
# `echo … | head -1`. This covers what the expression is for: FIRST_ENTRY must
# be the first entry, not the whole document. The fixture's top entry is
# [9.9.9]; a today-dated sync marker sits ~450 entries below it.

SYNCED_CHANGELOG="$(cat "$MONOREPO_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"

assert_line_present "the CHANGELOG's pre-existing top entry survives the sync" \
    "## [9.9.9] - 2026-01-01" "$SYNCED_CHANGELOG"

# Control for the assertion above, and it has to be the *top* entry rather than
# merely "today's entry appears somewhere": the fixture seeds a stale today-dated
# sync entry 450 entries down, so a `grep`-anywhere form would be satisfied by
# the fixture itself and stay green even if the sync never wrote the file at all.
CHANGELOG_TOP_ENTRY="$(grep -m1 '^## \[' "$MONOREPO_FIXTURE/CHANGELOG.md" || true)"

assert_eq "the sync wrote its own entry at the top of the CHANGELOG" \
    "## [$TODAY] — Monorepo sync" "$CHANGELOG_TOP_ENTRY"

# ============================================================
# Defect 5 — an empty skill list must report zero, not one phantom
# ============================================================
#
# Newly reachable: before discovery filtered non-skill directories, docs/ kept
# the list non-empty. A monorepo holding only those now yields nothing.

assert_eq "a monorepo with no skills reports a count of 0" "0" "$(printed_skill_count "$EMPTY_STDOUT")"

# Counted on the raw block, before the "  - " prefix is stripped. Counting
# stripped names instead would be vacuous here: the phantom bullet strips down to
# an empty name, so the defect this exists to catch would still report zero.
EMPTY_LIST_LINES=$(awk '/^Skills to sync /{f=1; next} f && /^$/{exit} f{print}' <<< "$EMPTY_STDOUT" | wc -l | tr -d ' ')

assert_eq "a monorepo with no skills prints no name lines at all" "0" "$EMPTY_LIST_LINES"

PHANTOM_BULLETS=$(printf '%s\n' "$EMPTY_STDOUT" | grep -c '^  - $' || true)
assert_eq "a monorepo with no skills prints no bare \"  - \" bullet" "0" "$PHANTOM_BULLETS"

# ============================================================
# A skill name that looks like an option must survive the filter
# ============================================================

DASHN_SYNCED_NAMES="$(synced_names "$DASHN_STDOUT")"

assert_line_present "a skill directory named -n survives filter_skill_candidates" \
    "-n" "$DASHN_SYNCED_NAMES"
assert_file_exists "the -n skill was written to disk" \
    "$MONOREPO_DASHN_FIXTURE/-n/SKILL.md"

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
