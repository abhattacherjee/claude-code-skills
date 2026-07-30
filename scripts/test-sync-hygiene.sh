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
#   6. All three name-emitting sites in discovery used `echo`, which consumes a
#      leading -n/-e/-E as its own option. filter_skill_candidates dropped such a
#      directory with no SKIP line — the one thing an announcing filter must not
#      do — while `--skills -n` synced nothing and still exited 0, and `--add -n`
#      into a monorepo with no skills yet emitted nothing, so the trailing
#      `grep -v '^$'` exited 1 and killed the run with an empty stderr. All three
#      now emit through `printf`, and each has its own sync run below.
#   7. `--add -n`'s fix above cured the cause (echo eating the argument) but not
#      the shape: any ADD_SKILL that reduces to nothing after comma-splitting
#      (the literal argument `,` is the simplest case) still leaves the same
#      trailing `grep -v '^$'` with nothing to match, so it still exits 1 and
#      still kills the run under `set -e` with an empty stderr. discover_skills()
#      now detects an empty combined result itself and exits with a message
#      naming the offending argument, rather than letting grep's exit code
#      propagate unexplained. `--skills ,` was checked for the same shape and
#      does not have it — with no `--add`, an empty result there is just the
#      ordinary "0 skills to sync" case (defect 5) and exits 0 by design.
#
#   8. The plugin auto-build ran prepare-plugin.sh under `>/dev/null 2>&1` and,
#      on failure, printed only "Warning: prepare-plugin.sh failed for <manifest>".
#      That was survivable while the build stage was `./build/<name>/` in the
#      caller's cwd — the partial tree stayed behind to inspect and re-run by
#      hand. Defect 2's fix moved the stage into a mktemp -d that the EXIT trap
#      deletes on every path including this one, so the child's own diagnosis
#      (e.g. "ERROR: skill source not found: …") became the only evidence that
#      ever existed, and it was the thing being discarded. It is now captured to
#      a log in the stage root — not inside the build dir, which prepare-plugin.sh
#      `rm -rf`s on entry — and echoed to stderr on failure. The run's exit status
#      on that path was a separate defect, tracked as #73 and closed below.
#   9. The .gitignore template fix (defect 3) reaches freshly --init-ed monorepos
#      only. write_file does not overwrite, so an already-published monorepo gets
#      "SKIP    .gitignore (already exists)" — indistinguishable from "already
#      correct" — and no signal that it lacks the rule. A non-fatal NOTE now says
#      so, naming the pattern to add.
#
#  10. Issue #73, both halves. A legacy manifest declares its skills as bare
#      strings ("skills": ["name"]) rather than objects, and every one of
#      prepare-plugin.sh's eight `.skills[…]` reads then died with
#      `jq: error … Cannot index string with "name"`. The manifest is now
#      normalised once into a temp copy that every read is pointed at (see
#      normalize_manifest() in _lib.sh), with MANIFEST_DIR deliberately left
#      pointing at the ORIGINAL manifest's directory — relative sources resolve
#      against it, and every manifest in use has one. sync-monorepo.sh read the
#      same shape at two sites under `2>/dev/null`, so on a legacy manifest its
#      reversion guard saw no skills and its drift check saw no first skill and
#      never rebuilt the plugin at all; both now go through
#      manifest_skill_names(). And the failure itself is now fatal: a sync whose
#      plugin auto-build fails exits 1 rather than warning and going on to
#      regenerate a catalogue describing a plugin it could not build.
#
# The whole run is hermetic: four throwaway SKILLS_HOMEs, a fixture directory
# that is deliberately never a SKILLS_HOME, twelve throwaway monorepos, the syncs
# invoked from a throwaway cwd, and `gh` shimmed off PATH so nothing reaches the
# network. The live repo is never passed to sync-monorepo.sh or prepare-plugin.sh.
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
# The whole skill directory, not just the script: a change to this skill lands in
# SKILL.md (metadata.version, which drives the reversion guard), CHANGELOG.md and
# scripts/ alike, and a parity check narrower than the publish relationship it
# describes lets the rest drift unnoticed.
LIVE_SKILL_DIR="${LIVE_SKILL_DIR:-$HOME/.claude/skills/skill-publishing}"
IN_REPO_SKILL_DIR="$REPO_ROOT/plugins/skill-publishing/skills/skill-publishing"

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

# Issue #73's manifest-shape assertions drive prepare-plugin.sh directly rather
# than through a sync: the shapes under test are its input, and a sync run would
# only reach them via the auto-build stage, which reports a build failure with
# one line whatever the cause. Taken from the same directory as SYNC_SCRIPT, not
# from the repo, so a `SYNC_SCRIPT=/tmp/pre-fix/…` mutation run exercises the
# matching pre-fix child — the two scripts are edited together and testing a
# reverted parent against the current child would prove nothing.
PREPARE_SCRIPT="$(dirname "$SYNC_SCRIPT")/prepare-plugin.sh"
if [[ ! -x "$PREPARE_SCRIPT" ]]; then
    echo "FATAL: no executable prepare-plugin.sh beside SYNC_SCRIPT: $PREPARE_SCRIPT" >&2
    exit 1
fi

# Issue #78's assertions drive validate-pre-sync.sh directly — it is never
# invoked by sync-monorepo.sh, so a sync run cannot reach it. Taken from beside
# SYNC_SCRIPT for the same reason as PREPARE_SCRIPT above: it and _lib.sh (which
# it sources for skill_source_dir()) are edited together with the parent.
PRESYNC_SCRIPT="$(dirname "$SYNC_SCRIPT")/validate-pre-sync.sh"
if [[ ! -x "$PRESYNC_SCRIPT" ]]; then
    echo "FATAL: no executable validate-pre-sync.sh beside SYNC_SCRIPT: $PRESYNC_SCRIPT" >&2
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
# A herestring is fully written before the reader starts, so there is no reader
# to race: bash materialises small content into a pipe (5.1+) and larger content
# into a temp file, but it only takes the pipe when the content fits in the pipe
# buffer, so the write completes either way before grep is exec'd.
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
# `gh` calls happen per sync even with --github-user supplied: sync-monorepo.sh's
# `gh repo view <user>/<skill>` probe, once per synced skill (two for the main
# fixture: demo-skill and inrepo-skill). Historically there was a third — the
# auto-build child prepare-plugin.sh's own `gh api user` lookup — because the
# auto-build stage did not forward --github-user to it (issue #79). Now that it
# does, GITHUB_USER is always non-empty at that call site (resolve_github_user
# guarantees it before the auto-build stage runs at all), so the child never
# reaches its own gh api user fallback and the count drops to one call per
# synced skill. Both are failure-tolerant, so a non-zero stub reproduces the
# unauthenticated-CI path exactly while guaranteeing no network I/O. GH_SHIM_LOG
# records each call so the "offline" claim can be asserted rather than
# asserted-in-a-comment. The Issue #79 section below asserts the forwarding
# itself, through generated README content rather than the shim log — a shimmed
# `gh api user` always fails regardless of whether it was reached, so the log
# can prove the call happened but not what prepare-plugin.sh did as a result.
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
#   monorepo-dashn/-n/                                       skill dir named -n, reached by discovery
#   monorepo-skillsn/                                        empty; -n reaches it via --skills -n
#   monorepo-addn/                                           empty; -n reaches it via --add -n
#   monorepo-addcomma/                                       empty; --add , must fail loudly, not silently abort
#   skills-home-buildfail/broken-plugin/plugin-manifest.json  manifest naming a source that does not exist
#   monorepo-buildfail/                                      empty; target of the failing-auto-build run
#   monorepo-gitignore/.gitignore                            pre-existing .gitignore with no /build/ line
#   run-cwd/                                                 every sync is invoked from here
#
# Every monorepo but monorepo-gitignore/ deliberately has no .gitignore, so the
# sync CREATEs one and the embedded template is what gets asserted. That is also
# why monorepo-gitignore/ has to be a tree of its own: write_file does not
# overwrite, so the "already exists" branch — the one an already-published
# monorepo always takes — is only reachable with a file already in place.
#
# skills-home-buildfail/ is a second SKILLS_HOME rather than one more manifest in
# the shared one because the auto-build stage scans $SKILLS_HOME/*/ on every run:
# a deliberately broken manifest living there would print its failure into all
# eight other runs that share skills-home/ and leave every other assertion
# reading around it. (Runs 10-11 use their own third SKILLS_HOME, skills-home-hooks/,
# for the identical reason — see its own fixture comment below.)
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
MONOREPO_SKILLSN_FIXTURE="$SCRATCH_DIR/monorepo-skillsn"
MONOREPO_ADDN_FIXTURE="$SCRATCH_DIR/monorepo-addn"
MONOREPO_ADDCOMMA_FIXTURE="$SCRATCH_DIR/monorepo-addcomma"
SKILLS_HOME_BUILDFAIL_FIXTURE="$SCRATCH_DIR/skills-home-buildfail"
MONOREPO_BUILDFAIL_FIXTURE="$SCRATCH_DIR/monorepo-buildfail"
MONOREPO_GITIGNORE_FIXTURE="$SCRATCH_DIR/monorepo-gitignore"
RUN_CWD="$SCRATCH_DIR/run-cwd"

# Issue #77 (hooks.source) and #79 (--github-user forwarding) fixtures. A
# separate SKILLS_HOME/monorepo pair, for the same reason SKILLS_HOME_BUILDFAIL_FIXTURE
# is separate: the auto-build stage scans $SKILLS_HOME/*/plugin-manifest.json on
# every invocation, so these four manifests would otherwise print their own
# AUTO-SYNCED / ERROR lines into all eight runs above that share skills-home/
# (runs 1-7 and 9) and perturb their counts.
SKILLS_HOME_HOOKS_FIXTURE="$SCRATCH_DIR/skills-home-hooks"
MONOREPO_HOOKS_FIXTURE="$SCRATCH_DIR/monorepo-hooks"

# Issue #73 (legacy `"skills": ["name"]` manifests). A fourth SKILLS_HOME, for
# the same reason as the two above — its single manifest would otherwise print
# into every run that shares a home — holding one legacy-shape plugin driven
# through three sync runs:
#   monorepo-legacy/     runs 12 and 13, first build then forced rebuild
#   monorepo-legacyref/  run 14, the same manifest with its skill refused
SKILLS_HOME_LEGACY_FIXTURE="$SCRATCH_DIR/skills-home-legacy"
MONOREPO_LEGACY_FIXTURE="$SCRATCH_DIR/monorepo-legacy"
MONOREPO_LEGACYREF_FIXTURE="$SCRATCH_DIR/monorepo-legacyref"

# Manifests driven straight into prepare-plugin.sh. Deliberately NOT a
# SKILLS_HOME: two of them are meant to fail the build, and the auto-build stage
# scans every manifest under $SKILLS_HOME on every sync, so as a home they would
# now abort each of the fourteen sync runs above (the failure is fatal as of
# #73) instead of being read as the isolated inputs they are.
PREPARE_FIXTURE_DIR="$SCRATCH_DIR/prepare-fixtures"
PREPARE_OUT_DIR="$SCRATCH_DIR/prepare-out"

# TMPDIR for those invocations, so prepare-plugin.sh's normalised-manifest temp
# file lands somewhere this harness owns and its cleanup can be asserted rather
# than assumed. Its `mktemp "${TMPDIR:-/tmp}/plugin-manifest.XXXXXX"` honours
# TMPDIR by way of the explicit template; a bare `mktemp` on macOS would not
# (BSD mktemp resolves _CS_DARWIN_USER_TEMP_DIR instead — the same divergence
# the MKTEMP_PARENT probe below exists for).
PREPARE_TMPDIR="$SCRATCH_DIR/prepare-tmpdir"

# A TMPDIR that cannot hold a file, used to prove the location above is actually
# honoured. A regular file rather than a chmod 555 directory: mode bits do not
# constrain root, and some CI containers run as root, where a permissions-based
# injection would silently stop failing and the assertion would go red for the
# wrong reason. ENOTDIR constrains everyone.
PREPARE_BAD_TMPDIR="$SCRATCH_DIR/prepare-tmpdir-not-a-directory"

# The source path the broken manifest names. Absolute, so resolve_source_path
# returns it untouched and the error text is fixed rather than carrying this
# run's scratch path — the assertion below can then match the whole line.
BROKEN_SKILL_SOURCE="/nonexistent/sync-hygiene-harness-no-such-skill-source"

# The auto-built plugin's name, carrying this run's PID. The temp-stage leak
# assertion below identifies a leaked stage by looking for this name inside it,
# so the name has to be unique to the run: with a fixed "demo-plugin", a second
# concurrent copy of this harness has an in-flight stage that looks exactly like
# a leak to the first, and the first fails. That is measured, not hypothetical —
# 10 sequential solo runs never failed, while 3 of 3 concurrent pairs did.
DEMO_PLUGIN_NAME="demo-plugin-$$"

# Issue #78 fixtures — validate-pre-sync.sh must resolve every skill through
# skill_source_dir() rather than hardcoding $SKILLS_HOME/<name>, so an
# in-repo-source-only skill (no local copy at all) is examined instead of
# silently skipped. Two monorepos, not one: the core (negative) fixture and the
# positive control need the SAME skill with DIFFERENT CHANGELOG content, and a
# single monorepo can't hold both without one run's fixture mutation
# contaminating the other.
#
#   presync-skills-home/presync-local-skill/            local-source skill (regression control)
#   presync-monorepo/presync-local-skill/                empty — source resolves via SKILLS_HOME
#   presync-monorepo/presync-inrepo-skill/                in-repo-source-only; CHANGELOG MISMATCHED (core, negative)
#   presync-monorepo/docs/, build/                        non-skill dirs, must enter neither count
#   presync-monorepo-pass/presync-local-skill/            same shape as above
#   presync-monorepo-pass/presync-inrepo-skill/           same skill; CHANGELOG MATCHES (positive control)
#   presync-monorepo-pass/docs/, build/                   same shape as above
#
# presync-local-skill's monorepo-side CHANGELOG.md is deliberately WRONG
# (STALE-DO-NOT-READ, matching no real version) in both monorepos: skill_source_dir()
# is local-first, so a correct implementation never reads it. If a regression
# read the monorepo copy for a local-source skill instead, this fixture turns
# that PASS into a FAIL rather than agreeing with the regression by accident.
PRESYNC_SKILLS_HOME_FIXTURE="$SCRATCH_DIR/presync-skills-home"
PRESYNC_MONOREPO_FIXTURE="$SCRATCH_DIR/presync-monorepo"
PRESYNC_MONOREPO_PASS_FIXTURE="$SCRATCH_DIR/presync-monorepo-pass"

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
         "$MONOREPO_SKILLSN_FIXTURE" \
         "$MONOREPO_ADDN_FIXTURE" \
         "$MONOREPO_ADDCOMMA_FIXTURE" \
         "$SKILLS_HOME_BUILDFAIL_FIXTURE/broken-plugin" \
         "$MONOREPO_BUILDFAIL_FIXTURE" \
         "$MONOREPO_GITIGNORE_FIXTURE" \
         "$SKILLS_HOME_HOOKS_FIXTURE/hooks-none-plugin" \
         "$SKILLS_HOME_HOOKS_FIXTURE/hooks-null-plugin" \
         "$SKILLS_HOME_HOOKS_FIXTURE/hooks-empty-plugin" \
         "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/hooks-src" \
         "$MONOREPO_HOOKS_FIXTURE" \
         "$SKILLS_HOME_LEGACY_FIXTURE/legacy-sync-plugin" \
         "$MONOREPO_LEGACY_FIXTURE" \
         "$MONOREPO_LEGACYREF_FIXTURE/legacy-sync-plugin" \
         "$PREPARE_FIXTURE_DIR/legacy-plugin" \
         "$PREPARE_FIXTURE_DIR/relsource-plugin/nested-src" \
         "$PREPARE_FIXTURE_DIR/barecmd-plugin" \
         "$PREPARE_FIXTURE_DIR/bareagent-plugin" \
         "$PREPARE_FIXTURE_DIR/objentry-plugin" \
         "$PREPARE_OUT_DIR" \
         "$PREPARE_TMPDIR" \
         "$PRESYNC_SKILLS_HOME_FIXTURE/presync-local-skill" \
         "$PRESYNC_MONOREPO_FIXTURE/presync-local-skill" \
         "$PRESYNC_MONOREPO_FIXTURE/presync-inrepo-skill" \
         "$PRESYNC_MONOREPO_FIXTURE/docs" \
         "$PRESYNC_MONOREPO_FIXTURE/build" \
         "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-local-skill" \
         "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-inrepo-skill" \
         "$PRESYNC_MONOREPO_PASS_FIXTURE/docs" \
         "$PRESYNC_MONOREPO_PASS_FIXTURE/build" \
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
cat > "$SKILLS_HOME_FIXTURE/demo-skill/plugin-manifest.json" <<EOF
{
  "name": "$DEMO_PLUGIN_NAME",
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

# ------------------------------------------------------------------
# Issue #78 fixtures — validate-pre-sync.sh
# ------------------------------------------------------------------

cat > "$PRESYNC_SKILLS_HOME_FIXTURE/presync-local-skill/SKILL.md" <<'EOF'
---
name: presync-local-skill
description: Throwaway fixture — local-source skill, regression control for validate-pre-sync.sh.
version: 1.0.0
---

# Presync Local Skill

Fixture content.
EOF

cat > "$PRESYNC_SKILLS_HOME_FIXTURE/presync-local-skill/CHANGELOG.md" <<'EOF'
## [1.0.0] - 2026-01-01

- Initial fixture version.
EOF

# No skills-home counterpart — this skill's only source is the monorepo, which
# is what forces skill_source_dir() down its in-repo branch. Same SKILL.md
# (version 2.0.0) in both monorepos; only the CHANGELOG differs below.
PRESYNC_INREPO_SKILL_MD='---
name: presync-inrepo-skill
description: Throwaway fixture — in-repo-source-only skill exercising issue #78.
version: 2.0.0
---

# Presync In-repo Skill

Fixture content.'

printf '%s\n' "$PRESYNC_INREPO_SKILL_MD" > "$PRESYNC_MONOREPO_FIXTURE/presync-inrepo-skill/SKILL.md"
printf '%s\n' "$PRESYNC_INREPO_SKILL_MD" > "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-inrepo-skill/SKILL.md"

# Core (negative) fixture: CHANGELOG exists but has no entry matching v2.0.0 —
# a version bump with no matching CHANGELOG entry, the exact failure #78 must
# catch instead of silently skipping the skill.
cat > "$PRESYNC_MONOREPO_FIXTURE/presync-inrepo-skill/CHANGELOG.md" <<'EOF'
## [1.0.0] - 2026-01-01

- Initial fixture version.
EOF

# Positive control: same skill, CHANGELOG updated to match v2.0.0. Without this,
# a rework that fails every skill unconditionally would still pass the core
# assertion above.
cat > "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-inrepo-skill/CHANGELOG.md" <<'EOF'
## [2.0.0] - 2026-01-02

- Bumped version with a matching CHANGELOG entry.

## [1.0.0] - 2026-01-01

- Initial fixture version.
EOF

# Deliberately wrong — see the fixture-block comment above. A regression that
# resolved a local-source skill's CHANGELOG through the monorepo instead of
# SKILLS_HOME would read this and flip presync-local-skill from PASS to FAIL.
echo "STALE-DO-NOT-READ — matches no real version" > "$PRESYNC_MONOREPO_FIXTURE/presync-local-skill/CHANGELOG.md"
echo "STALE-DO-NOT-READ — matches no real version" > "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-local-skill/CHANGELOG.md"

echo "fixture" > "$PRESYNC_MONOREPO_FIXTURE/docs/notes.md"
echo "fixture" > "$PRESYNC_MONOREPO_FIXTURE/build/stale-artifact.txt"
echo "fixture" > "$PRESYNC_MONOREPO_PASS_FIXTURE/docs/notes.md"
echo "fixture" > "$PRESYNC_MONOREPO_PASS_FIXTURE/build/stale-artifact.txt"

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

# A manifest whose skill source does not exist, so prepare-plugin.sh exits 1
# with "  ERROR: skill source not found: <path>" on stderr. That line is the
# whole point of the fixture: it is the actionable text the auto-build used to
# throw away, and with the build stage now a mktemp -d that the EXIT trap
# removes, there is no partial build tree left to recover it from either.
# No SKILL.md beside it — the auto-build stage keys off the manifest alone, and
# this SKILLS_HOME is never used for a skill sync.
cat > "$SKILLS_HOME_BUILDFAIL_FIXTURE/broken-plugin/plugin-manifest.json" <<EOF
{
  "name": "broken-plugin-$$",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin whose skill source deliberately does not exist.",
  "skills": [
    {
      "name": "missing-skill",
      "source": "$BROKEN_SKILL_SOURCE"
    }
  ],
  "commands": []
}
EOF

# An already-published monorepo's .gitignore: plausible, and without /build/.
# The template written into a fresh monorepo cannot reach this file — write_file
# skips it — so the only thing that can tell the operator is an advisory line.
cat > "$MONOREPO_GITIGNORE_FIXTURE/.gitignore" <<'EOF'
.DS_Store
*.swp
*~
.claude/
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

# Four plugin manifests covering issue #77's three legal no-ops plus its one
# real error, all built in a single sync so the no-op cases can't hide behind
# each other:
#   hooks-none-plugin   — no "hooks" key at all (HOOK_COUNT stays 0)
#   hooks-null-plugin   — "hooks": {"source": null}
#   hooks-empty-plugin  — "hooks": {"source": ""}
#   hooks-ok-plugin     — "hooks": {"source": "./hooks-src"}, a real directory —
#                         the positive control: without the #77 fix (or with a
#                         fix patched to reject hooks unconditionally), this is
#                         the one manifest that would either silently drop
#                         hooks/ or fail to build at all.
for _hp in hooks-none-plugin hooks-null-plugin hooks-empty-plugin hooks-ok-plugin; do
    cat > "$SKILLS_HOME_HOOKS_FIXTURE/$_hp/SKILL.md" <<EOF
---
name: $_hp
description: Throwaway fixture skill backing the $_hp plugin manifest, used only by the sync-hygiene harness's hooks assertions.
version: 0.1.0
---

# ${_hp}

Fixture content.
EOF
done

cat > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-none-plugin/plugin-manifest.json" <<EOF
{
  "name": "hooks-none-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin with no hooks key at all — must remain a legal no-op.",
  "skills": [
    { "name": "hooks-none-plugin", "source": "." }
  ],
  "commands": []
}
EOF

cat > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-null-plugin/plugin-manifest.json" <<EOF
{
  "name": "hooks-null-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin with hooks.source explicitly null — must remain a legal no-op.",
  "skills": [
    { "name": "hooks-null-plugin", "source": "." }
  ],
  "commands": [],
  "hooks": { "source": null }
}
EOF

cat > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-empty-plugin/plugin-manifest.json" <<EOF
{
  "name": "hooks-empty-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin with hooks.source as an empty string — must remain a legal no-op.",
  "skills": [
    { "name": "hooks-empty-plugin", "source": "." }
  ],
  "commands": [],
  "hooks": { "source": "" }
}
EOF

cat > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/plugin-manifest.json" <<EOF
{
  "name": "hooks-ok-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin whose hooks.source names a real directory.",
  "skills": [
    { "name": "hooks-ok-plugin", "source": "." }
  ],
  "commands": [],
  "hooks": { "source": "./hooks-src" }
}
EOF

echo "#!/usr/bin/env bash" > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/hooks-src/pre-tool-use.sh"
echo "# Throwaway fixture hook, present only to prove hooks/ survives the build." \
    >> "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/hooks-src/pre-tool-use.sh"

# ------------------------------------------------------------------
# Issue #73 fixtures — legacy `"skills": ["name"]` manifests
# ------------------------------------------------------------------
#
# The skill's directory name matches the name inside skills[]. That is not
# cosmetic: a bare string carries no source, so it normalises to source "."
# (the manifest's own directory), and sync-monorepo.sh's drift check separately
# resolves the same name through skill_source_dir(), which looks the name up as
# a directory. The one real legacy manifest on this machine
# (github-release-board-promote) has exactly this shape.

cat > "$SKILLS_HOME_LEGACY_FIXTURE/legacy-sync-plugin/SKILL.md" <<'EOF'
---
name: legacy-sync-plugin
description: Throwaway fixture skill whose plugin manifest uses the legacy bare-string skills[] form.
version: 0.1.0
---

# legacy-sync-plugin

Fixture content.
EOF

cat > "$SKILLS_HOME_LEGACY_FIXTURE/legacy-sync-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "legacy-sync-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin declaring its skills in the legacy bare-string form.",
  "skills": ["legacy-sync-plugin"],
  "commands": []
}
EOF

# Run 14's monorepo holds a copy of the same skill at a version far ahead of the
# local source, which is the only thing that makes the reversion guard refuse it
# — and a refusal is the only way to reach the auto-build stage's
# `.skills[]?.name` read, the second of sync-monorepo.sh's two legacy-blind
# sites. Without it that site is never executed by this harness at all.
cat > "$MONOREPO_LEGACYREF_FIXTURE/legacy-sync-plugin/SKILL.md" <<'EOF'
---
name: legacy-sync-plugin
description: Throwaway fixture skill whose plugin manifest uses the legacy bare-string skills[] form.
version: 9.9.9
---

# legacy-sync-plugin

In-repo copy, deliberately far newer than the local source so the reversion
guard refuses it.
EOF

# ------------------------------------------------------------------
# Issue #73 fixtures — manifests driven straight into prepare-plugin.sh
# ------------------------------------------------------------------
#
# legacy-plugin     bare-string skills[], and NO CHANGELOG.md beside it, so the
#                   build takes the generated-template branch — the only branch
#                   that reaches the `.skills[$i].name` read inside the CHANGELOG
#                   stage. With a CHANGELOG present that read is never executed
#                   and a fix that missed it would still look green here.
# relsource-plugin  object-form skills[] with a *relative* source that is not
#                   ".": the regression guard for MANIFEST_DIR. If MANIFEST_DIR
#                   ever follows the normalised temp copy instead of the original
#                   manifest, "./nested-src" resolves under the temp directory
#                   and this build fails outright.
# barecmd-plugin    a bare string in commands[] — not normalisable, since a
#                   command's source is a file and "." would name a directory.
# bareagent-plugin  the same for agents[]. Both halves of the guard are checked;
#                   one alone is an N-1-of-N of the guard's own two branches.
# objentry-plugin   the positive control for that guard: object-form commands[]
#                   AND agents[] must still build. Without it, a "guard" that
#                   rejected every commands[]/agents[] entry would pass both
#                   rejection assertions.

cat > "$PREPARE_FIXTURE_DIR/legacy-plugin/SKILL.md" <<'EOF'
---
name: legacy-plugin
description: LEGACY-SOURCE-MARKER — throwaway fixture skill reached only through a legacy bare-string skills[] entry.
version: 0.1.0
---

# legacy-plugin

Fixture content.
EOF

cat > "$PREPARE_FIXTURE_DIR/legacy-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "legacy-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin declaring its skills in the legacy bare-string form.",
  "skills": ["legacy-plugin"],
  "commands": []
}
EOF

cat > "$PREPARE_FIXTURE_DIR/relsource-plugin/nested-src/SKILL.md" <<'EOF'
---
name: relsource-skill
description: RELSOURCE-MARKER — throwaway fixture skill reached only through a relative source that is not ".".
version: 0.1.0
---

# relsource-skill

Fixture content.
EOF

cat > "$PREPARE_FIXTURE_DIR/relsource-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "relsource-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin whose only skill source is a relative subdirectory.",
  "skills": [
    { "name": "relsource-skill", "source": "./nested-src" }
  ],
  "commands": []
}
EOF

cat > "$PREPARE_FIXTURE_DIR/barecmd-plugin/SKILL.md" <<'EOF'
---
name: barecmd-plugin
description: Throwaway fixture skill backing the bare-string commands[] manifest.
version: 0.1.0
---

# barecmd-plugin

Fixture content.
EOF

cat > "$PREPARE_FIXTURE_DIR/barecmd-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "barecmd-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin with a bare string in commands[], which is not normalisable.",
  "skills": [
    { "name": "barecmd-plugin", "source": "." }
  ],
  "commands": ["bare-command-entry"]
}
EOF

cat > "$PREPARE_FIXTURE_DIR/bareagent-plugin/SKILL.md" <<'EOF'
---
name: bareagent-plugin
description: Throwaway fixture skill backing the bare-string agents[] manifest.
version: 0.1.0
---

# bareagent-plugin

Fixture content.
EOF

cat > "$PREPARE_FIXTURE_DIR/bareagent-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "bareagent-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin with a bare string in agents[], which is not normalisable.",
  "skills": [
    { "name": "bareagent-plugin", "source": "." }
  ],
  "commands": [],
  "agents": ["bare-agent-entry"]
}
EOF

cat > "$PREPARE_FIXTURE_DIR/objentry-plugin/SKILL.md" <<'EOF'
---
name: objentry-plugin
description: Throwaway fixture skill backing the object-form commands[]/agents[] positive control.
version: 0.1.0
---

# objentry-plugin

Fixture content.
EOF

cat > "$PREPARE_FIXTURE_DIR/objentry-plugin/fixture-command.md" <<'EOF'
---
description: Throwaway fixture command, object-form.
---

Fixture command body.
EOF

cat > "$PREPARE_FIXTURE_DIR/objentry-plugin/fixture-agent.md" <<'EOF'
---
name: fixture-agent
description: Throwaway fixture agent, object-form.
---

Fixture agent body.
EOF

cat > "$PREPARE_FIXTURE_DIR/objentry-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "objentry-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin whose commands[] and agents[] are object-form and must still build.",
  "skills": [
    { "name": "objentry-plugin", "source": "." }
  ],
  "commands": [
    { "name": "fixture-command", "source": "./fixture-command.md" }
  ],
  "agents": [
    { "name": "fixture-agent", "source": "./fixture-agent.md" }
  ]
}
EOF

# ============================================================
# Sync invocations
# ============================================================
#
# Fourteen sync runs, all from the same throwaway cwd, followed by six direct
# prepare-plugin.sh invocations:
#   1. plain sync of monorepo/            — the main hygiene surface
#   2. --add added-skill on monorepo-add/ — the SECOND filter site (line ~197)
#   3. plain sync of monorepo-empty/      — the empty-skill-list branch
#   4. plain sync of monorepo-dashn/      — a -n skill reached through discovery
#   5. --skills -n on monorepo-skillsn/   — the same name, through --skills
#   6. --add -n on monorepo-addn/         — the same name, through --add
#   7. --add , on monorepo-addcomma/      — must fail loudly, not silently abort
#   8. plain sync of monorepo-buildfail/  — a failing auto-build must stay diagnosable
#   9. plain sync of monorepo-gitignore/  — a pre-existing .gitignore with no /build/
#  10. plain sync of monorepo-hooks/      — issue #77's three no-ops plus its positive control
#  11. second sync of monorepo-hooks/     — issue #77's error path, after the hooks source
#                                           is removed and the fixture's SKILL.md is bumped
#                                           to force a rebuild attempt
#  12. plain sync of monorepo-legacy/     — issue #73: a legacy bare-string manifest's
#                                           first build, through a sync
#  13. second sync of monorepo-legacy/    — the same manifest once published, so the
#                                           auto-build stage's drift read is reached
#  14. plain sync of monorepo-legacyref/  — the same manifest with its skill refused, so
#                                           the reversion-guard read is reached
#
# Run 2 exists because sync-monorepo.sh filters at two independent sites and a
# single no-`--add` invocation executes only one of them. Reverting the filter
# on the --add branch alone reproduces #74 verbatim while every run-1 assertion
# stays green.
#
# Runs 4-6 are three runs rather than one for the same reason: discover_skills()
# emits names from three independent expressions, and each one had its own copy
# of the `echo`-eats-`-n` defect. Reverting any single one leaves the other two
# green — verified, one revert at a time.
#
# Runs 7, 8, 11 and 14 are the ones expected to exit non-zero. An ADD_SKILL that reduces to
# nothing after comma-splitting (e.g. the literal argument `,`) used to leave
# the discovery pipeline's trailing `grep -v '^$'` with no line to match: it
# exited 1 and `set -e` killed the run with rc=1 and empty stderr — no
# explanation. discover_skills() now checks for that empty result itself and
# exits with a message naming the offending argument. run_sync()'s `|| rc=$?`
# already tolerates a non-zero sync, so capturing this run does not require
# touching the harness's own `set -e` posture. `--skills ,` was checked for the
# same shape and does not have it: with no `--add`, an empty result there is
# just the ordinary "0 skills to sync" case (defect 5, above) and the run exits
# 0 by design, so it gets no separate assertion.
#
# Run 8 is the only one using the second SKILLS_HOME. It is a separate run and a
# separate home so the deliberate build failure stays confined to it: the
# auto-build stage scans $SKILLS_HOME/*/plugin-manifest.json on every invocation,
# so a broken manifest in the shared home would print into all eight other runs
# that share it (runs 1-7 and 9 — runs 10-11 use the third, hooks-only, home).
#
# Run 9 is the only monorepo that starts with a .gitignore already on disk, which
# is the only way to reach write_file's "already exists" branch — the branch an
# already-published monorepo takes on every sync, and the one the template fix
# cannot reach.
#
# Run 10 exercises issue #77's three legal no-ops (hooks absent, hooks.source
# null, hooks.source "") and its one positive control (hooks.source naming a
# real directory) in a single sync, plus issue #79: this run's own generated
# READMEs — root and all four auto-built plugins' — are asserted to carry the
# --github-user value forwarded to it rather than the "USERNAME" fallback
# prepare-plugin.sh's own `gh api user` lookup produces when unauthenticated
# (the gh shim above guarantees that path is always unauthenticated).
#
# Run 11 is the only run that touches monorepo-hooks/ a second time. Between
# runs 10 and 11, hooks-ok-plugin's hooks-src/ is deleted and its SKILL.md is
# rewritten to a new version, so the auto-build stage's drift check (comparing
# SKILL.md between skills-home and the already-published monorepo copy) forces
# a rebuild attempt rather than skipping it as unchanged. That rebuild must fail
# --- a declared, non-empty hooks.source that no longer resolves to a directory
# is issue #77's actual error case, not a fourth no-op --- and the already-
# published plugins/hooks-ok-plugin/hooks/ from run 10 must survive, because
# the sync's existing rsync --delete only runs on the success branch (the same
# structure run 8's BUILDFAIL fixture already proves for a missing skill
# source). This is why the fixture needs two runs rather than one: run 10 alone
# cannot exercise the "already published, must not be deleted" half of the #77
# error case.
#
# SKILLS_HOME is an explicit first argument rather than an environment prefix on
# the call (`VAR=x run_sync …`): whether such an assignment persists past a shell
# *function* differs between bash's default and POSIX modes, and a home that
# leaked into the following run would be a silent cross-run contamination.

run_sync() {
    local skills_home="$1" monorepo="$2" stdout_log="$3" stderr_log="$4"
    shift 4
    local rc=0
    (
        cd "$RUN_CWD"
        PATH="$GH_SHIM_DIR:$PATH" \
        SKILLS_HOME="$skills_home" \
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

# LC_ALL=C so the two snapshots are ordered identically byte-wise whatever the
# ambient locale is — `comm` requires its inputs in the collation order it
# itself uses, and a locale-dependent `sort` is the classic way to violate that.
snapshot_mktemp_parent() {
    LC_ALL=C find "$MKTEMP_PARENT" -maxdepth 1 -mindepth 1 2>/dev/null | LC_ALL=C sort
}

TMP_BEFORE="$SCRATCH_DIR/mktemp-parent.before"
TMP_AFTER="$SCRATCH_DIR/mktemp-parent.after"
snapshot_mktemp_parent > "$TMP_BEFORE"

STDOUT_LOG="$SCRATCH_DIR/sync.stdout"
STDERR_LOG="$SCRATCH_DIR/sync.stderr"
SYNC_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_FIXTURE" "$STDOUT_LOG" "$STDERR_LOG" || SYNC_RC=$?
SYNC_STDOUT="$(cat "$STDOUT_LOG")"
SYNC_STDERR="$(cat "$STDERR_LOG")"

ADD_STDOUT_LOG="$SCRATCH_DIR/add.stdout"
ADD_STDERR_LOG="$SCRATCH_DIR/add.stderr"
ADD_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADD_FIXTURE" "$ADD_STDOUT_LOG" "$ADD_STDERR_LOG" --add added-skill || ADD_RC=$?
ADD_STDOUT="$(cat "$ADD_STDOUT_LOG")"

EMPTY_STDOUT_LOG="$SCRATCH_DIR/empty.stdout"
EMPTY_STDERR_LOG="$SCRATCH_DIR/empty.stderr"
EMPTY_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_EMPTY_FIXTURE" "$EMPTY_STDOUT_LOG" "$EMPTY_STDERR_LOG" || EMPTY_RC=$?
EMPTY_STDOUT="$(cat "$EMPTY_STDOUT_LOG")"

DASHN_STDOUT_LOG="$SCRATCH_DIR/dashn.stdout"
DASHN_STDERR_LOG="$SCRATCH_DIR/dashn.stderr"
DASHN_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_DASHN_FIXTURE" "$DASHN_STDOUT_LOG" "$DASHN_STDERR_LOG" || DASHN_RC=$?
DASHN_STDOUT="$(cat "$DASHN_STDOUT_LOG")"

# Runs 5 and 6: the same -n name arriving through the two paths that bypass
# discovery's filter entirely, so run 4 above cannot stand in for either.
# --skills feeds the name straight to `printf … | tr`, and --add concatenates it
# onto the comma-joined existing set — where an *empty* existing set leaves the
# bare name as the sole argument. Both went through `echo` before, which eats a
# leading -n: --skills reported "Skills to sync (0):" and synced nothing while
# still exiting 0, and --add emitted nothing at all, so its trailing `grep -v`
# exited 1 and aborted the run with an empty stderr.
SKILLSN_STDOUT_LOG="$SCRATCH_DIR/skillsn.stdout"
SKILLSN_STDERR_LOG="$SCRATCH_DIR/skillsn.stderr"
SKILLSN_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_SKILLSN_FIXTURE" "$SKILLSN_STDOUT_LOG" "$SKILLSN_STDERR_LOG" --skills -n || SKILLSN_RC=$?
SKILLSN_STDOUT="$(cat "$SKILLSN_STDOUT_LOG")"

ADDN_STDOUT_LOG="$SCRATCH_DIR/addn.stdout"
ADDN_STDERR_LOG="$SCRATCH_DIR/addn.stderr"
ADDN_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADDN_FIXTURE" "$ADDN_STDOUT_LOG" "$ADDN_STDERR_LOG" --add -n || ADDN_RC=$?
ADDN_STDOUT="$(cat "$ADDN_STDOUT_LOG")"

# Run 7: an ADD_SKILL that is itself nothing but separators. Expected to fail —
# see the note above run_sync's definition. Captured the same way as every
# other run so a dying `run_sync` cannot take the harness down with it.
ADDCOMMA_STDOUT_LOG="$SCRATCH_DIR/addcomma.stdout"
ADDCOMMA_STDERR_LOG="$SCRATCH_DIR/addcomma.stderr"
ADDCOMMA_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADDCOMMA_FIXTURE" "$ADDCOMMA_STDOUT_LOG" "$ADDCOMMA_STDERR_LOG" --add , || ADDCOMMA_RC=$?
ADDCOMMA_STDERR="$(cat "$ADDCOMMA_STDERR_LOG")"

# Run 8: the only run pointed at the second SKILLS_HOME, whose single manifest
# names a skill source that does not exist. prepare-plugin.sh exits 1, and as of
# #73 the sync surfaces the child's diagnosis and then exits 1 itself rather than
# carrying on to regenerate a catalogue describing a plugin it could not build.
BUILDFAIL_STDOUT_LOG="$SCRATCH_DIR/buildfail.stdout"
BUILDFAIL_STDERR_LOG="$SCRATCH_DIR/buildfail.stderr"
BUILDFAIL_RC=0
run_sync "$SKILLS_HOME_BUILDFAIL_FIXTURE" "$MONOREPO_BUILDFAIL_FIXTURE" "$BUILDFAIL_STDOUT_LOG" "$BUILDFAIL_STDERR_LOG" || BUILDFAIL_RC=$?
BUILDFAIL_STDOUT="$(cat "$BUILDFAIL_STDOUT_LOG")"
BUILDFAIL_STDERR="$(cat "$BUILDFAIL_STDERR_LOG")"

# Run 9: a monorepo whose .gitignore already exists and lacks /build/ — the shape
# every already-published monorepo has, and the one the embedded template can
# never reach.
GITIGNORE_STDOUT_LOG="$SCRATCH_DIR/gitignore.stdout"
GITIGNORE_STDERR_LOG="$SCRATCH_DIR/gitignore.stderr"
GITIGNORE_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_GITIGNORE_FIXTURE" "$GITIGNORE_STDOUT_LOG" "$GITIGNORE_STDERR_LOG" || GITIGNORE_RC=$?
GITIGNORE_STDOUT="$(cat "$GITIGNORE_STDOUT_LOG")"

# Run 10: the four hooks manifests, all built in one pass. --github-user is
# harness-fixture-user for every run in this file (run_sync hardcodes it); the
# README assertions below check that value, not the illustrative "probe" named
# in the issue.
HOOKS_STDOUT_LOG="$SCRATCH_DIR/hooks.stdout"
HOOKS_STDERR_LOG="$SCRATCH_DIR/hooks.stderr"
HOOKS_RC=0
run_sync "$SKILLS_HOME_HOOKS_FIXTURE" "$MONOREPO_HOOKS_FIXTURE" "$HOOKS_STDOUT_LOG" "$HOOKS_STDERR_LOG" || HOOKS_RC=$?
HOOKS_STDOUT="$(cat "$HOOKS_STDOUT_LOG")"
HOOKS_STDERR="$(cat "$HOOKS_STDERR_LOG")"

# Filesystem snapshot taken immediately after run 10, before run 11's mutation
# below removes hooks-src. Every assertion in this file runs after all eleven
# syncs, so a check against the live path on disk at that point measures
# end-of-harness state — identical to whatever run 11 leaves behind — not
# "run 10 copied hooks/". This is the one property run 10 alone can prove;
# capturing it here, mirroring how HOOKS_STDOUT/HOOKS_STDERR above are
# snapshotted per run rather than re-read live, is what keeps it distinct from
# the post-run-11 survival check below.
HOOKS_OK_HOOKS_AFTER_RUN10="ABSENT"
[[ -f "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-ok-plugin/hooks/pre-tool-use.sh" ]] && HOOKS_OK_HOOKS_AFTER_RUN10="PRESENT"

# Mutate the fixture between runs 10 and 11: remove the real hooks source and
# bump the skill's SKILL.md to a new version, so the auto-build stage's drift
# check (SKILL.md diff between skills-home and the published monorepo copy)
# forces a rebuild attempt instead of skipping hooks-ok-plugin as unchanged.
# The version goes forward (0.1.0 -> 0.2.0), not backward, so this cannot trip
# the reversion guard — that guard only refuses a source that is OLDER than
# what is already published.
rm -rf "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/hooks-src"
cat > "$SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/SKILL.md" <<EOF
---
name: hooks-ok-plugin
description: Throwaway fixture skill backing the hooks-ok-plugin manifest, used only by the sync-hygiene harness's hooks assertions.
version: 0.2.0
---

# hooks-ok-plugin

Fixture content, version-bumped to force run 11's rebuild attempt.
EOF

# Run 11: the forced rebuild, with hooks-src gone. Expected to exit 1: the child
# refuses (#77) and the sync layer treats a failed auto-build as fatal (#73). It
# is a second, independent path to that exit status from run 8's — run 8 fails on
# a missing skill source before the plugin exists at all, run 11 on a missing
# hooks source while a published copy is already on disk — so the two rc
# assertions are not duplicates of each other.
HOOKS2_STDOUT_LOG="$SCRATCH_DIR/hooks2.stdout"
HOOKS2_STDERR_LOG="$SCRATCH_DIR/hooks2.stderr"
HOOKS2_RC=0
run_sync "$SKILLS_HOME_HOOKS_FIXTURE" "$MONOREPO_HOOKS_FIXTURE" "$HOOKS2_STDOUT_LOG" "$HOOKS2_STDERR_LOG" || HOOKS2_RC=$?
HOOKS2_STDOUT="$(cat "$HOOKS2_STDOUT_LOG")"
HOOKS2_STDERR="$(cat "$HOOKS2_STDERR_LOG")"

# Run 12: the legacy manifest's first build. Nothing is published yet, so the
# auto-build stage takes its "plugin does not exist" branch and never consults
# the drift check — this run proves prepare-plugin.sh can assemble a legacy
# manifest at all, end to end through a sync.
LEGACY_STDOUT_LOG="$SCRATCH_DIR/legacy.stdout"
LEGACY_STDERR_LOG="$SCRATCH_DIR/legacy.stderr"
LEGACY_RC=0
run_sync "$SKILLS_HOME_LEGACY_FIXTURE" "$MONOREPO_LEGACY_FIXTURE" "$LEGACY_STDOUT_LOG" "$LEGACY_STDERR_LOG" || LEGACY_RC=$?
LEGACY_STDOUT="$(cat "$LEGACY_STDOUT_LOG")"

# Snapshotted here, before run 13 overwrites it: only the auto-build stage
# writes .claude-plugin/plugin.json, so its version is the one artifact that
# distinguishes "this plugin was rebuilt" from "the resync stage patched its
# SKILL.md" — and the resync stage would happily do the latter on run 13
# regardless of whether the drift check ever fired.
LEGACY_PLUGIN_JSON_AFTER_RUN12="$(cat "$MONOREPO_LEGACY_FIXTURE/plugins/legacy-sync-plugin/.claude-plugin/plugin.json" 2>/dev/null || true)"

# Mutate between runs 12 and 13: the SKILL.md version drives the drift check
# (forward, so the reversion guard cannot fire), and the manifest is what the
# rebuild — and only the rebuild — writes into plugin.json.
#
# The manifest's DESCRIPTION changes too, and it has to change *length*. The
# auto-build publishes through `rsync -a --delete`, whose default quick-check
# skips any file whose size and mtime both match the destination's. Bumping
# 0.1.0 -> 0.2.0 alone leaves plugin.json byte-for-byte the same size, so when
# runs 12 and 13 land in the same wall-clock second — measured at 3 of 5 runs —
# rsync skips it and the published plugin.json keeps run 12's content while the
# differently-sized SKILL.md beside it updates normally. The assertion below
# then reads a stale file and fails for a reason that has nothing to do with
# the drift check it is testing. A length change makes the transfer
# unconditional. (The underlying rsync behaviour is pre-existing and out of
# scope here; it only bites two builds inside one second.)
cat > "$SKILLS_HOME_LEGACY_FIXTURE/legacy-sync-plugin/SKILL.md" <<'EOF'
---
name: legacy-sync-plugin
description: Throwaway fixture skill whose plugin manifest uses the legacy bare-string skills[] form.
version: 0.2.0
---

# legacy-sync-plugin

Fixture content, version-bumped to force run 13's rebuild.
EOF

cat > "$SKILLS_HOME_LEGACY_FIXTURE/legacy-sync-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "legacy-sync-plugin",
  "version": "0.2.0",
  "description": "Throwaway fixture plugin declaring its skills in the legacy bare-string form, REBUILT-AFTER-DRIFT-MARKER.",
  "skills": ["legacy-sync-plugin"],
  "commands": []
}
EOF

# Run 13: the same pair again, with the plugin now already published. This is
# the run that reaches sync-monorepo.sh's own legacy-blind drift read — the one
# that made the plugin silently never rebuild.
LEGACY2_STDOUT_LOG="$SCRATCH_DIR/legacy2.stdout"
LEGACY2_STDERR_LOG="$SCRATCH_DIR/legacy2.stderr"
LEGACY2_RC=0
run_sync "$SKILLS_HOME_LEGACY_FIXTURE" "$MONOREPO_LEGACY_FIXTURE" "$LEGACY2_STDOUT_LOG" "$LEGACY2_STDERR_LOG" || LEGACY2_RC=$?
LEGACY2_STDOUT="$(cat "$LEGACY2_STDOUT_LOG")"

# Run 14: the same legacy manifest against a monorepo holding a far newer copy
# of its skill, so the reversion guard refuses that skill and the auto-build
# stage reaches its `.skills[]?.name` read. Expected to exit 3 — a refusal is
# not a success — which is also why it gets its own monorepo rather than reusing
# run 12/13's.
LEGACYREF_STDOUT_LOG="$SCRATCH_DIR/legacyref.stdout"
LEGACYREF_STDERR_LOG="$SCRATCH_DIR/legacyref.stderr"
LEGACYREF_RC=0
run_sync "$SKILLS_HOME_LEGACY_FIXTURE" "$MONOREPO_LEGACYREF_FIXTURE" "$LEGACYREF_STDOUT_LOG" "$LEGACYREF_STDERR_LOG" || LEGACYREF_RC=$?
LEGACYREF_STDOUT="$(cat "$LEGACYREF_STDOUT_LOG")"

snapshot_mktemp_parent > "$TMP_AFTER"

# ============================================================
# prepare-plugin.sh invocations (issue #73's manifest shapes)
# ============================================================
#
# Driven directly, not through a sync: these are shapes of prepare-plugin.sh's
# input, and the auto-build stage collapses every build failure into one line
# regardless of cause, so a sync could not tell "rejected a bare command entry"
# from "could not find a skill source". TMPDIR is redirected into a directory
# this harness owns so the normalised-manifest temp file's cleanup is assertable.
# $4/$5 override TMPDIR and the output directory; both default to the ordinary
# ones. Only the unusable-TMPDIR run below passes them.
run_prepare() {
    local fixture="$1" stdout_log="$2" stderr_log="$3"
    local tmpdir="${4:-$PREPARE_TMPDIR}" outdir="${5:-$PREPARE_OUT_DIR/$fixture}"
    local rc=0
    (
        cd "$RUN_CWD"
        PATH="$GH_SHIM_DIR:$PATH" \
        TMPDIR="$tmpdir" \
            "$PREPARE_SCRIPT" \
                --output-dir "$outdir" \
                --github-user harness-fixture-user \
                "$PREPARE_FIXTURE_DIR/$fixture/plugin-manifest.json"
    ) >"$stdout_log" 2>"$stderr_log" || rc=$?
    return "$rc"
}

PREPARE_LEGACY_RC=0
run_prepare legacy-plugin "$SCRATCH_DIR/prep-legacy.stdout" "$SCRATCH_DIR/prep-legacy.stderr" || PREPARE_LEGACY_RC=$?
PREPARE_LEGACY_STDERR="$(cat "$SCRATCH_DIR/prep-legacy.stderr")"

PREPARE_RELSOURCE_RC=0
run_prepare relsource-plugin "$SCRATCH_DIR/prep-relsource.stdout" "$SCRATCH_DIR/prep-relsource.stderr" || PREPARE_RELSOURCE_RC=$?
PREPARE_RELSOURCE_STDERR="$(cat "$SCRATCH_DIR/prep-relsource.stderr")"

PREPARE_BARECMD_RC=0
run_prepare barecmd-plugin "$SCRATCH_DIR/prep-barecmd.stdout" "$SCRATCH_DIR/prep-barecmd.stderr" || PREPARE_BARECMD_RC=$?
PREPARE_BARECMD_STDERR="$(cat "$SCRATCH_DIR/prep-barecmd.stderr")"

PREPARE_BAREAGENT_RC=0
run_prepare bareagent-plugin "$SCRATCH_DIR/prep-bareagent.stdout" "$SCRATCH_DIR/prep-bareagent.stderr" || PREPARE_BAREAGENT_RC=$?
PREPARE_BAREAGENT_STDERR="$(cat "$SCRATCH_DIR/prep-bareagent.stderr")"

PREPARE_OBJENTRY_RC=0
run_prepare objentry-plugin "$SCRATCH_DIR/prep-objentry.stdout" "$SCRATCH_DIR/prep-objentry.stderr" || PREPARE_OBJENTRY_RC=$?

# The same manifest that just built cleanly, re-run with TMPDIR pointed at a
# regular file. Reusing objentry-plugin is the point: it is known-good one line
# above, so the only thing that can make this run fail is the TMPDIR itself.
# Its output directory is a path nothing else uses, so "never created" is
# checkable — prepare-plugin.sh's mktemp runs before its `rm -rf "$OUTPUT_DIR"`,
# and a failure there must not have got as far as touching the output.
printf 'Not a directory. TMPDIR is pointed here to make mktemp fail.\n' > "$PREPARE_BAD_TMPDIR"
PREPARE_BADTMP_RC=0
run_prepare objentry-plugin "$SCRATCH_DIR/prep-badtmp.stdout" "$SCRATCH_DIR/prep-badtmp.stderr" \
    "$PREPARE_BAD_TMPDIR" "$PREPARE_OUT_DIR/badtmpdir-run" || PREPARE_BADTMP_RC=$?
PREPARE_BADTMP_STDERR="$(cat "$SCRATCH_DIR/prep-badtmp.stderr")"
PREPARE_BADTMP_OUTPUT_DIR="$([[ -e "$PREPARE_OUT_DIR/badtmpdir-run" ]] && echo PRESENT || echo ABSENT)"

# Counted after every invocation above, including the three that exit non-zero:
# the EXIT trap that removes the normalised manifest has to fire on the failure
# paths too, and a leaked file there is exactly what `rm -r` (no -f) would also
# have turned into a rewritten exit status.
PREPARE_TMPDIR_LEFTOVERS="$(find "$PREPARE_TMPDIR" -mindepth 1 2>/dev/null | wc -l | tr -d ' ')"

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
assert_eq "--skills -n run exits 0 on the fixture" "0" "$SKILLSN_RC"
assert_eq "--add -n run exits 0 on the fixture" "0" "$ADDN_RC"
assert_eq "pre-existing-.gitignore run exits 0 on the fixture" "0" "$GITIGNORE_RC"
assert_eq "hooks no-ops + positive-control run exits 0 on the fixture" "0" "$HOOKS_RC"
assert_eq "legacy-manifest first-build run exits 0 on the fixture" "0" "$LEGACY_RC"
assert_eq "legacy-manifest rebuild run exits 0 on the fixture" "0" "$LEGACY2_RC"

# A failed plugin auto-build is fatal as of #73. Both runs that produce one are
# asserted, for two independent causes — see run 11's fixture note. These two
# were the only "a failed auto-build still exits 0" assertions in this file
# (re-derived by grep, not carried over: `grep -n '_RC"$' | grep '"0"'` across
# every run, cross-checked against which runs have a failing manifest at all).
# Retiring one and not the other would have left the suite green while half the
# assertion set still encoded the behaviour #73 removed.
assert_eq "failing-auto-build run exits non-zero on the fixture (#73)" "1" "$BUILDFAIL_RC"
assert_eq "hooks forced-rebuild-failure run exits non-zero on the fixture (#73)" "1" "$HOOKS2_RC"

# Exit 3, not 1: the reversion guard refused a skill, and no build failed. This
# is the control that the fatal-build-failure change did not turn every
# unhappy-path sync into a bare exit 1.
assert_eq "legacy-manifest reversion-guard run exits 3 on the fixture" "3" "$LEGACYREF_RC"

assert_contains "control: the plugin auto-build stage actually ran" \
    "AUTO-SYNCED  plugins/$DEMO_PLUGIN_NAME/" "$SYNC_STDOUT"

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
# temp directory. A stage is claimed as this run's leak only if it holds
# $DEMO_PLUGIN_NAME, which carries this run's PID — so neither a stale stage from
# an earlier run nor a *concurrent* copy of this harness (whose in-flight stage is
# alive under the same temp parent for the duration) can turn this red. A fixed
# plugin name could not distinguish those, and did not: 3 of 3 concurrent pairs
# had one side report the other's live stage as its own leak.
#
# comm's output is captured to a file rather than consumed through a process
# substitution, whose exit status is unobservable: GNU comm exits 1 on
# "input is not in sorted order", and a silently-empty read would make the leak
# assertion pass vacuously — green through failure, the one shape worth ruling
# out here. LC_ALL=C in snapshot_mktemp_parent keeps both snapshots in the byte
# order comm expects regardless of locale, so the trigger is gone too.
TMP_NEW_ENTRIES="$SCRATCH_DIR/mktemp-parent.new"
COMM_RC=0
LC_ALL=C comm -13 "$TMP_BEFORE" "$TMP_AFTER" > "$TMP_NEW_ENTRIES" || COMM_RC=$?

assert_eq "comm compared the temp-parent snapshots successfully (leak scan is not vacuous)" \
    "0" "$COMM_RC"

LEAKED_BUILD_STAGES=""
while IFS= read -r _entry; do
    [[ -z "$_entry" ]] && continue
    if [[ -d "$_entry/$DEMO_PLUGIN_NAME" ]]; then
        LEAKED_BUILD_STAGES="${LEAKED_BUILD_STAGES}${_entry} "
    fi
done < "$TMP_NEW_ENTRIES"

assert_eq "no auto-build temp stage left behind under $MKTEMP_PARENT" \
    "" "${LEAKED_BUILD_STAGES% }"

# ============================================================
# Defect 8 — a failing auto-build must stay diagnosable
# ============================================================
#
# Cleaning up the stage (above) is what made this urgent: with the partial
# ./build/<name>/ tree gone from the caller's cwd, the child's own error line is
# the only evidence a failure ever produces — and it was being sent to
# /dev/null. Asserted on that line's *content*: a line that says "failed" and
# nothing else is precisely the undiagnosable state this closes.
#
# On stderr, with the child's log: as of #73 the whole failure path is an error
# rather than a warning, so it belongs on the same stream as the diagnosis it
# introduces — an operator redirecting stdout must not lose half of it.

assert_contains "control: the auto-build failure path actually ran" \
    "ERROR: prepare-plugin.sh failed for" "$BUILDFAIL_STDERR"

assert_contains "the failing manifest is named on stderr" \
    "$SKILLS_HOME_BUILDFAIL_FIXTURE/broken-plugin/plugin-manifest.json" "$BUILDFAIL_STDERR"

assert_line_present "the failing child's own error line reaches the operator" \
    "    |   ERROR: skill source not found: $BROKEN_SKILL_SOURCE" "$BUILDFAIL_STDERR"

# The refusal summary, distinct from the per-manifest line above: it is what
# names every failing manifest in one place and explains the partial state the
# run is leaving behind.
assert_contains "the run explains its refusal to continue, naming the manifest" \
    "Error: plugin build failed, refusing to continue: $SKILLS_HOME_BUILDFAIL_FIXTURE/broken-plugin/plugin-manifest.json" \
    "$BUILDFAIL_STDERR"

# The point of exiting: the catalogue-regenerating stages must not have run.
# Asserted on the monorepo's own files rather than on log text — the root README
# is generated from the plugin table and is written on every completed sync, so
# its absence is the load-bearing evidence that the run stopped where it claimed
# to. Without this, an "exit 1" bolted onto the very end of the script would
# satisfy every other assertion in this section.
# Both artifacts are written unconditionally by a completed run. Deliberately
# NOT marketplace.json, which the script only writes when the monorepo has at
# least one published plugin — this fixture's one plugin is the one that failed,
# so marketplace.json would be absent whether the run stopped or not, and the
# assertion would pass under the un-fixed script too. (Measured: it does.)
assert_eq "a failed build stops before the root README is regenerated" "ABSENT" \
    "$([[ -f "$MONOREPO_BUILDFAIL_FIXTURE/README.md" ]] && echo PRESENT || echo ABSENT)"
assert_eq "a failed build stops before the root CHANGELOG is regenerated" "ABSENT" \
    "$([[ -f "$MONOREPO_BUILDFAIL_FIXTURE/CHANGELOG.md" ]] && echo PRESENT || echo ABSENT)"

# …and the other direction, so the two above cannot pass merely because this
# fixture never generates those files: a run that completes does write them.
assert_file_exists "positive control: a completed sync does regenerate the root README" \
    "$MONOREPO_LEGACY_FIXTURE/README.md"
assert_file_exists "positive control: a completed sync does regenerate the marketplace catalogue" \
    "$MONOREPO_LEGACY_FIXTURE/.claude-plugin/marketplace.json"

# The other half of the control pair: proves the run took the failure branch
# rather than somehow succeeding, so the assertion above cannot be satisfied by a
# build that worked and printed the line for some unrelated reason.
assert_not_contains "a failed build is not also reported as synced" \
    "AUTO-SYNCED" "$BUILDFAIL_STDOUT"

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

# …and that it matches *only* at the root. The assertion above is anchoring-blind:
# it reads IGNORED under `/build/` and under a bare `build/` alike, so on its own
# it only catches the pattern being deleted, not the anchor being lost. The
# generated-.gitignore assertion above covers anchoring for what the script emits;
# this covers the same property for this repo's own file, which nothing else does.
# `plugins/placeholder/` is a path no plugin occupies, so no nested plugin
# .gitignore can decide the answer instead.
#
# `git check-ignore -q` exits 0 = ignored, 1 = not-ignored, 128 = error (e.g.
# bad repo path). The `&&`-into-a-string form used above for the positive
# assertion collapses 1 and 128 into the same default value here, and that
# default happens to equal this assertion's *expected* value — so a genuine
# git error would read as a clean NOT-IGNORED pass instead of failing loudly.
# Capture the literal exit status instead and assert on that, so 1 and 128
# are distinguishable. The `|| VAR=$?` form (not a bare call) is required for
# `set -e` safety: check-ignore's expected-for-this-path exit of 1 must not be
# treated as a fatal error by the harness itself.
NESTED_BUILD_RC=0
git -C "$REPO_ROOT" check-ignore -q "plugins/placeholder/build/" || NESTED_BUILD_RC=$?

assert_eq "this repo's .gitignore does NOT ignore a nested build/" "1" "$NESTED_BUILD_RC"

# ============================================================
# Defect 9 — an already-published monorepo must be told, not skipped past
# ============================================================
#
# Site A above only covers monorepos that do not have a .gitignore yet, because
# write_file does not overwrite: every monorepo that already exists — including
# this one — takes the "already exists" branch and receives the template's fix
# never. All that branch printed was a SKIP line, which reads identically whether
# the existing file carries the rule or not. A non-fatal NOTE now distinguishes
# them.

assert_contains "control: the .gitignore stage reached its \"already exists\" branch" \
    "SKIP    .gitignore (already exists)" "$GITIGNORE_STDOUT"

assert_contains "an existing .gitignore with no /build/ line is called out" \
    "NOTE: .gitignore exists but has no '/build/' line" "$GITIGNORE_STDOUT"

# …and the NOTE is conditional, not decoration. Run 1's monorepo started with no
# .gitignore, so the sync wrote the template — which carries /build/ — and there
# is nothing left to advise about. Without this, an advisory printed
# unconditionally would satisfy the assertion above just as well.
assert_not_contains "a .gitignore that carries /build/ draws no NOTE" \
    "NOTE: .gitignore" "$SYNC_STDOUT"

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

# Known ~1-in-86,400 window: $TODAY is computed once when this harness starts and
# again inside each sync, so a run that straddles midnight compares yesterday's
# expectation against today's written entry and this goes red. Left as-is
# deliberately — the failure is loud and self-evident from the two dates in the
# message, and threading the harness's clock into the child sync would couple the
# test to an implementation detail to buy nothing but that one second.
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

# The other two writers of the same name list. Each is checked on both the
# printed list and disk: "Skills to sync (0):" followed by a full root-files
# sync and a clean exit 0 is exactly what the --skills defect produced, so an
# exit-status control alone would not have caught it.
SKILLSN_SYNCED_NAMES="$(synced_names "$SKILLSN_STDOUT")"
assert_line_present "--skills -n names the -n skill rather than eating it" \
    "-n" "$SKILLSN_SYNCED_NAMES"
assert_eq "--skills -n reports a count of 1, not 0" \
    "1" "$(printed_skill_count "$SKILLSN_STDOUT")"
assert_file_exists "--skills -n wrote the -n skill to disk" \
    "$MONOREPO_SKILLSN_FIXTURE/-n/SKILL.md"

ADDN_SYNCED_NAMES="$(synced_names "$ADDN_STDOUT")"
assert_line_present "--add -n into a monorepo with no existing skills names it" \
    "-n" "$ADDN_SYNCED_NAMES"
assert_file_exists "--add -n wrote the -n skill to disk" \
    "$MONOREPO_ADDN_FIXTURE/-n/SKILL.md"

# ============================================================
# --add with a separator-only argument must fail loudly, not silently
# ============================================================
#
# `--add ,` reduces to nothing after comma-splitting: with no existing skills
# in the target monorepo, there is no line left for the discovery pipeline's
# trailing `grep -v '^$'` to match, so it used to exit 1 and take the whole
# run down under `set -e` with an empty stderr — rc=1 and no clue why. The
# assertions here are about the
# run's rc and its stderr content; a failure of "no skill(s) synced" would be
# the wrong kind of green here, since the run must not silently succeed either.
assert_eq "--add , fails with a deliberate, explained exit rather than an unexplained abort" \
    "1" "$ADDCOMMA_RC"
assert_contains "--add , explains itself on stderr, naming the offending argument" \
    "Error: --add produced no skill names from: ','" "$ADDCOMMA_STDERR"

# ============================================================
# Issue #77 — a declared, non-empty hooks.source that does not resolve to a
# directory must error, not silently skip; the three legal no-ops must survive
# ============================================================

assert_contains "control: hooks-none-plugin was auto-built" \
    "AUTO-SYNCED  plugins/hooks-none-plugin/" "$HOOKS_STDOUT"
assert_contains "control: hooks-null-plugin was auto-built" \
    "AUTO-SYNCED  plugins/hooks-null-plugin/" "$HOOKS_STDOUT"
assert_contains "control: hooks-empty-plugin was auto-built" \
    "AUTO-SYNCED  plugins/hooks-empty-plugin/" "$HOOKS_STDOUT"
assert_contains "control: hooks-ok-plugin was auto-built" \
    "AUTO-SYNCED  plugins/hooks-ok-plugin/" "$HOOKS_STDOUT"

# The three no-op cases must not carry a hooks/ directory into the published
# plugin — there was never a real source to copy.
assert_eq "hooks-none-plugin (no hooks key) has no hooks/ dir" "ABSENT" \
    "$([[ -d "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-none-plugin/hooks" ]] && echo PRESENT || echo ABSENT)"
assert_eq "hooks-null-plugin (hooks.source: null) has no hooks/ dir" "ABSENT" \
    "$([[ -d "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-null-plugin/hooks" ]] && echo PRESENT || echo ABSENT)"
assert_eq "hooks-empty-plugin (hooks.source: \"\") has no hooks/ dir" "ABSENT" \
    "$([[ -d "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-empty-plugin/hooks" ]] && echo PRESENT || echo ABSENT)"

# The positive control: a real hooks.source must actually land in the build.
# Without this, a fix that rejected every hooks.source unconditionally (a guard
# stuck ON) would still pass every assertion above.
#
# Checked against the HOOKS_OK_HOOKS_AFTER_RUN10 snapshot taken right after run
# 10, not by re-testing the live path here: every assertion in this file runs
# after all eleven syncs, and run 11 deliberately deletes hooks-src and forces
# a rebuild of this exact plugin. A live re-check at this point in the file
# would be byte-for-byte the same predicate as the post-run-11 survival check
# below — run 10's own positive control would be silently absorbed into run
# 11's, and reverting either fix would fail both assertions for one cause
# instead of the two the brief asks for.
assert_eq "positive control: hooks-ok-plugin's hooks/ was copied (as of run 10)" \
    "PRESENT" "$HOOKS_OK_HOOKS_AFTER_RUN10"

# None of the four no-op/positive-control builds may have errored.
HOOKS_ERROR_LINES=$(printf '%s\n%s\n' "$HOOKS_STDOUT" "$HOOKS_STDERR" | grep 'ERROR' || true)
assert_eq "no ERROR line from the run-10 hooks fixtures" "" "$HOOKS_ERROR_LINES"

# Run 11: hooks-src is gone and the SKILL.md version bump forced a rebuild
# attempt. The child must refuse — matching the skills/commands/agents
# siblings' error shape — and the sync layer must surface that refusal rather
# than reporting success.
assert_contains "control: run 11 actually attempted to rebuild hooks-ok-plugin" \
    "ERROR: prepare-plugin.sh failed for" "$HOOKS2_STDERR"
assert_line_present "the child's hooks-source error reaches the operator" \
    "    |   ERROR: hooks source not found: $SKILLS_HOME_HOOKS_FIXTURE/hooks-ok-plugin/./hooks-src" \
    "$HOOKS2_STDERR"
assert_not_contains "the failed hooks rebuild is not also reported as synced" \
    "AUTO-SYNCED  plugins/hooks-ok-plugin/" "$HOOKS2_STDOUT"

# The load-bearing assertion for #77's second half: the already-published
# plugin from run 10 must survive a failed rebuild attempt untouched, because
# the destructive `rsync --delete` only runs on the child's success branch.
# Without prepare-plugin.sh refusing first, this is exactly the shape #77
# describes: the missing source is skipped, the child reports success, and
# `rsync --delete` removes hooks/ from the published plugin.
assert_file_exists "the already-published hooks/ survives a failed rebuild attempt" \
    "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-ok-plugin/hooks/pre-tool-use.sh"

# ============================================================
# Issue #79 — the auto-build stage must forward --github-user, not fall back
# to prepare-plugin.sh's own (shimmed-to-fail) `gh api user` lookup
# ============================================================
#
# Every README this run generates — the monorepo root and all four auto-built
# plugins' — must carry the value this run passed via --github-user
# (harness-fixture-user, hardcoded in run_sync) rather than the literal
# "USERNAME" prepare-plugin.sh falls back to when it resolves its own GitHub
# user and gh fails. The root README is not itself part of #79 (sync-monorepo.sh
# substitutes {{GITHUB_USER}} into it directly, independent of prepare-plugin.sh)
# but is asserted anyway per the issue's own test list, and as a control that a
# fix which broke --github-user forwarding entirely couldn't hide behind a root
# README that was never wrong to begin with.

ROOT_README_CONTENT="$(cat "$MONOREPO_HOOKS_FIXTURE/README.md" 2>/dev/null || true)"
assert_contains "root README carries the forwarded --github-user" \
    "harness-fixture-user" "$ROOT_README_CONTENT"
assert_not_contains "root README does not fall back to USERNAME" \
    "USERNAME" "$ROOT_README_CONTENT"

# Globbed rather than the hardcoded four names used to build the fixture
# (line ~532 above): a fifth manifest added to skills-home-hooks/ later must
# not be able to escape this loop by simply not being named here.
# `|| true` on the pipeline, not just the `find`: under `set -euo pipefail` (see
# this file's top), a missing plugins/ dir makes `find` exit non-zero, which
# propagates through the pipe into this assignment and kills the whole harness
# right here — no summary line, no FAIL naming what happened, and everything
# after this point (the count control below, all per-plugin README checks, and
# the authoring-source-parity section at the end) silently never runs. `|| true`
# turns that into an empty $HOOKS_PUBLISHED_PLUGINS, which the count control
# below reports as an explained "expected [4] ... got [0]" instead.
HOOKS_PUBLISHED_PLUGINS=$(find "$MONOREPO_HOOKS_FIXTURE/plugins" -maxdepth 1 -mindepth 1 -type d \
    -exec basename {} \; 2>/dev/null | LC_ALL=C sort || true)

# Control on the glob itself: without this, a run that silently built fewer
# than four plugins (or somehow more) would just iterate the loop below over
# whatever it found and still print all-PASS — the same "green through
# omission" shape the fail-first discipline in this file exists to rule out.
assert_eq "exactly the four hooks fixture plugins were published" \
    "4" "$(printf '%s\n' "$HOOKS_PUBLISHED_PLUGINS" | grep -c .)"

while IFS= read -r _hp; do
    [[ -z "$_hp" ]] && continue
    _hp_readme_path="$MONOREPO_HOOKS_FIXTURE/plugins/$_hp/README.md"
    # Checked as its own assertion, not folded into the `cat … || true` below:
    # `|| true` turns a missing file into an empty string, and an empty string
    # already satisfies assert_not_contains "USERNAME" — so a README that
    # never got written would pass that half silently. assert_contains still
    # catches it (empty can't contain "harness-fixture-user"), but only by
    # accident of which literal is being searched for; this makes the missing
    # case fail on its own, for its own reason, regardless of either literal.
    assert_file_exists "plugins/$_hp/README.md exists" "$_hp_readme_path"
    _hp_readme="$(cat "$_hp_readme_path" 2>/dev/null || true)"
    assert_contains "plugins/$_hp/README.md carries the forwarded --github-user" \
        "harness-fixture-user" "$_hp_readme"
    assert_not_contains "plugins/$_hp/README.md does not fall back to USERNAME" \
        "USERNAME" "$_hp_readme"
done <<< "$HOOKS_PUBLISHED_PLUGINS"

# ============================================================
# Issue #73 — a legacy bare-string skills[] manifest must build, and a failed
# build must stop the run
# ============================================================
#
# Before the fix, every `.skills[$i].name` / `.skills[$i].source` read in
# prepare-plugin.sh died on such a manifest with
# `jq: error … Cannot index string with "name"` (measured: rc=5, no plugin
# assembled). There are eight of those reads, so the fix normalises the manifest
# once into a temp copy and points every read at it — and this fixture is
# arranged so that all eight are actually executed. A read left un-normalised
# still errors, `set -e` still kills the child, and the rc assertion below still
# goes red: the fixture is itself the N-1-of-N detector, not a spot check.

assert_eq "a legacy bare-string skills[] manifest builds" "0" "$PREPARE_LEGACY_RC"

assert_not_contains "…without the legacy shape reaching jq" \
    "Cannot index string" "$PREPARE_LEGACY_STDERR"

assert_file_exists "the legacy manifest's skill is assembled under its declared name" \
    "$PREPARE_OUT_DIR/legacy-plugin/skills/legacy-plugin/SKILL.md"
assert_file_exists "the legacy manifest still produces a plugin manifest" \
    "$PREPARE_OUT_DIR/legacy-plugin/.claude-plugin/plugin.json"

# Content, not just existence: a bare string normalises to source ".", and the
# only proof that "." resolved against the ORIGINAL manifest's directory is that
# the description was read out of the SKILL.md that lives there. This is the
# README's Contents list — the `.skills[$i].source` read furthest from the copy
# loop, and the one a partial fix is likeliest to miss.
PREPARE_LEGACY_README="$(cat "$PREPARE_OUT_DIR/legacy-plugin/README.md" 2>/dev/null || true)"
assert_contains "the legacy skill's source resolved to the manifest's own directory" \
    "LEGACY-SOURCE-MARKER" "$PREPARE_LEGACY_README"

# The CHANGELOG stage's own `.skills[$i].name` read, reachable only on the
# generated-template branch — hence a fixture with no CHANGELOG.md beside it.
PREPARE_LEGACY_CHANGELOG="$(cat "$PREPARE_OUT_DIR/legacy-plugin/CHANGELOG.md" 2>/dev/null || true)"
assert_contains "the generated CHANGELOG names the legacy skill" \
    '- Skill: `legacy-plugin`' "$PREPARE_LEGACY_CHANGELOG"

# The MANIFEST_DIR regression guard. If MANIFEST_DIR ever follows the normalised
# temp copy, "./nested-src" resolves under the temp directory, the source is not
# found, and this build exits 1 — which is why the rc and the marker are both
# asserted: the marker alone would be satisfiable by an empty file.
assert_eq "a relative source that is not \".\" still builds" "0" "$PREPARE_RELSOURCE_RC"
assert_file_exists "the relative source's skill is assembled" \
    "$PREPARE_OUT_DIR/relsource-plugin/skills/relsource-skill/SKILL.md"
PREPARE_RELSOURCE_README="$(cat "$PREPARE_OUT_DIR/relsource-plugin/README.md" 2>/dev/null || true)"
assert_contains "the relative source resolved against the original manifest's directory" \
    "RELSOURCE-MARKER" "$PREPARE_RELSOURCE_README"

# A bare string in commands[]/agents[] names a *file* source, so "." would mean
# nothing; both are refused rather than guessed at.
assert_eq "a bare string in commands[] is refused" "1" "$PREPARE_BARECMD_RC"
assert_contains "…with a message naming the offending entry" \
    "ERROR: command entry must be an object with 'name' and 'source', not a bare string: bare-command-entry" \
    "$PREPARE_BARECMD_STDERR"
assert_contains "…and the manifest the caller actually named, not the temp copy" \
    "$PREPARE_FIXTURE_DIR/barecmd-plugin/plugin-manifest.json" "$PREPARE_BARECMD_STDERR"

assert_eq "a bare string in agents[] is refused" "1" "$PREPARE_BAREAGENT_RC"
assert_contains "…with a message naming the offending entry" \
    "ERROR: agent entry must be an object with 'name' and 'source', not a bare string: bare-agent-entry" \
    "$PREPARE_BAREAGENT_STDERR"

# Positive control for that guard: object-form commands[] and agents[] must
# still build and still be copied. Without this, a guard that rejected every
# commands[]/agents[] entry outright would pass both assertions above.
assert_eq "positive control: object-form commands[] and agents[] still build" \
    "0" "$PREPARE_OBJENTRY_RC"
assert_file_exists "positive control: an object-form command is still copied" \
    "$PREPARE_OUT_DIR/objentry-plugin/commands/fixture-command.md"
assert_file_exists "positive control: an object-form agent is still copied" \
    "$PREPARE_OUT_DIR/objentry-plugin/agents/fixture-agent.md"

# --- The normalised manifest's temp file: created where we think, then removed ---
#
# These two assertions only mean something together. A leftover count of 0 on
# its own is satisfied identically by "created and cleaned up" and by "never
# created there at all" — and "never created there" is not hypothetical: it is
# what a bare `mktemp` produces on macOS, where BSD mktemp ignores TMPDIR unless
# the template says otherwise. So the location has to be pinned first.
#
# Pinned by pointing TMPDIR at something no file can be created inside and
# requiring the run to die there. mktemp's own message carries the path, which
# is what makes this checkable without prepare-plugin.sh growing a diagnostic
# it would not otherwise need.
#
# Honest limit: this discriminates on BSD mktemp (macOS), where a bare `mktemp`
# would ignore this TMPDIR and succeed, turning the assertion red. On GNU mktemp
# (CI) both forms honour TMPDIR, so both fail and the assertion cannot tell them
# apart — it still cannot pass falsely there, it just stops being a tripwire for
# that particular simplification. The leak direction below is measured by
# mutation instead: deleting prepare-plugin.sh's EXIT trap takes the count from
# 0 to 5, which is also a second, platform-independent proof that the file is
# being created in $PREPARE_TMPDIR.
assert_eq "an unusable TMPDIR stops the run rather than relocating the temp file" \
    "1" "$PREPARE_BADTMP_RC"
assert_contains "…and mktemp's failure names the TMPDIR that was honoured" \
    "$PREPARE_BAD_TMPDIR" "$PREPARE_BADTMP_STDERR"
assert_eq "…before any output directory is created" \
    "ABSENT" "$PREPARE_BADTMP_OUTPUT_DIR"

# Positive control for the three above: the same manifest, with an ordinary
# TMPDIR, builds cleanly (asserted by PREPARE_OBJENTRY_RC and the two copied
# files above). Without that pairing, a prepare-plugin.sh that failed on every
# TMPDIR would satisfy all three.
#
# `rm -rf` rather than `rm -r` in the trap is load-bearing for a second reason
# this count cannot see — under `set -e` a trap body returning non-zero rewrites
# the script's exit status — verified separately rather than asserted here.
assert_eq "prepare-plugin.sh leaves no normalised-manifest temp file behind" \
    "0" "$PREPARE_TMPDIR_LEFTOVERS"

# --- The sync layer's own two legacy-blind reads ---
#
# Run 12: nothing published yet, so this only proves the child can build the
# manifest end to end through a sync. Run 13 is the one that reaches the drift
# read.
assert_contains "control: a legacy manifest is auto-built through a sync" \
    "AUTO-SYNCED  plugins/legacy-sync-plugin/" "$LEGACY_STDOUT"
assert_contains "the first build wrote the manifest's version into plugin.json" \
    '"version": "0.1.0"' "$LEGACY_PLUGIN_JSON_AFTER_RUN12"

# Run 13: the drift check compares the source SKILL.md against the published
# copy, and it needs the manifest's FIRST SKILL NAME to do it. On a legacy
# manifest that read errored into 2>/dev/null, leaving the name empty, the drift
# check skipped, and the plugin never rebuilt.
#
# Asserted on plugin.json rather than on the published SKILL.md: the plugin
# auto-RESYNC stage further down would have patched that SKILL.md across
# regardless of whether the drift check ever fired, so a SKILL.md assertion here
# would be green with the fix reverted. Only the auto-build stage writes
# plugin.json.
#
# Matched on the description marker, not on the version string: see the
# rsync quick-check note beside run 13's fixture mutation above. The marker is
# the part of the rebuilt manifest that changes plugin.json's *size*, so it is
# also the part that cannot be silently skipped in transit.
LEGACY_PLUGIN_JSON_AFTER_RUN13="$(cat "$MONOREPO_LEGACY_FIXTURE/plugins/legacy-sync-plugin/.claude-plugin/plugin.json" 2>/dev/null || true)"
assert_contains "a drifted legacy manifest is actually rebuilt, not silently skipped" \
    "REBUILT-AFTER-DRIFT-MARKER" "$LEGACY_PLUGIN_JSON_AFTER_RUN13"
# The other direction: run 12's snapshot must NOT already carry the marker, or
# the assertion above would be satisfied by the first build rather than the
# rebuild.
assert_not_contains "…and the marker is not something the first build already wrote" \
    "REBUILT-AFTER-DRIFT-MARKER" "$LEGACY_PLUGIN_JSON_AFTER_RUN12"
assert_contains "control: run 13 reported the rebuild" \
    "AUTO-SYNCED  plugins/legacy-sync-plugin/" "$LEGACY2_STDOUT"

# Run 14: the reversion guard refused this manifest's only skill, and the
# auto-build stage must recognise that from the manifest's skill names — the
# second legacy-blind read. Blind, it saw no skills, skipped nothing, and
# rebuilt the plugin from the stale local source the main loop had just refused.
assert_contains "a refused skill is recognised through a legacy manifest" \
    "SKIP (reversion guard)  plugins/legacy-sync-plugin  —  stale local source for: legacy-sync-plugin" \
    "$LEGACYREF_STDOUT"
assert_not_contains "…and the refused plugin is not built anyway" \
    "AUTO-SYNCED  plugins/legacy-sync-plugin/" "$LEGACYREF_STDOUT"

# ============================================================
# Issue #78 — validate-pre-sync.sh must see in-repo-source skills
# ============================================================
#
# validate-pre-sync.sh hardcoded SKILL_SRC="$SKILLS_HOME/$SKILL_NAME" and
# `continue`d whenever the local SKILL.md was absent — the same branch a
# genuine non-skill directory (docs/, build/) takes. An in-repo-source-only
# skill (no local copy at all — github-board-move and the three spec-* skills,
# in the real repo) fell into that branch too: never counted in TOTAL, never
# counted as a FAIL, and the run printed "Safe to sync" without ever having
# examined it. It now resolves every skill through skill_source_dir() (_lib.sh),
# the same function sync-monorepo.sh sources its own skills through, so
# discovery can never disagree with sourcing.
#
# Parses "Total: N | Pass: P | Fail: F" out of validate-pre-sync.sh's own
# summary line, not out of counting RESULTS lines: the bug was printing a green
# summary despite having examined too few skills, so the summary's own number
# is exactly what has to be checked, not a paraphrase of it.
presync_total() {
    sed -n 's/^Total: \([0-9]*\).*/\1/p' <<< "$1"
}
presync_pass() {
    sed -n 's/^Total: [0-9]* | Pass: \([0-9]*\).*/\1/p' <<< "$1"
}
presync_fail() {
    sed -n 's/^Total: [0-9]* | Pass: [0-9]* | Fail: \([0-9]*\)$/\1/p' <<< "$1"
}

run_presync() {
    local skills_home="$1" monorepo="$2"
    (
        cd "$RUN_CWD"
        SKILLS_HOME="$skills_home" "$PRESYNC_SCRIPT" "$monorepo"
    )
}

PRESYNC_RC=0
PRESYNC_STDOUT="$(run_presync "$PRESYNC_SKILLS_HOME_FIXTURE" "$PRESYNC_MONOREPO_FIXTURE")" || PRESYNC_RC=$?

PRESYNC_PASS_RC=0
PRESYNC_PASS_STDOUT="$(run_presync "$PRESYNC_SKILLS_HOME_FIXTURE" "$PRESYNC_MONOREPO_PASS_FIXTURE")" || PRESYNC_PASS_RC=$?

# --- Core assertion: an in-repo-source-only skill with a mismatched CHANGELOG
# is examined and blocks the sync. Before the fix this fixture exits 0 with
# Total: 1 (presync-inrepo-skill silently omitted) — verified by hand against a
# reverted scratch copy of validate-pre-sync.sh, both loop forms restored. ---
assert_eq "issue #78 core: in-repo-source skill with mismatched CHANGELOG blocks the sync" \
    "1" "$PRESYNC_RC"
assert_contains "…and is named in the FAIL line with the right version" \
    "FAIL  presync-inrepo-skill — SKILL.md says v2.0.0 but CHANGELOG latest is v1.0.0" \
    "$PRESYNC_STDOUT"
assert_eq "…Total counts both real skills despite docs/ and build/ present" \
    "2" "$(presync_total "$PRESYNC_STDOUT")"
assert_eq "…Pass is exactly the local-source skill" "1" "$(presync_pass "$PRESYNC_STDOUT")"
assert_eq "…Fail is exactly the in-repo-source skill" "1" "$(presync_fail "$PRESYNC_STDOUT")"
assert_contains "…a local-source skill still validates exactly as before" \
    "PASS  presync-local-skill v1.0.0" "$PRESYNC_STDOUT"
assert_not_contains "…docs/ never enters the report" "docs" "$PRESYNC_STDOUT"
assert_not_contains "…build/ never enters the report" "build" "$PRESYNC_STDOUT"

# --- Positive control: same skill, CHANGELOG updated to match v2.0.0. Without
# this, a rework that failed every skill unconditionally would still satisfy
# every assertion above — verified by hand: patching the CHANGELOG-match guard
# to `if false && grep …` (an unconditional reject) turns this fixture's Pass
# count from 2 to 0 and its exit status from 0 to 1. ---
assert_eq "positive control: a matching CHANGELOG entry exits 0" \
    "0" "$PRESYNC_PASS_RC"
assert_contains "…and the skill appears in the PASS list with the right version" \
    "PASS  presync-inrepo-skill v2.0.0" "$PRESYNC_PASS_STDOUT"
assert_eq "…Total is still 2 (docs/ and build/ still excluded)" \
    "2" "$(presync_total "$PRESYNC_PASS_STDOUT")"
assert_eq "…Pass is both skills" "2" "$(presync_pass "$PRESYNC_PASS_STDOUT")"
assert_eq "…Fail is zero" "0" "$(presync_fail "$PRESYNC_PASS_STDOUT")"
assert_contains "…\"Safe to sync\" banner prints" \
    "All skills have matching CHANGELOG entries. Safe to sync." "$PRESYNC_PASS_STDOUT"

# ============================================================
# Authoring-source parity
# ============================================================
#
# skill-publishing is authored outside the repo and published into plugins/**.
# A fix applied to only one copy is a fix that either nobody receives or the
# next sync silently reverts. The live copy does not exist in CI.

# Compared as a tree. The single-file form this replaced diffed scripts/
# sync-monorepo.sh alone while describing the whole publish relationship, so
# SKILL.md and CHANGELOG.md — two of the three files a typical change to this
# skill touches — could drift with the check still green. SKILL.md is the
# load-bearing one: its metadata.version is what the reversion guard compares, so
# a live copy left behind on the older version is exactly the stale-source shape
# that guard exists to catch.
#
# The live copy is its own git repo and carries repo scaffolding the published
# copy has no business containing (verified: these seven names are the entire
# delta). Filtered by anchored whole-line match on diff's own "Only in <live>:"
# form, so the exclusion applies to those top-level entries and nothing nested.
#
# `diff -rq` for the message's sake: one line per differing or missing file
# instead of every changed line of a 1300-line script.
if [[ -d "$LIVE_SKILL_DIR" ]]; then
    LIVE_ONLY_SCAFFOLD="^Only in $LIVE_SKILL_DIR: (\.git|\.github|\.gitignore|CONTRIBUTING\.md|LICENSE|README\.md|plugin-manifest\.json)\$"
    PARITY_DIFF="$(diff -rq "$LIVE_SKILL_DIR" "$IN_REPO_SKILL_DIR" 2>&1 | grep -vE "$LIVE_ONLY_SCAFFOLD" || true)"
    assert_eq "live authoring copy is byte-identical to the in-repo copy (whole skill tree)" \
        "" "$PARITY_DIFF"
else
    echo "SKIP: live authoring copy not present, parity check skipped: $LIVE_SKILL_DIR"
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
