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
# The whole run is hermetic: 18 throwaway SKILLS_HOMEs, a fixture directory
# that is deliberately never a SKILLS_HOME, 34 throwaway monorepos, the syncs
# invoked from a throwaway cwd, and `gh` shimmed off PATH so nothing reaches the
# network. The live repo is never passed to sync-monorepo.sh or prepare-plugin.sh.
#
# Counts are `grep -oE '^[A-Z_]*(MONOREPO|SKILLS_HOME)[A-Z_]*_FIXTURE=' | sort -u`
# over this file — re-derive them the same way rather than incrementing by hand.
# Two `gh` shims: the ordinary one, and the stdin-draining one defect 11 needs.
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

# The N out of the closing "Sync complete. N skills synced to <dir>" line
# (issue #81). Read this rather than substring-matching a literal "Sync
# complete. 2" — in a two-skill fixture the pre-fix formula (discovered count)
# and the post-fix formula (actually-resolved count) coincidentally agree
# whenever every discovered name resolves, so a bare literal-match assertion
# would pass against the unfixed formula too. Parsing the number out and
# comparing it against something independently derived (a catalogue row count,
# or a fixture where the two formulas are known to diverge) is what actually
# discriminates.
sync_complete_count() {
    sed -n 's/^Sync complete\. \([0-9]*\) skills synced .*/\1/p' <<< "$1"
}

# Counts SKILL catalogue rows in a generated README.md, distinguishing them
# from plugin catalogue rows in the same file. Both are `| [name](path) | ... |`
# table rows, but a skill row's link is `(./name/)` — a single path segment —
# while a plugin row's is `(./plugins/name/)` — two segments. Requiring no
# internal `/` inside the parens is what tells them apart; a plain
# `grep -c '^| \['` would double-count once a plugin table exists in the same
# README (issue #80 fixtures always trigger the demo-plugin auto-build).
skill_catalog_row_count() {
    grep -cE '^\| \[[^]]+\]\(\./[^/]+/\) \|' "$1" 2>/dev/null || true
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

# Issue #80 (--skills resolving to zero real skills must refuse, not publish
# an empty catalogue). Three separate monorepo trees, each pre-seeded with a
# demo-skill/ directory so a first "populate" sync run (no --skills) gives it
# a real, non-empty catalogue — the whole point of these fixtures is proving
# that catalogue survives a subsequent bad --skills call, so each needs its
# own tree: sharing MONOREPO_FIXTURE would let a still-broken guard corrupt
# the state that MONOREPO_FIXTURE's own later assertions depend on.
MONOREPO_SKILLSCOMMA_FIXTURE="$SCRATCH_DIR/monorepo-skillscomma"
MONOREPO_SKILLSBAD_FIXTURE="$SCRATCH_DIR/monorepo-skillsbad"
MONOREPO_SKILLSGOOD_FIXTURE="$SCRATCH_DIR/monorepo-skillsgood"

# A dedicated SKILLS_HOME for the --skills-nosuchskill fixture only (not shared
# with SKILLS_HOME_FIXTURE): its plugin-manifest.json is added *between* the
# populate run and the guard-triggering run (see that section below) so the
# auto-build stage still has real work to do — a manifest published at
# populate time would already be built and drift-free by the second run,
# making "no AUTO-SYNCED line" true whether or not the guard actually fired.
SKILLS_HOME_SKILLSBAD_FIXTURE="$SCRATCH_DIR/skills-home-skillsbad"

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
#   presync-monorepo/presync-local-skill/                SHADOW SKILL.md + CHANGELOG (see below)
#   presync-monorepo/presync-inrepo-skill/                in-repo-source-only; CHANGELOG MISMATCHED (core, negative)
#   presync-monorepo/docs/, build/                        non-skill dirs, must enter neither count
#   presync-monorepo-pass/presync-local-skill/            same shape as above
#   presync-monorepo-pass/presync-inrepo-skill/           same skill; CHANGELOG MATCHES (positive control)
#   presync-monorepo-pass/docs/, build/                   same shape as above
#
# presync-local-skill's monorepo-side directory is deliberately NOT empty: it
# carries its own SKILL.md (a different version, 9.9.9) and its own WRONG
# CHANGELOG.md (STALE-DO-NOT-READ, matching no real version). skill_source_dir()
# is local-first, so a correct implementation resolves to presync-skills-home
# and this fixture never enters the report. A monorepo-side directory with NO
# SKILL.md would not actually exercise that precedence — a monorepo-first
# mutant's own `[[ -f … SKILL.md ]]` test would fail on an empty directory and
# fall through to the same right answer by construction, silently agreeing
# with the bug. The shadow SKILL.md gives the wrong branch something to match:
# a monorepo-first mutant resolves here instead, reads v9.9.9, checks it
# against the STALE CHANGELOG (which matches no version), and presync-local-skill
# flips PASS -> FAIL. Proven by mutation, not asserted from reading the code —
# see the fix-round section of the task report.
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
         "$MONOREPO_SKILLSCOMMA_FIXTURE/demo-skill" \
         "$MONOREPO_SKILLSBAD_FIXTURE/demo-skill" \
         "$MONOREPO_SKILLSGOOD_FIXTURE/demo-skill" \
         "$SKILLS_HOME_SKILLSBAD_FIXTURE/demo-skill" \
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

# Deliberately wrong, deliberately present — see the fixture-block comment
# above. A different version (9.9.9, vs. the real 1.0.0) so a monorepo-first
# resolution is distinguishable from the correct local-first one, paired with
# a CHANGELOG that cannot match ANY version. skill_source_dir() must never
# reach either file for a local-source skill.
PRESYNC_SHADOW_SKILL_MD='---
name: presync-local-skill
description: MUST NOT BE READ — shadows presync-local-skill in the monorepo so a local-first precedence violation in skill_source_dir() is distinguishable, not silently correct by construction.
version: 9.9.9
---

# Presync Local Skill (stale monorepo shadow — must not be read)'

printf '%s\n' "$PRESYNC_SHADOW_SKILL_MD" > "$PRESYNC_MONOREPO_FIXTURE/presync-local-skill/SKILL.md"
printf '%s\n' "$PRESYNC_SHADOW_SKILL_MD" > "$PRESYNC_MONOREPO_PASS_FIXTURE/presync-local-skill/SKILL.md"
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

# Run 7b: the SAME argument against a POPULATED monorepo, which is the half the
# fixture above structurally cannot reach — and the half that was broken.
#
# MONOREPO_ADDCOMMA_FIXTURE is created bare, so `--add ,` there leaves the
# combined list empty and the guard fires. The guard used to test emptiness on
# the UNION, which is empty only when the monorepo is also empty: against a
# populated one, $existing kept the union non-empty, `--add ,` contributed
# nothing, and the run completed at rc=0 with the next-steps banner — the
# operator asked to add a skill, none was added, success reported. Measured
# before the fix: rc=0 populated, rc=1 empty.
#
# The fixture was the root cause, not the guard. The existing assertion looked
# like coverage of `--add ,` while exercising only the case that already worked,
# which is why the bug survived into the commit that fixed its twin in
# validate-pre-sync.sh. A second, populated fixture is the fix; asserting harder
# against the bare one could not have caught it.
MONOREPO_ADDCOMMAPOP_FIXTURE="$SCRATCH_DIR/monorepo-addcomma-populated"
mkdir -p "$MONOREPO_ADDCOMMAPOP_FIXTURE"
ADDCOMMAPOP_SEED_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADDCOMMAPOP_FIXTURE" \
    "$SCRATCH_DIR/addcommapop-seed.stdout" "$SCRATCH_DIR/addcommapop-seed.stderr" \
    --add demo-skill || ADDCOMMAPOP_SEED_RC=$?
ADDCOMMAPOP_README_BEFORE="$(cat "$MONOREPO_ADDCOMMAPOP_FIXTURE/README.md" 2>/dev/null || true)"

ADDCOMMAPOP_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADDCOMMAPOP_FIXTURE" \
    "$SCRATCH_DIR/addcommapop.stdout" "$SCRATCH_DIR/addcommapop.stderr" \
    --add , || ADDCOMMAPOP_RC=$?
ADDCOMMAPOP_STDOUT="$(cat "$SCRATCH_DIR/addcommapop.stdout")"
ADDCOMMAPOP_STDERR="$(cat "$SCRATCH_DIR/addcommapop.stderr")"

# --add and --skills together: they're parsed independently with no mutual
# exclusion in the argument loop, and discover_skills() returns from the
# --add branch without ever reading SKILLS_LIST — but the #80 post-loop guard
# gates on SKILLS_LIST alone. Before the mutual-exclusion check, this
# combination on a monorepo with no existing skill dirs would abort correctly
# but MISDIAGNOSE it: "--skills matched no valid skills ... from: 'anything'",
# naming a flag whose value was never actually consulted. The monorepo
# argument doesn't need to exist — the rejection is at parse time, before any
# directory is ever touched.
ADDSKILLS_STDOUT_LOG="$SCRATCH_DIR/addskills-conflict.stdout"
ADDSKILLS_STDERR_LOG="$SCRATCH_DIR/addskills-conflict.stderr"
ADDSKILLS_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$SCRATCH_DIR/monorepo-addskills-conflict-unused" "$ADDSKILLS_STDOUT_LOG" "$ADDSKILLS_STDERR_LOG" --add nosuchskill --skills anything || ADDSKILLS_RC=$?
ADDSKILLS_STDERR="$(cat "$ADDSKILLS_STDERR_LOG")"

# Runs 7a-7c: issue #80 — a --skills value that resolves to zero real skills
# must refuse rather than silently republish the catalogue. Each of the three
# fixtures below is first "populated" with a genuine sync (no --skills), which
# writes a real, non-empty catalogue row for demo-skill; the populate run's own
# rc/output is not asserted on (MONOREPO_FIXTURE's identical run already covers
# that path) — it exists purely to give the guard-triggering run something to
# protect or, in the positive control, to prove it still works.
SKILLSCOMMA_POPULATE_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_SKILLSCOMMA_FIXTURE" "$SCRATCH_DIR/skillscomma-populate.stdout" "$SCRATCH_DIR/skillscomma-populate.stderr" || SKILLSCOMMA_POPULATE_RC=$?
SKILLSCOMMA_README_BEFORE="$(cat "$MONOREPO_SKILLSCOMMA_FIXTURE/README.md" 2>/dev/null || true)"
SKILLSCOMMA_ROWS_BEFORE="$(skill_catalog_row_count "$MONOREPO_SKILLSCOMMA_FIXTURE/README.md")"

SKILLSCOMMA_STDOUT_LOG="$SCRATCH_DIR/skillscomma.stdout"
SKILLSCOMMA_STDERR_LOG="$SCRATCH_DIR/skillscomma.stderr"
SKILLSCOMMA_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_SKILLSCOMMA_FIXTURE" "$SKILLSCOMMA_STDOUT_LOG" "$SKILLSCOMMA_STDERR_LOG" --skills , || SKILLSCOMMA_RC=$?
SKILLSCOMMA_STDERR="$(cat "$SKILLSCOMMA_STDERR_LOG")"
SKILLSCOMMA_README_AFTER="$(cat "$MONOREPO_SKILLSCOMMA_FIXTURE/README.md" 2>/dev/null || true)"
SKILLSCOMMA_ROWS_AFTER="$(skill_catalog_row_count "$MONOREPO_SKILLSCOMMA_FIXTURE/README.md")"

# SKILLS_HOME_SKILLSBAD_FIXTURE starts with a plain demo-skill and NO
# plugin-manifest.json, so the populate run below cannot build a plugin yet —
# the manifest is added afterwards (see below), between the populate run and
# the guard-triggering one, so the latter is the run that would attempt the
# very first build if the guard did not stop it first.
cat > "$SKILLS_HOME_SKILLSBAD_FIXTURE/demo-skill/SKILL.md" <<'EOF'
---
name: demo-skill
description: Throwaway fixture skill used only by the sync-hygiene harness's --skills-nosuchskill guard-placement assertion.
version: 0.1.0
---

# Demo Skill

Fixture content.
EOF

SKILLSBAD_POPULATE_RC=0
run_sync "$SKILLS_HOME_SKILLSBAD_FIXTURE" "$MONOREPO_SKILLSBAD_FIXTURE" "$SCRATCH_DIR/skillsbad-populate.stdout" "$SCRATCH_DIR/skillsbad-populate.stderr" || SKILLSBAD_POPULATE_RC=$?
SKILLSBAD_README_BEFORE="$(cat "$MONOREPO_SKILLSBAD_FIXTURE/README.md" 2>/dev/null || true)"
SKILLSBAD_ROWS_BEFORE="$(skill_catalog_row_count "$MONOREPO_SKILLSBAD_FIXTURE/README.md")"

# Mutate between the populate run and the guard-triggering run: add the
# manifest now, so the second run is the first one that ever sees it. Without
# the #80 guard, this run's plugin auto-build stage would find no
# plugins/skillsbad-plugin/.claude-plugin on disk yet and attempt a real
# first build (printing "AUTO-SYNCED"), proving the "aborts before auto-build"
# assertion below is not vacuous — a manifest present since populate time
# would already be built and drift-free, making that line absent regardless
# of whether the guard fired at all.
cat > "$SKILLS_HOME_SKILLSBAD_FIXTURE/demo-skill/plugin-manifest.json" <<'EOF'
{
  "name": "skillsbad-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin used only by the sync-hygiene harness's --skills-nosuchskill guard-placement assertion.",
  "skills": [
    {
      "name": "demo-skill",
      "source": "."
    }
  ],
  "commands": []
}
EOF

SKILLSBAD_STDOUT_LOG="$SCRATCH_DIR/skillsbad.stdout"
SKILLSBAD_STDERR_LOG="$SCRATCH_DIR/skillsbad.stderr"
SKILLSBAD_RC=0
run_sync "$SKILLS_HOME_SKILLSBAD_FIXTURE" "$MONOREPO_SKILLSBAD_FIXTURE" "$SKILLSBAD_STDOUT_LOG" "$SKILLSBAD_STDERR_LOG" --skills nosuchskill || SKILLSBAD_RC=$?
SKILLSBAD_STDOUT="$(cat "$SKILLSBAD_STDOUT_LOG")"
SKILLSBAD_STDERR="$(cat "$SKILLSBAD_STDERR_LOG")"
SKILLSBAD_README_AFTER="$(cat "$MONOREPO_SKILLSBAD_FIXTURE/README.md" 2>/dev/null || true)"
SKILLSBAD_ROWS_AFTER="$(skill_catalog_row_count "$MONOREPO_SKILLSBAD_FIXTURE/README.md")"

# Positive control: without this, a guard that refuses every --skills
# invocation (not just the zero-resolving ones) would pass both checks above.
SKILLSGOOD_POPULATE_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_SKILLSGOOD_FIXTURE" "$SCRATCH_DIR/skillsgood-populate.stdout" "$SCRATCH_DIR/skillsgood-populate.stderr" || SKILLSGOOD_POPULATE_RC=$?

# Remove the README the populate run just wrote before the real test run: a
# genuine rewrite is byte-identical to the populate output, so "was the row
# written by THIS run" is not observable from content alone once the file is
# already there. Deleting it first turns the row's mere presence afterwards
# into real proof the guard-triggering run itself performed the write, rather
# than the assertion passing vacuously off populate's leftover file.
rm -f "$MONOREPO_SKILLSGOOD_FIXTURE/README.md"

SKILLSGOOD_STDOUT_LOG="$SCRATCH_DIR/skillsgood.stdout"
SKILLSGOOD_STDERR_LOG="$SCRATCH_DIR/skillsgood.stderr"
SKILLSGOOD_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_SKILLSGOOD_FIXTURE" "$SKILLSGOOD_STDOUT_LOG" "$SKILLSGOOD_STDERR_LOG" --skills demo-skill || SKILLSGOOD_RC=$?
SKILLSGOOD_STDOUT="$(cat "$SKILLSGOOD_STDOUT_LOG")"
SKILLSGOOD_README_AFTER="$(cat "$MONOREPO_SKILLSGOOD_FIXTURE/README.md" 2>/dev/null || true)"

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
assert_contains "the run explains its refusal to continue" \
    "Error: refusing to continue — one or more manifests could not be published." \
    "$BUILDFAIL_STDERR"
# The reason row, not just the headline: this manifest's build was ATTEMPTED and
# failed, so it must appear under "plugin build failed" and not under one of the
# two reasons that describe something else happening.
assert_contains "…naming the manifest under the reason that actually applies" \
    "plugin build failed:        $SKILLS_HOME_BUILDFAIL_FIXTURE/broken-plugin/plugin-manifest.json" \
    "$BUILDFAIL_STDERR"
assert_not_contains "…and not miscategorised as an unreadable manifest" \
    "skills[] could not be read:" "$BUILDFAIL_STDERR"
assert_contains "…with the real run's wording about what is already on disk" \
    "Skills synced before this point are already written" "$BUILDFAIL_STDERR"

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

# …and that it has CONTENTS, not merely existence. The marketplace builder is
# the one list-driven loop reached through a process substitution rather than a
# here-string, and it was the last one converted to fd 3. Botching that
# conversion — `3< <(…)` back to `< <(…)`, the exact failure mode the
# install-all and CHANGELOG-inventory loops already have controls for — writes
#     "plugins": [
#     ]
# and exits 0: the marketplace catalogue silently emptied, which is #80's shape
# on the marketplace side. The assert_file_exists above stays GREEN through it,
# because the file is written, just empty; the README's plugin row is built by a
# different loop and survives, so nothing else notices either. Measured: that
# mutant passed all 279 assertions at rc=0 before this line existed. Bash does
# print "3: Bad file descriptor" to stderr, but no assertion reads that stream
# for this run.
#
# Pairs with the assert_file_exists above rather than relying on the `|| true`:
# on a missing file the substitution yields an empty haystack, and
# assert_contains on an empty haystack FAILS (`"" == *needle*` is false), so
# this is red either way. Checked directly rather than assumed — the vacuous-
# `|| true` shape bit this harness once already, but it bites assert_not_contains,
# not assert_contains.
assert_contains "…listing the plugin it built, not an empty plugins[]" \
    '"name": "legacy-sync-plugin"' \
    "$(cat "$MONOREPO_LEGACY_FIXTURE/.claude-plugin/marketplace.json" 2>/dev/null || true)"

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

# Issue #81's blank-line guards (`[[ -z "$NAME" ]] && continue`), added to
# every here-string loop converted in that fix: `<<< ""` still feeds one
# blank line to `read`, so an empty $SKILLS_TO_SYNC reaches the main sync
# loop, the install-all loop and the skill-inventory loop with SKILL_NAME=""
# unless each one skips it. The main loop's case is the loud one — an empty
# name still resolves nothing and prints its own "no SKILL.md" ERROR at rc 0
# (verified reachable: reverting just the five guards, keeping the
# herestring conversion, and probing this exact empty-monorepo shape in
# isolation reproduces "ERROR: no SKILL.md in …/ or …/, skipping"). Nothing
# in this harness asserted against it before — the pre-existing rc-0
# assertion above survives regardless, since the blank iteration still
# `continue`s either way.
assert_not_contains "a monorepo with no skills prints no ERROR line (the #81 blank-line guards, not just the rc)" \
    "ERROR:" "$EMPTY_STDOUT"

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

# --- The same argument against a POPULATED monorepo (run 7b). The two
# assertions above cannot reach this: their fixture is bare, so the union is
# empty and the old union-based guard fired for the wrong reason. Verified red
# against that guard — rc=0, "Sync complete. 1 skills synced", the next-steps
# banner, and no error at all, because $existing kept the union non-empty while
# `--add ,` contributed nothing. The operator asked to add a skill, none was
# added, and the run reported success. ---
assert_eq "control: the populated fixture's seed --add really did publish a catalogue" \
    "0" "$ADDCOMMAPOP_SEED_RC"
assert_eq "…with a row to protect" \
    "1" "$(skill_catalog_row_count "$MONOREPO_ADDCOMMAPOP_FIXTURE/README.md")"
assert_eq "--add , against a POPULATED monorepo refuses too, not just an empty one" \
    "1" "$ADDCOMMAPOP_RC"
assert_contains "…naming the offending argument there as well" \
    "Error: --add produced no skill names from: ','" "$ADDCOMMAPOP_STDERR"
assert_not_contains "…and never claiming the sync completed" \
    "Sync complete." "$ADDCOMMAPOP_STDOUT"
assert_eq "…leaving the published catalogue byte-identical" \
    "$ADDCOMMAPOP_README_BEFORE" \
    "$(cat "$MONOREPO_ADDCOMMAPOP_FIXTURE/README.md" 2>/dev/null || true)"

# --- `--add ""` is the same silent no-op through a shorter argument. The guard
# above lived inside `if [[ -n "$ADD_SKILL" ]]`, so an EMPTY value never reached
# it — the branch was skipped wholesale and the run came out byte-identical to
# one with no --add at all. Measured before the fix: rc=0, "Sync complete. 1
# skills synced", exactly matching a plain discovery sync on the same fixture.
# The operator passed --add, nothing was added, success reported.
#
# Gating on whether the flag was PASSED ($ADD_GIVEN) rather than on whether its
# value is non-empty is what closes it; the existing add_split guard then prints
# the message it already had. Reuses the populated fixture above because a
# refusing run writes nothing, so it cannot disturb those assertions. ---
ADDEMPTY_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_ADDCOMMAPOP_FIXTURE" \
    "$SCRATCH_DIR/addempty.stdout" "$SCRATCH_DIR/addempty.stderr" \
    --add "" || ADDEMPTY_RC=$?
ADDEMPTY_STDOUT="$(cat "$SCRATCH_DIR/addempty.stdout")"
assert_eq "--add with an EMPTY value refuses too, not just --add ," \
    "1" "$ADDEMPTY_RC"
assert_contains "…naming the empty argument" \
    "Error: --add produced no skill names from: ''" \
    "$(cat "$SCRATCH_DIR/addempty.stderr")"
assert_not_contains "…and never reporting a completed sync" \
    "Sync complete." "$ADDEMPTY_STDOUT"
assert_eq "…with the catalogue still untouched" \
    "$ADDCOMMAPOP_README_BEFORE" \
    "$(cat "$MONOREPO_ADDCOMMAPOP_FIXTURE/README.md" 2>/dev/null || true)"

# ============================================================
# --add and --skills together must be rejected, with the right diagnosis
# ============================================================
assert_eq "--add and --skills together are rejected at parse time" \
    "1" "$ADDSKILLS_RC"
assert_contains "...names the actual conflict" \
    "Error: --add and --skills are mutually exclusive" "$ADDSKILLS_STDERR"
assert_not_contains "...does not misattribute the failure to --skills, whose value --add's presence means was never consulted" \
    "matched no valid skills" "$ADDSKILLS_STDERR"

# ============================================================
# Issue #80 — a --skills value resolving to zero real skills must refuse
# rather than publish an empty (or silently unchanged-but-misleading) catalog
# ============================================================
#
# Two entry points into the same defect, differing only in how quiet they
# were: `--skills ,` resolves to zero names before the sync loop ever runs
# (caught in discover_skills() itself); `--skills nosuchskill` resolves to one
# name that then fails to find a SKILL.md inside the loop (caught by the
# post-loop SKILLS_RESOLVED_COUNT guard). Both must leave the existing
# catalogue untouched — the row count is the assertion, not the file's mere
# presence, since the destructive version of this bug also leaves a file
# behind (just an emptied one).

# Sanity: the populate step must have actually succeeded and produced a real,
# non-empty catalogue, or "the row count didn't change" would be trivially
# true of two absent files and prove nothing.
assert_eq "--skills , fixture: the populate run itself succeeded" \
    "0" "$SKILLSCOMMA_POPULATE_RC"
assert_eq "--skills , fixture: populate produced exactly one catalogue row" \
    "1" "$SKILLSCOMMA_ROWS_BEFORE"
assert_eq "--skills nosuchskill fixture: the populate run itself succeeded" \
    "0" "$SKILLSBAD_POPULATE_RC"
assert_eq "--skills nosuchskill fixture: populate produced exactly one catalogue row" \
    "1" "$SKILLSBAD_ROWS_BEFORE"
assert_eq "--skills demo-skill fixture: the populate run itself succeeded" \
    "0" "$SKILLSGOOD_POPULATE_RC"

assert_eq "--skills , fails with a deliberate, explained exit" \
    "1" "$SKILLSCOMMA_RC"
assert_contains "--skills , explains itself on stderr, naming the offending argument" \
    "Error: --skills produced no skill names from: ','" "$SKILLSCOMMA_STDERR"
assert_eq "--skills , leaves the catalogue row count unchanged" \
    "$SKILLSCOMMA_ROWS_BEFORE" "$SKILLSCOMMA_ROWS_AFTER"
assert_eq "--skills , leaves the README byte-for-byte unchanged" \
    "$SKILLSCOMMA_README_BEFORE" "$SKILLSCOMMA_README_AFTER"

assert_eq "--skills nosuchskill fails with a deliberate, explained exit" \
    "1" "$SKILLSBAD_RC"
assert_contains "--skills nosuchskill explains itself on stderr, naming the offending argument" \
    "Error: --skills matched no valid skills (no SKILL.md found) from: 'nosuchskill'" "$SKILLSBAD_STDERR"
assert_eq "--skills nosuchskill leaves the catalogue row count unchanged" \
    "$SKILLSBAD_ROWS_BEFORE" "$SKILLSBAD_ROWS_AFTER"
assert_eq "--skills nosuchskill leaves the README byte-for-byte unchanged" \
    "$SKILLSBAD_README_BEFORE" "$SKILLSBAD_README_AFTER"

# Placement proof: the guard is sited before the plugin auto-build stage, not
# just before the literal README/CHANGELOG write, so a doomed --skills call
# cannot leave plugins/ mutated on disk beside a catalogue that no longer
# describes it (see task report for the full reasoning — this mirrors #77's
# own "exit before anything is written" contract). The manifest added between
# the populate and guard-triggering runs above means this run is genuinely the
# first one that would ever attempt to build skillsbad-plugin, so "no
# AUTO-SYNCED line" is proof the guard fired before reaching that stage, not
# an accident of the plugin already being built and drift-free.
assert_not_contains "--skills nosuchskill aborts before the plugin auto-build stage" \
    "AUTO-SYNCED" "$SKILLSBAD_STDOUT"

# Positive control: --skills naming a real skill still succeeds and is synced.
assert_eq "positive control: --skills demo-skill exits 0" \
    "0" "$SKILLSGOOD_RC"
assert_line_present "positive control: --skills demo-skill names it in the synced list" \
    "demo-skill" "$(synced_names "$SKILLSGOOD_STDOUT")"
# The README is removed between the populate run and this one (below, at the
# run-7c call site) so a row's presence here is proof this run wrote it, not
# a leftover from populate — a byte-identical rewrite is otherwise
# content-indistinguishable from "the run never touched the file".
assert_contains "positive control: --skills demo-skill's catalogue row is present after the run" \
    "[demo-skill](./demo-skill/)" "$SKILLSGOOD_README_AFTER"

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

# stdout and stderr captured to separate log files, same shape as run_sync()
# above — a bare command substitution captures stdout only, which is why the
# SKIP line item 4 added below was invisible to every assertion here despite
# printing correctly: it went straight through to the harness's own stderr
# instead of into a variable anything could assert against.
run_presync() {
    local skills_home="$1" monorepo="$2" stdout_log="$3" stderr_log="$4"
    shift 4
    local rc=0
    (
        cd "$RUN_CWD"
        SKILLS_HOME="$skills_home" "$PRESYNC_SCRIPT" "$@" "$monorepo"
    ) >"$stdout_log" 2>"$stderr_log" || rc=$?
    return "$rc"
}

PRESYNC_STDOUT_LOG="$SCRATCH_DIR/presync.stdout"
PRESYNC_STDERR_LOG="$SCRATCH_DIR/presync.stderr"
PRESYNC_RC=0
run_presync "$PRESYNC_SKILLS_HOME_FIXTURE" "$PRESYNC_MONOREPO_FIXTURE" "$PRESYNC_STDOUT_LOG" "$PRESYNC_STDERR_LOG" || PRESYNC_RC=$?
PRESYNC_STDOUT="$(cat "$PRESYNC_STDOUT_LOG")"
PRESYNC_STDERR="$(cat "$PRESYNC_STDERR_LOG")"

PRESYNC_PASS_STDOUT_LOG="$SCRATCH_DIR/presync-pass.stdout"
PRESYNC_PASS_STDERR_LOG="$SCRATCH_DIR/presync-pass.stderr"
PRESYNC_PASS_RC=0
run_presync "$PRESYNC_SKILLS_HOME_FIXTURE" "$PRESYNC_MONOREPO_PASS_FIXTURE" "$PRESYNC_PASS_STDOUT_LOG" "$PRESYNC_PASS_STDERR_LOG" || PRESYNC_PASS_RC=$?
PRESYNC_PASS_STDOUT="$(cat "$PRESYNC_PASS_STDOUT_LOG")"
PRESYNC_PASS_STDERR="$(cat "$PRESYNC_PASS_STDERR_LOG")"

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

# --- The stderr SKIP line added alongside item 4's fix: a non-skill directory
# is announced, not silently dropped, matching sync-monorepo.sh's
# filter_skill_candidates() message shape exactly (same string as the
# assertions against $SYNC_STDERR above — the two are distinguishable only by
# which producer's captured stream the assertion reads, never by content; a
# future assertion that merged the two logs before grepping could not tell
# them apart). Verified by hand: reverting the printf in a scratch copy leaves
# $PRESYNC_STDERR empty against this fixture, and this pair of assertions goes
# red. ---
assert_contains "the presync run announces docs/ as skipped on stderr" \
    "  SKIP (not a skill: no SKILL.md)  docs" "$PRESYNC_STDERR"
assert_contains "…and build/ too" \
    "  SKIP (not a skill: no SKILL.md)  build" "$PRESYNC_STDERR"
# Positive control: a real skill must never be named in a SKIP line. Without
# this, a regression that announced every name (including real skills) as
# skipped would still satisfy the two assertions above. Verified by hand:
# making the skip unconditional (skill_source_dir() always empty) makes both
# real skill names appear in $PRESYNC_STDERR and flips this pair red.
assert_not_contains "…a real skill (presync-local-skill) is never named in a SKIP line" \
    "SKIP (not a skill: no SKILL.md)  presync-local-skill" "$PRESYNC_STDERR"
assert_not_contains "…nor is the other real skill (presync-inrepo-skill)" \
    "SKIP (not a skill: no SKILL.md)  presync-inrepo-skill" "$PRESYNC_STDERR"

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

# ------------------------------------------------------------------
# Issue #81's SIXTH site — validate-pre-sync.sh's own skill loop
# ------------------------------------------------------------------
#
# #81 is described everywhere in this file as "five sites in sync-monorepo.sh",
# and it is six: Task 3 folded the same conversion into validate-pre-sync.sh's
# loop ("fixing it here avoids two tasks editing the same loop"), and Task 5
# then built the space-name fixtures against sync-monorepo.sh's five. The fix
# crossed a file boundary; the coverage stayed with the task that owned the
# issue. Every earlier N-1-of-N on this branch was WITHIN one file — this is
# the first that crossed one, which is why six review passes went by it.
#
# Measured, not inferred: reverting ONLY validate-pre-sync.sh's loop to
# `for SKILL_NAME in $SKILLS` (leaving sync-monorepo.sh at HEAD) left this
# harness at 248 PASS / 0 FAIL. Every space-named fixture above is sync-side —
# the presync fixtures hold only presync-local-skill, presync-inrepo-skill,
# docs and build, none of them IFS-splittable — so nothing here could tell
# line-wise iteration from word-splitting for this script.
#
# A THIRD presync monorepo rather than space-named skills added to the two
# above: those fixtures' Total/Pass/Fail assertions are load-bearing for #78
# and pin exact counts, so growing them would mean rewriting #78's evidence to
# test #81's. Same reasoning that gave #78 two monorepos instead of one.
#
# Note this is the word-splitting half only. The fd-3 half of the same loop
# (defect 11) is NOT observable here: the body's only children are grep, sed
# and head, all of which read a file or an internal pipe rather than the loop's
# stdin, so no child can eat the list even when it is on stdin. The fd-3
# conversion there is defence in depth, and the f1 mutant reflects that
# honestly by going red only on the sync side.
PRESYNC_MONOREPO_SPACE_FIXTURE="$SCRATCH_DIR/presync-monorepo-space"

# Three skills, in-repo-source-only (no SKILLS_HOME counterpart), so this also
# reaches skill_source_dir()'s in-repo branch with a space-named skill:
#   "my presync skill"     v1.0.0, CHANGELOG lists only 9.9.9  -> must FAIL
#   "my passing skill"     v1.0.0, CHANGELOG lists 1.0.0       -> must PASS
#   presync-plain-skill    ordinary name, matching CHANGELOG   -> control
#
# One space-named skill on each side of the report, because "examined" has two
# possible correct outcomes and a fix that reached only one of the two lists
# would otherwise look complete. The failing one also makes the run's EXIT
# STATUS a discriminator: word-split, its three fragments each fail
# skill_source_dir(), it never enters TOTAL, and the run prints "Safe to sync"
# and exits 0 over a genuinely broken skill — #78's defect shape reached
# through #81's bug.
mkdir -p "$PRESYNC_MONOREPO_SPACE_FIXTURE/my presync skill" \
         "$PRESYNC_MONOREPO_SPACE_FIXTURE/my passing skill" \
         "$PRESYNC_MONOREPO_SPACE_FIXTURE/presync-plain-skill"

cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/my presync skill/SKILL.md" <<'EOF'
---
name: my presync skill
description: Throwaway fixture — space-named, CHANGELOG deliberately mismatched (#81, sixth site).
version: 1.0.0
---

# My Presync Skill
EOF
cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/my presync skill/CHANGELOG.md" <<'EOF'
# Changelog

## [9.9.9] - 2026-01-01

Deliberately not 1.0.0 — this skill must be REPORTED as failing, not dropped.
EOF

cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/my passing skill/SKILL.md" <<'EOF'
---
name: my passing skill
description: Throwaway fixture — space-named, CHANGELOG matches (#81, sixth site).
version: 1.0.0
---

# My Passing Skill
EOF
cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/my passing skill/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Matches SKILL.md — this skill must reach the PASS list under its whole name.
EOF

cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/presync-plain-skill/SKILL.md" <<'EOF'
---
name: presync-plain-skill
description: Throwaway fixture with an ordinary name — the control that survives word-splitting either way (#81, sixth site).
version: 1.0.0
---

# Presync Plain Skill
EOF
cat > "$PRESYNC_MONOREPO_SPACE_FIXTURE/presync-plain-skill/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Matches SKILL.md.
EOF

PRESYNC_SPACE_STDOUT_LOG="$SCRATCH_DIR/presync-space.stdout"
PRESYNC_SPACE_STDERR_LOG="$SCRATCH_DIR/presync-space.stderr"
PRESYNC_SPACE_RC=0
run_presync "$PRESYNC_SKILLS_HOME_FIXTURE" "$PRESYNC_MONOREPO_SPACE_FIXTURE" \
    "$PRESYNC_SPACE_STDOUT_LOG" "$PRESYNC_SPACE_STDERR_LOG" || PRESYNC_SPACE_RC=$?
PRESYNC_SPACE_STDOUT="$(cat "$PRESYNC_SPACE_STDOUT_LOG")"
PRESYNC_SPACE_STDERR="$(cat "$PRESYNC_SPACE_STDERR_LOG")"

# --- Assertions. Verified red against a scratch build with ONLY
# validate-pre-sync.sh's loop reverted to `for SKILL_NAME in $SKILLS` and
# sync-monorepo.sh left at HEAD: Total drops 3 -> 1, Pass 2 -> 1, Fail 1 -> 0,
# the run exits 0 instead of 1, and stderr fills with "SKIP (not a skill: no
# SKILL.md)" lines for the fragments "my", "presync", "passing" and "skill". ---
assert_eq "presync: a space-named skill with a mismatched CHANGELOG makes the run exit 1" \
    "1" "$PRESYNC_SPACE_RC"
assert_eq "…all three skills are examined, not just the one whose name survives word-splitting" \
    "3" "$(presync_total "$PRESYNC_SPACE_STDOUT")"
assert_eq "…Pass is the plain skill plus the passing space-named one" \
    "2" "$(presync_pass "$PRESYNC_SPACE_STDOUT")"
assert_eq "…Fail is exactly the mismatched space-named skill" \
    "1" "$(presync_fail "$PRESYNC_SPACE_STDOUT")"

# Whole-line matches on the report rows: a substring check for "my presync
# skill" would also be satisfied by a fragment line, which is the thing under
# test. The FAIL row carries both versions, so it also proves the skill was
# actually READ (its v1.0.0 and its CHANGELOG's 9.9.9) rather than merely named.
assert_line_present "…the space-named failure is reported under its whole name, with both versions" \
    "FAIL  my presync skill — SKILL.md says v1.0.0 but CHANGELOG latest is v9.9.9" \
    "$PRESYNC_SPACE_STDOUT"
assert_line_present "…and the space-named PASS reaches the pass list under its whole name" \
    "PASS  my passing skill v1.0.0" "$PRESYNC_SPACE_STDOUT"
assert_line_present "positive control: the ordinary-named skill is unaffected either way" \
    "PASS  presync-plain-skill v1.0.0" "$PRESYNC_SPACE_STDOUT"

# The fragments must not appear anywhere, on either stream. Under the unquoted
# form each one is announced as "SKIP (not a skill: no SKILL.md)" on stderr —
# the report stays superficially tidy while the skill vanishes, so stderr is
# where the bug is loudest and is asserted directly.
for _frag in my presync passing skill; do
    assert_line_absent "…no \"$_frag\" fragment was skipped as a non-skill" \
        "  SKIP (not a skill: no SKILL.md)  $_frag" "$PRESYNC_SPACE_STDERR"
done
assert_not_contains "…and the run never claims it is safe to sync over a failing skill" \
    "Safe to sync" "$PRESYNC_SPACE_STDOUT"

# ============================================================
# Issue #81 — unquoted iteration IFS-splits any skill/plugin name containing
# a space, and the closing summary reported the discovered count rather than
# what actually resolved and synced
# ============================================================
#
# filter_skill_candidates() correctly accepts a directory named "my skill" —
# it has a valid SKILL.md — and prints it as ONE line. Five separate consumers
# of that line then re-split it on whitespace via an unquoted `for X in $LIST`:
# the main sync loop, the manifest-skill-names check inside the auto-build
# stage's reversion guard, the published-plugin catalogue loop, the
# install-all command builder, and the CHANGELOG skill-inventory builder. All
# five are now `while IFS= read -r … done <<< "$LIST"`.
#
# "Five" counts sync-monorepo.sh only. There is a SIXTH site in
# validate-pre-sync.sh, converted by the same issue but in a different task, and
# the fixtures below never covered it — see defect 17 in the header and the
# presync-space section above. Do not read "all five" here as "all of #81".
#
# The closing "Sync
# complete. N skills synced" line is also fixed: it read SKILL_COUNT
# (discovered) rather than SKILLS_RESOLVED_COUNT (actually resolved), so a
# name that failed to resolve was still counted as synced.
#
# Two fixture families, because the two scenarios need opposite outcomes for
# a same-shaped skill: SPACE_FIXTURE needs "my skill" to resolve and sync
# cleanly (proving the ordinary path is not broken by the space); SPACE_PLUGIN
# FIXTURE needs it refused by the reversion guard (proving the manifest-skill
# loop still recognises a refused name that contains a space). They cannot
# share a monorepo.

SKILLS_HOME_SPACE_FIXTURE="$SCRATCH_DIR/skills-home-space"
MONOREPO_SPACE_FIXTURE="$SCRATCH_DIR/monorepo-space"
SKILLS_HOME_SPACE_PLUGIN_FIXTURE="$SCRATCH_DIR/skills-home-space-plugin"
MONOREPO_SPACE_PLUGIN_FIXTURE="$SCRATCH_DIR/monorepo-space-plugin"
MONOREPO_MIXEDSKILLS_FIXTURE="$SCRATCH_DIR/monorepo-mixedskills"

mkdir -p "$SKILLS_HOME_SPACE_FIXTURE/my skill/scripts" \
         "$SKILLS_HOME_SPACE_FIXTURE/space-plain-skill" \
         "$MONOREPO_SPACE_FIXTURE/my skill" \
         "$MONOREPO_SPACE_FIXTURE/space-plain-skill" \
         "$MONOREPO_SPACE_FIXTURE/plugins/my plugin/.claude-plugin" \
         "$SKILLS_HOME_SPACE_PLUGIN_FIXTURE/my skill" \
         "$MONOREPO_SPACE_PLUGIN_FIXTURE/my skill" \
         "$MONOREPO_MIXEDSKILLS_FIXTURE"

cat > "$SKILLS_HOME_SPACE_FIXTURE/my skill/SKILL.md" <<'EOF'
---
name: my skill
description: Throwaway fixture skill in a directory named with a space, guarding sync-monorepo.sh's unquoted iteration sites against IFS word-splitting (#81).
version: 1.0.0
---

# My Skill

Fixture content.
EOF

# Proves the space-named skill's content is actually copied, not merely
# counted — a marker file distinct from SKILL.md, so the assertion below
# cannot be satisfied by the SKILL.md copy alone.
echo "SPACE-FIXTURE-SCRIPT-MARKER" > "$SKILLS_HOME_SPACE_FIXTURE/my skill/scripts/marker.sh"

cat > "$SKILLS_HOME_SPACE_FIXTURE/space-plain-skill/SKILL.md" <<'EOF'
---
name: space-plain-skill
description: Throwaway fixture skill with an ordinary name, synced alongside "my skill" as the positive control for issue #81.
version: 1.0.0
---

# Space Plain Skill

Fixture content.
EOF

# An already-published plugin whose directory (and manifest `name`) contains a
# space — seeded directly rather than through prepare-plugin.sh, since the
# PLUGINS_TO_LIST catalogue loop only reads what is already on disk under
# plugins/. Guards `for PLUGIN_NAME in $PLUGINS_TO_LIST`: word-split into "my"
# and "plugin", plugins/my/.claude-plugin/plugin.json and
# plugins/plugin/.claude-plugin/plugin.json both resolve to nothing, and the
# plugin silently drops out of PLUGIN_COUNT and the catalogue table with no
# error at all.
cat > "$MONOREPO_SPACE_FIXTURE/plugins/my plugin/.claude-plugin/plugin.json" <<'EOF'
{
  "name": "my plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin with a space in its name, guarding the PLUGINS_TO_LIST catalogue loop (#81)."
}
EOF

# --- The reversion-guard-in-plugin fixture: a plugin manifest whose sole
# skill has a space in its name, and IS refused. A stale local source (v1.0.0)
# alongside a newer in-repo copy (v2.0.0, below) forces the same reversion
# guard the main loop already exercises, but reached this time through the
# auto-build stage's own manifest-skill-names read.
cat > "$SKILLS_HOME_SPACE_PLUGIN_FIXTURE/my skill/SKILL.md" <<'EOF'
---
name: my skill
description: Throwaway fixture skill — stale local source, refused by the reversion guard (#81's manifest-skill-names loop).
version: 1.0.0
---

# My Skill (stale local source)

Fixture content.
EOF

cat > "$SKILLS_HOME_SPACE_PLUGIN_FIXTURE/my skill/plugin-manifest.json" <<'EOF'
{
  "name": "space-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin whose sole skill has a space in its name.",
  "skills": [
    {
      "name": "my skill",
      "source": "."
    }
  ],
  "commands": []
}
EOF

# The monorepo's own copy is NEWER, so the reversion guard refuses to sync
# "my skill" forward from the stale local source above.
cat > "$MONOREPO_SPACE_PLUGIN_FIXTURE/my skill/SKILL.md" <<'EOF'
---
name: my skill
description: Throwaway fixture skill — the in-repo copy, newer than the local source, so the reversion guard must refuse to overwrite it.
version: 2.0.0
---

# My Skill (in-repo, newer)

Fixture content.
EOF

SPACE_STDOUT_LOG="$SCRATCH_DIR/space.stdout"
SPACE_STDERR_LOG="$SCRATCH_DIR/space.stderr"
SPACE_RC=0
run_sync "$SKILLS_HOME_SPACE_FIXTURE" "$MONOREPO_SPACE_FIXTURE" "$SPACE_STDOUT_LOG" "$SPACE_STDERR_LOG" || SPACE_RC=$?
SPACE_STDOUT="$(cat "$SPACE_STDOUT_LOG")"

SPACE_PLUGIN_STDOUT_LOG="$SCRATCH_DIR/space-plugin.stdout"
SPACE_PLUGIN_STDERR_LOG="$SCRATCH_DIR/space-plugin.stderr"
SPACE_PLUGIN_RC=0
run_sync "$SKILLS_HOME_SPACE_PLUGIN_FIXTURE" "$MONOREPO_SPACE_PLUGIN_FIXTURE" "$SPACE_PLUGIN_STDOUT_LOG" "$SPACE_PLUGIN_STDERR_LOG" || SPACE_PLUGIN_RC=$?
SPACE_PLUGIN_STDOUT="$(cat "$SPACE_PLUGIN_STDOUT_LOG")"

# --- The arithmetic-only fixture: a --skills value with one real name and one
# that resolves to nothing, no spaces anywhere. Isolates the summary-count fix
# from the word-splitting fix — in the space fixture above, once the main
# loop is fixed, SKILL_COUNT and SKILLS_RESOLVED_COUNT happen to be numerically
# equal (every discovered, filtered name resolves), so that fixture alone
# cannot tell "uses SKILLS_RESOLVED_COUNT" apart from "still uses SKILL_COUNT".
# This one can: SKILL_COUNT is 2 either way, but only one of the two names
# ever resolves.
MIXEDSKILLS_RC=0
run_sync "$SKILLS_HOME_FIXTURE" "$MONOREPO_MIXEDSKILLS_FIXTURE" \
    "$SCRATCH_DIR/mixedskills.stdout" "$SCRATCH_DIR/mixedskills.stderr" \
    --skills demo-skill,mixedskills-nosuchskill || MIXEDSKILLS_RC=$?
MIXEDSKILLS_STDOUT="$(cat "$SCRATCH_DIR/mixedskills.stdout")"

# --- Assertions: main sync loop + honest summary (site 1/5, plus the
# arithmetic fix). Verified by hand against a scratch revert of the main loop
# alone: SKILLS_TO_SYNC still lists "my skill" and "space-plain-skill" as two
# correct lines (discovery is unaffected — the bug is purely in consumption),
# but the unquoted `for` re-splits them into "my", "skill",
# "space-plain-skill"; "my" and "skill" each print a "no SKILL.md" ERROR and
# are never counted into SKILLS_RESOLVED_COUNT or given a catalogue row, while
# "space-plain-skill" still resolves normally. ---
assert_eq "space-named-skill sync exits 0 (both skills resolve and sync cleanly)" \
    "0" "$SPACE_RC"

SPACE_SYNCED_NAMES="$(synced_names "$SPACE_STDOUT")"
assert_line_present "…\"my skill\" enters the discovered list as one name (discovery was never the bug)" \
    "my skill" "$SPACE_SYNCED_NAMES"
assert_line_present "…the ordinary-named sibling is listed too" \
    "space-plain-skill" "$SPACE_SYNCED_NAMES"

assert_not_contains "no ERROR line anywhere in the run" "ERROR:" "$SPACE_STDOUT"

assert_file_exists "the space-named skill's SKILL.md was actually written to disk" \
    "$MONOREPO_SPACE_FIXTURE/my skill/SKILL.md"
assert_file_exists "…and its scripts/ directory, proving copy_dir() received the real (unsplit) source path" \
    "$MONOREPO_SPACE_FIXTURE/my skill/scripts/marker.sh"
assert_eq "…with the right content, not an empty or wrong file" \
    "SPACE-FIXTURE-SCRIPT-MARKER" "$(cat "$MONOREPO_SPACE_FIXTURE/my skill/scripts/marker.sh" 2>/dev/null || true)"

SPACE_ROW_COUNT="$(skill_catalog_row_count "$MONOREPO_SPACE_FIXTURE/README.md")"
assert_eq "the catalogue has exactly 2 skill rows — \"my\"/\"skill\" fragments never got their own wrong rows" \
    "2" "$SPACE_ROW_COUNT"
SPACE_README="$(cat "$MONOREPO_SPACE_FIXTURE/README.md" 2>/dev/null || true)"
assert_contains "…the space-named skill's own row, with the un-split name" \
    "| [my skill](./my skill/) |" "$SPACE_README"
assert_contains "…the ordinary-named skill's row is unaffected" \
    "| [space-plain-skill](./space-plain-skill/) |" "$SPACE_README"

SPACE_SUMMARY_COUNT="$(sync_complete_count "$SPACE_STDOUT")"
assert_eq "the printed summary count is the full 2 (#81 core: not the false count a half-conversion would report)" \
    "2" "$SPACE_SUMMARY_COUNT"
assert_eq "…and agrees with the catalogue row count actually written" \
    "$SPACE_ROW_COUNT" "$SPACE_SUMMARY_COUNT"

# --- Assertion: install-all commands (site 4/5). Independent of site 1 — this
# loop reads $SKILLS_TO_SYNC directly, which is unaffected by the main loop's
# own bug. Verified by hand against a scratch revert of this loop alone: the
# correct single line below is replaced by two broken fragment lines ("cp -r
# …/my ~/.claude/skills/my" and "cp -r …/skill ~/.claude/skills/skill"). ---
assert_line_present "install-all commands contain the one correct cp -r line for the space-named skill" \
    "cp -r /tmp/claude-code-skills/my skill ~/.claude/skills/my skill" "$SPACE_README"
assert_line_absent "…and not the broken first-word-only fragment" \
    "cp -r /tmp/claude-code-skills/my ~/.claude/skills/my" "$SPACE_README"
assert_line_absent "…nor the broken second-word-only fragment" \
    "cp -r /tmp/claude-code-skills/skill ~/.claude/skills/skill" "$SPACE_README"

# --- Assertion: CHANGELOG skill inventory (site 5/5). Also independent of
# site 1. Verified by hand against a scratch revert of this loop alone: both
# "my" and "skill" fail skill_source_dir() individually, so the space-named
# skill's inventory line is silently omitted (space-plain-skill's still
# appears — its own name is a single token either way). ---
SPACE_CHANGELOG="$(cat "$MONOREPO_SPACE_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"
assert_contains "the CHANGELOG skill inventory carries the space-named skill's own entry" \
    "- \`my skill\` v1.0.0" "$SPACE_CHANGELOG"

# --- Assertion: published-plugin catalogue (site 3/5). Verified by hand
# against a scratch revert of this loop alone: PLUGIN_COUNT stays 0 (the
# split "my"/"plugin" fragments each fail the plugin.json existence check),
# the "## Plugins" section never renders, and "my plugin" is invisible in the
# generated README with no error at all. ---
assert_contains "the space-named already-published plugin keeps its catalogue row" \
    "| [my plugin](./plugins/my plugin/) |" "$SPACE_README"

# --- Assertion: manifest-skill-names loop inside the reversion guard (site
# 2/5). Verified by hand against a scratch revert of this loop alone:
# skill_refused("my") and skill_refused("skill") are each checked instead of
# skill_refused("my skill"), neither matches, the auto-build stage's own SKIP
# line never prints, and the plugin is auto-built from the stale local source
# the reversion guard exists to protect against — "AUTO-SYNCED
# plugins/space-plugin/" appears instead.
#
# assert_line_present with the FULL exact line, not assert_contains on a
# prefix: the (already-safe, glob-based) plugin RESYNC stage further down
# prints its own, differently-worded "SKIP (reversion guard)
# plugins/space-plugin resync — …" line whenever plugins/space-plugin/
# already exists on disk — which, under a reverted site 2, it now wrongly
# does, because the auto-build stage just created it. A substring match on
# "SKIP (reversion guard)  plugins/space-plugin" is a prefix of BOTH lines and
# is satisfied by the resync stage's unrelated, correct detection even while
# the auto-build stage's own check (the thing actually under test) stayed
# broken — caught by hand: the bare assert_contains form passed against the
# site-2-reverted variant for exactly this reason before being tightened here. ---
assert_eq "space-plugin reversion-guard run exits 3 (a skill was refused)" \
    "3" "$SPACE_PLUGIN_RC"
assert_line_present "…the refused skill is named correctly, whole, on the top-level REFUSED trailer" \
    "  - my skill" "$SPACE_PLUGIN_STDOUT"
assert_line_present "the plugin auto-build stage's OWN reversion-guard check skips the refused space-named skill's plugin" \
    "  SKIP (reversion guard)  plugins/space-plugin  —  stale local source for: my skill" "$SPACE_PLUGIN_STDOUT"
assert_not_contains "the refused plugin is not built anyway" \
    "AUTO-SYNCED  plugins/space-plugin/" "$SPACE_PLUGIN_STDOUT"

# --- Assertion: review round 3's CRITICAL finding, on the same refusal
# fixture. A refused skill still keeps its catalogue row — CATALOG_ROWS is
# built from the in-repo metadata BEFORE the reversion guard's `continue`,
# deliberately, so the root README stays populated for a skill that just
# wasn't recopied this run. Round 2 wrongly pointed the README's
# {{SKILL_COUNT}} figure at SKILLS_SYNCED_COUNT (resolved minus refused),
# which undercounts the catalogue by exactly REFUSED_COUNT whenever anything
# is refused — this fixture has REFUSED_COUNT=1, SKILLS_RESOLVED_COUNT=1, so
# the wrong figure reads 0 while the catalogue still has 1 row. Verified by
# hand against the round-2 code: README said "0 reusable" above a 1-row
# table, and the CHANGELOG said "Synced 0 skills" above a bullet for `my
# skill` with no indication that entry wasn't part of the 0. Both fixed:
# README/fallback now use SKILLS_RESOLVED_COUNT (matches the catalogue
# unconditionally), and the CHANGELOG inventory annotates refused entries so
# "Synced 0" no longer reads as contradicted by a populated list. ---
SPACE_PLUGIN_README="$(cat "$MONOREPO_SPACE_PLUGIN_FIXTURE/README.md" 2>/dev/null || true)"
SPACE_PLUGIN_CHANGELOG="$(cat "$MONOREPO_SPACE_PLUGIN_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"
SPACE_PLUGIN_ROW_COUNT="$(skill_catalog_row_count "$MONOREPO_SPACE_PLUGIN_FIXTURE/README.md")"
assert_eq "the README's {{SKILL_COUNT}} figure equals the catalogue row count even when a skill was refused" \
    "$SPACE_PLUGIN_ROW_COUNT" "$(sed -n 's/^A curated collection of \([0-9]*\) reusable.*/\1/p' <<< "$SPACE_PLUGIN_README")"
assert_contains "…concretely: the README says 1 (the refused skill's row is kept), not the synced-only 0" \
    "A curated collection of 1 reusable" "$SPACE_PLUGIN_README"
assert_contains "…while the CHANGELOG's \"Synced N skills\" correctly reports 0 (nothing was actually copied)" \
    "Synced 0 skills from local source." "$SPACE_PLUGIN_CHANGELOG"
assert_line_present "…and the refused skill's own inventory entry is annotated, not left silently contradicting \"Synced 0\"" \
    "- \`my skill\` v2.0.0 (REFUSED — stale local source, not synced this run) — Throwaway fixture skill — the in-repo copy, newer than the local source, so the reversion guard must refuse to overwrite it." \
    "$SPACE_PLUGIN_CHANGELOG"

# --- Assertion: the arithmetic fix in isolation, no spaces involved. Verified
# by hand against a scratch revert of the summary line alone (SKILL_COUNT -
# REFUSED_COUNT instead of SKILLS_RESOLVED_COUNT - REFUSED_COUNT): this run
# reports "2 skills synced" — the number of names *requested* — even though
# only demo-skill actually resolved and was copied. ---
assert_eq "mixed --skills run (one resolves, one does not) exits 0 — a partial resolution is not the #80 all-fail case" \
    "0" "$MIXEDSKILLS_RC"
assert_contains "…the unresolved name still gets its own ERROR" \
    "ERROR: no SKILL.md" "$MIXEDSKILLS_STDOUT"
assert_eq "…and the summary reports exactly the one skill that actually resolved and synced, not the two names requested" \
    "1" "$(sync_complete_count "$MIXEDSKILLS_STDOUT")"
assert_eq "…matching its single catalogue row" \
    "1" "$(skill_catalog_row_count "$MONOREPO_MIXEDSKILLS_FIXTURE/README.md")"

# --- Assertion: the fix must reach every PERSISTED past-tense count, not only
# stdout (review round 2's finding: five result-sites total — the stdout
# summary line fixed in round 1 is only one of them). Checked against this
# same mixed-skills fixture, whose catalogue row count (1) and requested name
# count (2) diverge, which is exactly what makes this a real discriminator
# rather than the coincidental-agreement trap the round-1 report already
# flagged for the space fixture. Each assertion below fails against the
# round-1 code (which still wrote SKILL_COUNT — 2 — into these two artifacts)
# and passes only once the writer uses SKILLS_SYNCED_COUNT. The README's
# {{SKILL_COUNT}}-templated line and the CHANGELOG's "Synced N skills" entry
# are both PAST-TENSE claims about what the run actually did, unlike the
# "Skills to sync (N):" line printed before the loop runs (deliberately left
# on the discovered/requested count — see the comment at its definition
# site). ---
MIXEDSKILLS_README="$(cat "$MONOREPO_MIXEDSKILLS_FIXTURE/README.md" 2>/dev/null || true)"
MIXEDSKILLS_CHANGELOG="$(cat "$MONOREPO_MIXEDSKILLS_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"
assert_contains "…the persisted README count also agrees with the catalogue, not the two names requested" \
    "A curated collection of 1 reusable" "$MIXEDSKILLS_README"
assert_contains "…and the persisted CHANGELOG \"Synced N skills\" entry agrees too" \
    "Synced 1 skills from local source." "$MIXEDSKILLS_CHANGELOG"

# --- Positive control: the ordinary (no-space, no partial-failure) fixture's
# summary line is correct and self-consistent. Without this, a rework that
# broke the arithmetic for every run (not just the space/mixed cases above)
# would still pass every #81 assertion so far. ---
SYNC_ROW_COUNT="$(skill_catalog_row_count "$MONOREPO_FIXTURE/README.md")"
assert_eq "positive control: the ordinary (no-space) fixture's summary count is correct" \
    "2" "$(sync_complete_count "$SYNC_STDOUT")"
assert_eq "…and matches its catalogue row count" \
    "$SYNC_ROW_COUNT" "$(sync_complete_count "$SYNC_STDOUT")"

# ============================================================
# Deep-review fix round (PR #91): defects introduced or left open by the
# #73/#77-#81 batch above
# ============================================================
#
#  11. THE INSTRUMENT GAP. #81 converted five `for X in $LIST` loops in
#      sync-monorepo.sh (and one in validate-pre-sync.sh) to
#      `while IFS= read -r X; do … done <<< "$LIST"`. That fixed the
#      word-splitting, and introduced a new failure mode the old `for` never
#      had: `done <<< "$LIST"` binds the list to the loop BODY's stdin, and
#      those bodies shell out to gh, rsync, cp, diff, find, jq, sed and grep.
#      Any child that reads stdin consumes the rest of the skill list, the loop
#      exits early, and the run reports success. Worse, #81's own count fix
#      makes the truncation self-consistent — {{SKILL_COUNT}} is
#      SKILLS_RESOLVED_COUNT, which counts the loop's own iterations, so the
#      catalogue, the count and the CHANGELOG inventory all agree with each
#      other while two thirds of the catalogue silently vanishes.
#
#      This harness could not see it, and that is the point of the fixture
#      below. Every existing run uses a `gh` shim that never touches stdin, so
#      the whole suite is structurally blind to the defect: the shim is the
#      instrument, and the instrument had no probe for this. DRAIN_FIXTURE
#      supplies a `gh` shim that drains stdin (`cat`) exactly as any ordinary
#      filter would, and asserts all three skills still sync. All six loops are
#      now bound to fd 3 (`read … <&3` / `done 3<<< "$LIST"`), which leaves the
#      body's stdin inherited from the caller so no child can reach the list.
#
#  12. `_MANIFEST_SKILL_NAMES=$(manifest_skill_names … 2>/dev/null || true)`
#      claimed to preserve "the pre-existing tolerance of an unreadable
#      manifest". Only half true: the base commit had TWO reads, and only one
#      was tolerant. The reversion guard's was a command substitution in a `for`
#      word-list (does not trip `set -e`); the drift check's was an ASSIGNMENT,
#      which under `set -e` aborted the run. Consolidating both onto one
#      tolerant read silently downgraded the second, on the destructive path.
#      Now recorded as a build failure and collected into _FAILED_BUILDS.
#
#  13. The collected-failure record was written AFTER a command that can abort.
#      `_BUILD_LOG` is named from the manifest's `.name`, which is free text; a
#      `/` in it makes the log redirect fail, so `sed` on the missing log fails,
#      so `set -e` kills the run before `_FAILED_BUILDS=` is ever assigned — and
#      the whole point of collecting failures (naming every broken manifest in
#      one pass) is lost, because the closing summary never prints. The
#      assignment now precedes the `sed`, and the `sed` carries `|| true`.
#
#  14. #73's bare-entry rejection landed in prepare-plugin.sh only, and the main
#      sync loop runs FIRST — so `"agents": ["x"]` killed the sync at
#      `jq -r ".agents[0].name"` with a raw `Cannot index string with "name"`
#      and rc=5, and the friendly message never printed. Now checked at both.
#
#  15. `--add <unresolvable>` against a POPULATED monorepo printed one inline
#      ERROR and exited 0 having regenerated the catalogue. #80's guard cannot
#      catch it (it fires only when *zero* names resolve, and $existing always
#      contributes resolvable ones). discover_skills() now rejects any
#      --add-contributed name with no SKILL.md, before anything is written.
#      This also closes #85, which tracked the narrower empty-monorepo case.
#
#  16. The --skills branch used `sort` where --add used `sort -u`, under a
#      comment saying it mirrored --add. `--skills alpha,alpha` synced one skill
#      twice: two stanzas, two identical catalogue rows, two identical `cp -r`
#      install lines published as instructions, and a doubled count in three
#      places, all agreeing with each other. Now `sort -u`.
#
#  17. #81 had SIX conversion sites, not five: validate-pre-sync.sh's own skill
#      loop is the sixth, and it had no coverage at all — reverting it alone to
#      `for SKILL_NAME in $SKILLS` left this harness at 248 PASS / 0 FAIL. The
#      space-name fixtures were all built sync-side. Fixed with a third presync
#      monorepo carrying space-named skills on both sides of the report; see the
#      section following the #78 assertions for why the coverage was missed and
#      why it needed its own fixture rather than growing an existing one.
#
#  18. Defect 14's guard was NON-FATAL, and its own comment's safety net did not
#      hold. It set AGENT_COUNT=0 and left the run to the auto-build stage,
#      which only invokes prepare-plugin.sh when _NEEDS_BUILD is true. An
#      already-published plugin whose manifest gains `"agents": ["x"]` without
#      its SKILL.md changing therefore printed one ERROR and exited 0 with the
#      catalogue regenerated and the declared agents silently not copied — a
#      loudness regression, since before the guard the same manifest died at jq
#      with rc=5 and wrote nothing. Now collected into _BARE_ENTRY_MANIFESTS,
#      declared before the main sync loop, and exited on through the shared
#      collected-failure gate — which also moved OUT of the
#      `[[ -x "$PREPARE_SCRIPT" ]]` block, since two of its three lists are
#      filled inside it but the third is not.
#
#  19. The collected-failure summary claimed more than happened on two of the
#      three paths it now serves: it said "plugin build failed" for a manifest
#      whose skills[] merely could not be READ (no build attempted), and
#      "Skills synced before this point are already written" under --dry-run,
#      which writes nothing. Each reason now gets its own labelled row, and the
#      --dry-run path says so explicitly.
#
# NOT covered by any assertion, and deliberately so — both are latent by
# construction, with no reachable input that triggers them today:
#   * capturing manifest_skill_names' stderr separately instead of `2>&1`, so a
#     jq diagnostic accompanying a ZERO exit cannot become a phantom skill name.
#     No such warning exists for this filter; merging a diagnostic stream into
#     data that is then read as data is unsafe by construction regardless.
#   * putting the marketplace.json loop on fd 3 like every other list-driven
#     loop. Its children (dirname, jq) do not read stdin today.
# Writing an assertion for either would mean asserting a condition the code
# cannot currently reach, which passes vacuously and reads as coverage.

SKILLS_HOME_FIXROUND_FIXTURE="$SCRATCH_DIR/skills-home-fixround"
MONOREPO_DRAIN_FIXTURE="$SCRATCH_DIR/monorepo-drain"
MONOREPO_ADDBAD_FIXTURE="$SCRATCH_DIR/monorepo-addbad"
MONOREPO_DUPSKILLS_FIXTURE="$SCRATCH_DIR/monorepo-dupskills"
SKILLS_HOME_BADMANIFEST_FIXTURE="$SCRATCH_DIR/skills-home-badmanifest"
MONOREPO_BADMANIFEST_FIXTURE="$SCRATCH_DIR/monorepo-badmanifest"
SKILLS_HOME_GOODMANIFEST_FIXTURE="$SCRATCH_DIR/skills-home-goodmanifest"
MONOREPO_GOODMANIFEST_FIXTURE="$SCRATCH_DIR/monorepo-goodmanifest"
SKILLS_HOME_BAREAGENT_FIXTURE="$SCRATCH_DIR/skills-home-bareagent"
MONOREPO_BAREAGENT_FIXTURE="$SCRATCH_DIR/monorepo-bareagent"
SKILLS_HOME_SLASHLOG_FIXTURE="$SCRATCH_DIR/skills-home-slashlog"
MONOREPO_SLASHLOG_FIXTURE="$SCRATCH_DIR/monorepo-slashlog"

# One shared SKILLS_HOME for the three manifest-free fixtures (drain, addbad,
# dupskills): with no plugin-manifest.json anywhere under it, the auto-build
# stage finds nothing in any of those runs, so they cannot print into each
# other the way a broken manifest would. The four manifest-carrying fixtures
# below each get a home of their own for exactly that reason.
mkdir -p "$SKILLS_HOME_FIXROUND_FIXTURE" \
         "$MONOREPO_DRAIN_FIXTURE" \
         "$MONOREPO_ADDBAD_FIXTURE" \
         "$MONOREPO_DUPSKILLS_FIXTURE" \
         "$SKILLS_HOME_BADMANIFEST_FIXTURE/badmanifest-skill" \
         "$MONOREPO_BADMANIFEST_FIXTURE/badmanifest-skill" \
         "$MONOREPO_BADMANIFEST_FIXTURE/plugins/badmanifest-plugin/.claude-plugin" \
         "$MONOREPO_BADMANIFEST_FIXTURE/plugins/badmanifest-plugin/skills/badmanifest-skill" \
         "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill" \
         "$MONOREPO_GOODMANIFEST_FIXTURE/goodmanifest-skill" \
         "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/.claude-plugin" \
         "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/skills/goodmanifest-skill" \
         "$SKILLS_HOME_BAREAGENT_FIXTURE/bareagent-skill" \
         "$MONOREPO_BAREAGENT_FIXTURE/bareagent-skill" \
         "$SKILLS_HOME_SLASHLOG_FIXTURE/slashlog-skill" \
         "$MONOREPO_SLASHLOG_FIXTURE/slashlog-skill"

# Writes a minimal fixture SKILL.md into <dir>/<name>/, at <version>.
write_fixround_skill() {
    local dir="$1" name="$2" version="${3:-1.0.0}"
    mkdir -p "$dir/$name"
    cat > "$dir/$name/SKILL.md" <<EOF
---
name: $name
description: Throwaway fixture skill for the PR #91 deep-review fix round.
version: $version
---

# $name

Fixture content.
EOF
}

for _fr_skill in drain-alpha drain-beta drain-gamma; do
    write_fixround_skill "$SKILLS_HOME_FIXROUND_FIXTURE" "$_fr_skill"
    write_fixround_skill "$MONOREPO_DRAIN_FIXTURE" "$_fr_skill"
done
write_fixround_skill "$SKILLS_HOME_FIXROUND_FIXTURE" addbad-skill
write_fixround_skill "$MONOREPO_ADDBAD_FIXTURE" addbad-skill
# Named by --add in the positive control below; deliberately has no directory in
# MONOREPO_ADDBAD_FIXTURE beforehand, so --add has to bring it in.
write_fixround_skill "$SKILLS_HOME_FIXROUND_FIXTURE" addbad-newcomer
write_fixround_skill "$SKILLS_HOME_FIXROUND_FIXTURE" dup-skill
write_fixround_skill "$MONOREPO_DUPSKILLS_FIXTURE" dup-skill

# ------------------------------------------------------------------
# Defect 11 — a `gh` shim that drains stdin
# ------------------------------------------------------------------
#
# The whole suite's existing shim exits without reading stdin, which is why it
# never caught this. `cat >/dev/null` is not a contrived hostile stub: it is
# what any program that treats stdin as input does, and `gh` itself reads stdin
# on several subcommands. The real `gh repo view --json url` happens not to,
# which is the only reason the shipped defect is latent rather than live.
#
# The byte counter is the instrument's own control. Post-fix the loop body's
# stdin is inherited from the caller (/dev/null on the run below), so every
# invocation must read 0 bytes; pre-fix it is the here-string carrying the
# remaining skill list, so the first invocation reads the rest of it. Asserting
# the counter — not just the skill count — is what proves the probe is wired to
# the thing under test rather than passing for an unrelated reason.
GH_DRAIN_SHIM_DIR="$SCRATCH_DIR/shim-bin-drain"
GH_DRAIN_BYTES_LOG="$SCRATCH_DIR/gh-drain-bytes.log"
mkdir -p "$GH_DRAIN_SHIM_DIR"
: > "$GH_DRAIN_BYTES_LOG"

cat > "$GH_DRAIN_SHIM_DIR/gh" <<EOF
#!/usr/bin/env bash
# wc -c on the drained stream, not a bare cat: the assertion needs to know
# HOW MUCH was consumed, and "0" is the post-fix expectation.
_drained=\$(cat | wc -c | tr -d ' ')
printf '%s\n' "\$_drained" >> "$GH_DRAIN_BYTES_LOG"
exit 1
EOF
chmod +x "$GH_DRAIN_SHIM_DIR/gh"

# Control on the shim itself: fed 4 bytes it must report 4. Without this, a shim
# broken so that it always reports 0 would make the "0 bytes drained" assertion
# below pass vacuously — the guard-stuck-ON case for the instrument.
GH_DRAIN_SELFTEST="$(printf 'abcd' | "$GH_DRAIN_SHIM_DIR/gh" x y || true; tail -1 "$GH_DRAIN_BYTES_LOG")"
assert_eq "control: the draining gh shim genuinely consumes stdin (4 bytes in, 4 reported)" \
    "4" "$GH_DRAIN_SELFTEST"
: > "$GH_DRAIN_BYTES_LOG"

# stdin from /dev/null explicitly. Two reasons: the shim would otherwise block
# on an interactive terminal, and the post-fix expectation ("every gh invocation
# reads 0 bytes") has to be pinned to a known-empty stdin rather than to
# whatever the harness inherited.
DRAIN_STDOUT_LOG="$SCRATCH_DIR/drain-stdout.log"
DRAIN_STDERR_LOG="$SCRATCH_DIR/drain-stderr.log"
DRAIN_RC=0
(
    cd "$RUN_CWD"
    PATH="$GH_DRAIN_SHIM_DIR:$PATH" \
    SKILLS_HOME="$SKILLS_HOME_FIXROUND_FIXTURE" \
        "$SYNC_SCRIPT" --github-user harness-fixture-user "$MONOREPO_DRAIN_FIXTURE"
) >"$DRAIN_STDOUT_LOG" 2>"$DRAIN_STDERR_LOG" </dev/null || DRAIN_RC=$?
DRAIN_STDOUT="$(cat "$DRAIN_STDOUT_LOG")"

# --- Assertions: defect 11. Verified red against the pre-fix build (the six
# loops on plain stdin): this run synced ONE skill, printed "Sync complete. 1
# skills synced", wrote a one-row catalogue and "A curated collection of 1
# reusable Agent Skills", and exited 0 — every figure agreeing with every other
# while two of the three skills silently vanished from the published
# catalogue. ---
assert_eq "stdin-draining gh: the sync still exits 0" "0" "$DRAIN_RC"
DRAIN_NAMES="$(synced_names "$DRAIN_STDOUT")"
assert_eq "…discovery still finds all three (the truncation is in consumption, not discovery)" \
    "3" "$(listed_skill_count "$DRAIN_NAMES")"
assert_eq "…and all three are actually synced, not just the first before gh ate the rest" \
    "3" "$(sync_complete_count "$DRAIN_STDOUT")"
for _fr_skill in drain-alpha drain-beta drain-gamma; do
    assert_contains "…the main sync loop reached $_fr_skill" \
        "--- $_fr_skill ---" "$DRAIN_STDOUT"
done
DRAIN_README="$(cat "$MONOREPO_DRAIN_FIXTURE/README.md" 2>/dev/null || true)"
assert_eq "…the published catalogue has all three rows (site 1/5: the main loop)" \
    "3" "$(skill_catalog_row_count "$MONOREPO_DRAIN_FIXTURE/README.md")"
assert_contains "…and the README count agrees with it rather than with a truncated loop" \
    "A curated collection of 3 reusable" "$DRAIN_README"
DRAIN_CHANGELOG="$(cat "$MONOREPO_DRAIN_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"
assert_contains "…and its \"Synced N skills\" figure is the full three" \
    "Synced 3 skills from local source." "$DRAIN_CHANGELOG"

# --- Positive controls on the fd-3 conversion itself, NOT fail-first probes for
# defect 11. Measured, not assumed: both of these PASS against the
# loops-on-stdin mutant, because the install-all builder (site 4/5) and the
# CHANGELOG inventory builder (site 5/5) re-read $SKILLS_TO_SYNC from scratch
# and their bodies spawn nothing that reads stdin, so a truncated main loop
# does not truncate them. What they do catch is a botched conversion of these
# two loops — `done 3<<<` without the matching `read … <&3` reads nothing at
# all and both artifacts come out empty — which is the failure mode this fix
# round could plausibly introduce at these sites. Labelled honestly rather than
# left implying a fail-first they do not have. ---
assert_line_present "control: install-all still emits the last skill's cp line after the fd-3 conversion (site 4/5)" \
    "cp -r /tmp/claude-code-skills/drain-gamma ~/.claude/skills/drain-gamma" "$DRAIN_README"
assert_contains "control: the CHANGELOG inventory still carries the last skill's entry (site 5/5)" \
    "- \`drain-gamma\` v1.0.0" "$DRAIN_CHANGELOG"

# The instrument assertion. Every recorded invocation must be 0 — the loop's
# list is on fd 3, so a child on stdin has nothing to reach. `sort -u` over the
# whole log rather than a tail: one non-zero invocation anywhere is a leak, and
# checking only the last would miss it.
assert_eq "…and no gh invocation could read a single byte of the skill list (all on fd 3)" \
    "0" "$(sort -u "$GH_DRAIN_BYTES_LOG" | tr '\n' ' ' | sed 's/ *$//')"
assert_eq "…with the probe actually having run (gh was invoked once per synced skill)" \
    "3" "$(wc -l < "$GH_DRAIN_BYTES_LOG" | tr -d ' ')"

# --- The loop-level `</dev/null`, isolated from the run-level one. ---
#
# The run above supplies </dev/null itself, so its zero-bytes result would hold
# even with the loop's own redirect removed — it proves the list is off stdin,
# not that the body's stdin is neutralised. This run feeds the sync a KNOWN
# NON-EMPTY stdin instead. With `done … </dev/null` on the loop the shim still
# reads 0; without it the shim reaches the caller's stdin and reads those bytes.
#
# That distinction is the point. fd 3 alone is a convention, not a barrier: it
# is inherited across exec, and a child running `<&3` consumes the list exactly
# as a stdin-reading child did — measured directly, a 4-line list driving 2
# iterations when the body read one line from fd 3. So the guarantee has two
# halves, and this asserts the half that is actually unconditional. The other
# half is not asserted: a child would have to name fd 3 deliberately, and an
# assertion for it would be testing bash's fd inheritance rather than this
# script.
: > "$GH_DRAIN_BYTES_LOG"
DRAIN_FED_RC=0
(
    cd "$RUN_CWD"
    PATH="$GH_DRAIN_SHIM_DIR:$PATH" \
    SKILLS_HOME="$SKILLS_HOME_FIXROUND_FIXTURE" \
        "$SYNC_SCRIPT" --github-user harness-fixture-user "$MONOREPO_DRAIN_FIXTURE"
) >"$SCRATCH_DIR/drain-fed-stdout.log" 2>"$SCRATCH_DIR/drain-fed-stderr.log" \
    <<< "STDIN-THE-LOOP-MUST-NOT-EXPOSE" || DRAIN_FED_RC=$?
DRAIN_FED_STDOUT="$(cat "$SCRATCH_DIR/drain-fed-stdout.log")"

assert_eq "a run given non-empty stdin still syncs every skill" \
    "0" "$DRAIN_FED_RC"
assert_eq "…all three, not a prefix" "3" "$(sync_complete_count "$DRAIN_FED_STDOUT")"
assert_eq "…and every gh invocation still read 0 bytes, so the loop's own </dev/null holds" \
    "0" "$(sort -u "$GH_DRAIN_BYTES_LOG" | tr '\n' ' ' | sed 's/ *$//')"
assert_eq "…with the probe having actually run against the fed stdin" \
    "3" "$(wc -l < "$GH_DRAIN_BYTES_LOG" | tr -d ' ')"

# ------------------------------------------------------------------
# Defects 15 + 16 — --add resolvability, --skills de-duplication
# ------------------------------------------------------------------

# Seed run: an ordinary sync, so the fixture has a real published catalogue for
# the refused --add below to be shown NOT to have disturbed. Without the seed
# there is no README, and "the catalogue is untouched" would hold vacuously.
ADDBAD_SEED_RC=0
run_sync "$SKILLS_HOME_FIXROUND_FIXTURE" "$MONOREPO_ADDBAD_FIXTURE" \
    "$SCRATCH_DIR/addbad-seed-stdout.log" "$SCRATCH_DIR/addbad-seed-stderr.log" || ADDBAD_SEED_RC=$?
assert_eq "control: the addbad fixture's seed sync succeeds and publishes a catalogue" \
    "0" "$ADDBAD_SEED_RC"
ADDBAD_README_BEFORE="$(cat "$MONOREPO_ADDBAD_FIXTURE/README.md" 2>/dev/null || true)"
ADDBAD_CHANGELOG_BEFORE="$(cat "$MONOREPO_ADDBAD_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"
assert_eq "…with exactly one skill row to protect" \
    "1" "$(skill_catalog_row_count "$MONOREPO_ADDBAD_FIXTURE/README.md")"

ADDBAD_RC=0
run_sync "$SKILLS_HOME_FIXROUND_FIXTURE" "$MONOREPO_ADDBAD_FIXTURE" \
    "$SCRATCH_DIR/addbad-stdout.log" "$SCRATCH_DIR/addbad-stderr.log" \
    --add nosuchskill || ADDBAD_RC=$?
ADDBAD_STDERR="$(cat "$SCRATCH_DIR/addbad-stderr.log")"

# --- Assertions: defect 15. Verified red against the pre-fix build: rc=0, the
# only complaint a single inline "  ERROR: no SKILL.md in …" from the sync loop,
# and the README/CHANGELOG/marketplace all regenerated regardless. ---
assert_eq "--add with an unresolvable name against a POPULATED monorepo now fails" \
    "1" "$ADDBAD_RC"
assert_contains "…naming the offending argument, not just reporting a count" \
    "--add named skills with no SKILL.md: nosuchskill" "$ADDBAD_STDERR"
assert_contains "…and saying where it looked" \
    "Looked under $SKILLS_HOME_FIXROUND_FIXTURE/<name>/" "$ADDBAD_STDERR"
assert_eq "…with the published catalogue left byte-identical, not republished" \
    "$ADDBAD_README_BEFORE" "$(cat "$MONOREPO_ADDBAD_FIXTURE/README.md" 2>/dev/null || true)"
assert_eq "…and the CHANGELOG likewise untouched" \
    "$ADDBAD_CHANGELOG_BEFORE" "$(cat "$MONOREPO_ADDBAD_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"

# --- Positive control: a guard that refused EVERY --add would satisfy every
# assertion above. A real skill must still come in, and the catalogue must grow
# to two rows. This also covers the comma-split path — a one-line
# skill_source_dir "$ADD_SKILL" test would look for a skill literally named
# "addbad-newcomer,addbad-skill" and refuse this legitimate call. ---
ADDGOOD_RC=0
run_sync "$SKILLS_HOME_FIXROUND_FIXTURE" "$MONOREPO_ADDBAD_FIXTURE" \
    "$SCRATCH_DIR/addgood-stdout.log" "$SCRATCH_DIR/addgood-stderr.log" \
    --add addbad-newcomer,addbad-skill || ADDGOOD_RC=$?
assert_eq "positive control: --add with resolvable comma-separated names still succeeds" \
    "0" "$ADDGOOD_RC"
assert_eq "…and the catalogue grew to two rows" \
    "2" "$(skill_catalog_row_count "$MONOREPO_ADDBAD_FIXTURE/README.md")"
assert_file_exists "…with the newcomer actually copied in" \
    "$MONOREPO_ADDBAD_FIXTURE/addbad-newcomer/SKILL.md"

DUPSKILLS_RC=0
run_sync "$SKILLS_HOME_FIXROUND_FIXTURE" "$MONOREPO_DUPSKILLS_FIXTURE" \
    "$SCRATCH_DIR/dupskills-stdout.log" "$SCRATCH_DIR/dupskills-stderr.log" \
    --skills dup-skill,dup-skill || DUPSKILLS_RC=$?
DUPSKILLS_STDOUT="$(cat "$SCRATCH_DIR/dupskills-stdout.log")"
DUPSKILLS_README="$(cat "$MONOREPO_DUPSKILLS_FIXTURE/README.md" 2>/dev/null || true)"
DUPSKILLS_CHANGELOG="$(cat "$MONOREPO_DUPSKILLS_FIXTURE/CHANGELOG.md" 2>/dev/null || true)"

# --- Assertions: defect 16. Verified red against the pre-fix build (`sort`
# without -u): "Skills to sync (2):", two "--- dup-skill ---" stanzas, "Sync
# complete. 2 skills synced", two identical catalogue rows, "A curated
# collection of 2 reusable", "Synced 2 skills" and two identical `cp -r` lines
# — one skill counted twice everywhere, consistently. ---
assert_eq "--skills with a repeated name still exits 0" "0" "$DUPSKILLS_RC"
assert_eq "…de-duplicated to one name in the plan line, matching the --add branch" \
    "1" "$(printed_skill_count "$DUPSKILLS_STDOUT")"
assert_eq "…one name in the plan list" \
    "1" "$(listed_skill_count "$(synced_names "$DUPSKILLS_STDOUT")")"
assert_eq "…synced once, not twice" "1" "$(sync_complete_count "$DUPSKILLS_STDOUT")"
assert_eq "…with a single catalogue row rather than a duplicated one" \
    "1" "$(skill_catalog_row_count "$MONOREPO_DUPSKILLS_FIXTURE/README.md")"
assert_contains "…and the README count is 1" \
    "A curated collection of 1 reusable" "$DUPSKILLS_README"
assert_contains "…and the CHANGELOG count is 1" \
    "Synced 1 skills from local source." "$DUPSKILLS_CHANGELOG"
assert_eq "…and exactly one install-all cp line is published as an instruction" \
    "1" "$(grep -cxF "cp -r /tmp/claude-code-skills/dup-skill ~/.claude/skills/dup-skill" <<< "$DUPSKILLS_README" || true)"

# ------------------------------------------------------------------
# Defect 12 — an unreadable skills[] must not be swallowed
# ------------------------------------------------------------------
#
# The plugin is ALREADY PUBLISHED under plugins/, which is what makes this
# fixture discriminate. With the plugin absent, `[[ ! -d "$_PLUGIN_DST/
# .claude-plugin" ]]` sets _NEEDS_BUILD=true regardless of the failed read,
# prepare-plugin.sh runs, fails on the same manifest and is collected — so the
# pre-fix run exits 1 too and the fixture proves nothing. Published, the drift
# check is the ONLY thing that can set _NEEDS_BUILD, its _FIRST_SKILL comes from
# the swallowed read, and the pre-fix run therefore never attempts a build at
# all: rc=0, not one ERROR line anywhere, catalogue regenerated.
cat > "$SKILLS_HOME_BADMANIFEST_FIXTURE/badmanifest-skill/SKILL.md" <<'EOF'
---
name: badmanifest-skill
description: Throwaway fixture skill whose manifest declares skills[] as a number (#73; harness defect 12).
version: 2.0.0
---

# Bad Manifest Skill
EOF
cp "$SKILLS_HOME_BADMANIFEST_FIXTURE/badmanifest-skill/SKILL.md" \
   "$MONOREPO_BADMANIFEST_FIXTURE/badmanifest-skill/SKILL.md"

# `[123]`, not `["name"]`: a bare STRING is the legacy form #73 normalises and
# manifest_skill_names() handles it deliberately. A number has no normalisation,
# so `.name` on it is the type error that makes jq exit 5 — while the `.name`
# read further up the stage succeeds on the same file, so nothing earlier
# catches it.
cat > "$SKILLS_HOME_BADMANIFEST_FIXTURE/badmanifest-skill/plugin-manifest.json" <<'EOF'
{
  "name": "badmanifest-plugin",
  "version": "2.0.0",
  "description": "Throwaway fixture plugin whose skills[] holds a number (#73; harness defect 12).",
  "skills": [123],
  "commands": []
}
EOF

# The stale published copy the drift check would want to rebuild (v1.0.0 against
# the source's v2.0.0).
cat > "$MONOREPO_BADMANIFEST_FIXTURE/plugins/badmanifest-plugin/.claude-plugin/plugin.json" <<'EOF'
{
  "name": "badmanifest-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin, already published and stale."
}
EOF
cat > "$MONOREPO_BADMANIFEST_FIXTURE/plugins/badmanifest-plugin/skills/badmanifest-skill/SKILL.md" <<'EOF'
---
name: badmanifest-skill
description: STALE published copy — a correct drift check wants to rebuild this.
version: 1.0.0
---

# Bad Manifest Skill (stale)
EOF

BADMANIFEST_RC=0
run_sync "$SKILLS_HOME_BADMANIFEST_FIXTURE" "$MONOREPO_BADMANIFEST_FIXTURE" \
    "$SCRATCH_DIR/badmanifest-stdout.log" "$SCRATCH_DIR/badmanifest-stderr.log" || BADMANIFEST_RC=$?
BADMANIFEST_STDERR="$(cat "$SCRATCH_DIR/badmanifest-stderr.log")"
BADMANIFEST_MANIFEST="$SKILLS_HOME_BADMANIFEST_FIXTURE/badmanifest-skill/plugin-manifest.json"

# --- Assertions: defect 12. Verified red against the pre-fix build: rc=0, the
# combined output contained no "ERROR" at all, and README.md was regenerated. ---
assert_eq "a manifest whose skills[] cannot be read fails the run instead of being skipped" \
    "1" "$BADMANIFEST_RC"
assert_contains "…naming the manifest" \
    "ERROR: cannot read skills[] from $BADMANIFEST_MANIFEST" "$BADMANIFEST_STDERR"
assert_contains "…and relaying jq's own diagnosis rather than swallowing it" \
    "Cannot index number with string \"name\"" "$BADMANIFEST_STDERR"
assert_contains "…joining the collected-failure summary that names every broken manifest in one pass" \
    "skills[] could not be read: $BADMANIFEST_MANIFEST" "$BADMANIFEST_STDERR"
assert_not_contains "…and is NOT reported as a build failure, since no build was attempted" \
    "plugin build failed:" "$BADMANIFEST_STDERR"
assert_eq "…with the catalogue deliberately NOT regenerated on the way out" \
    "false" "$([[ -f "$MONOREPO_BADMANIFEST_FIXTURE/README.md" ]] && echo true || echo false)"

# --- Positive control: the identical fixture shape with a WELL-FORMED skills[].
# Without it, a change that failed every run carrying an already-published
# plugin would satisfy every assertion above. ---
cat > "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill/SKILL.md" <<'EOF'
---
name: goodmanifest-skill
description: Throwaway fixture skill — positive control for #73, harness defect 12; well-formed manifest.
version: 2.0.0
---

# Good Manifest Skill
EOF
cp "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill/SKILL.md" \
   "$MONOREPO_GOODMANIFEST_FIXTURE/goodmanifest-skill/SKILL.md"
cat > "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill/plugin-manifest.json" <<'EOF'
{
  "name": "goodmanifest-plugin",
  "version": "2.0.0",
  "description": "Throwaway fixture plugin, well-formed (#73, harness defect 12 positive control).",
  "skills": [
    {
      "name": "goodmanifest-skill",
      "source": "."
    }
  ],
  "agents": [
    {
      "name": "control-agent",
      "source": "./agents-src/control-agent.md"
    }
  ],
  "commands": []
}
EOF

# A WELL-FORMED agents[] entry, so defect 14's guard has something it must NOT
# reject. Without an agents[] here the guard could be stuck permanently ON and
# every assertion in this file would still pass — measured, not assumed: a
# mutant with `_BARE_AGENTS="always-on-control"` (fires on every manifest,
# suppressing all agent copying) produced 246 PASS / 0 FAIL before this fixture
# existed.
mkdir -p "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill/agents-src"
cat > "$SKILLS_HOME_GOODMANIFEST_FIXTURE/goodmanifest-skill/agents-src/control-agent.md" <<'EOF'
---
name: control-agent
description: Throwaway fixture agent — proves a well-formed agents[] entry is still copied (#73, harness defect 14 positive control).
---

GOODMANIFEST-AGENT-MARKER
EOF
cat > "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/.claude-plugin/plugin.json" <<'EOF'
{
  "name": "goodmanifest-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin, already published and stale."
}
EOF
cat > "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/skills/goodmanifest-skill/SKILL.md" <<'EOF'
---
name: goodmanifest-skill
description: STALE published copy — the drift check must rebuild this.
version: 1.0.0
---

# Good Manifest Skill (stale)
EOF

GOODMANIFEST_RC=0
run_sync "$SKILLS_HOME_GOODMANIFEST_FIXTURE" "$MONOREPO_GOODMANIFEST_FIXTURE" \
    "$SCRATCH_DIR/goodmanifest-stdout.log" "$SCRATCH_DIR/goodmanifest-stderr.log" || GOODMANIFEST_RC=$?
GOODMANIFEST_STDOUT="$(cat "$SCRATCH_DIR/goodmanifest-stdout.log")"
# Both streams. The bare-agent ERROR goes to stderr, so a control that reads
# stdout alone passes no matter what the guard does — which is exactly what
# happened: the stdout-only form of the assertion below was green against the
# guard-stuck-ON mutant.
GOODMANIFEST_BOTH="$(cat "$SCRATCH_DIR/goodmanifest-stdout.log" "$SCRATCH_DIR/goodmanifest-stderr.log")"
assert_eq "positive control: the same shape with a well-formed skills[] still exits 0" \
    "0" "$GOODMANIFEST_RC"
assert_contains "…the drift check still fires and the stale published plugin is rebuilt" \
    "AUTO-SYNCED  plugins/goodmanifest-plugin/" "$GOODMANIFEST_STDOUT"
assert_contains "…the read that now reports failure still succeeds silently here" \
    "goodmanifest-skill" "$(cat "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/skills/goodmanifest-skill/SKILL.md" 2>/dev/null || true)"
assert_contains "…and the published copy is no longer the stale v1.0.0" \
    "version: 2.0.0" "$(cat "$MONOREPO_GOODMANIFEST_FIXTURE/plugins/goodmanifest-plugin/skills/goodmanifest-skill/SKILL.md" 2>/dev/null || true)"

# ------------------------------------------------------------------
# Defect 14 — bare agents[] entry must not kill the main sync loop
# ------------------------------------------------------------------
cat > "$SKILLS_HOME_BAREAGENT_FIXTURE/bareagent-skill/SKILL.md" <<'EOF'
---
name: bareagent-skill
description: Throwaway fixture skill whose manifest declares a bare-string agent (#73; harness defect 14).
version: 1.0.0
---

# Bare Agent Skill
EOF
cp "$SKILLS_HOME_BAREAGENT_FIXTURE/bareagent-skill/SKILL.md" \
   "$MONOREPO_BAREAGENT_FIXTURE/bareagent-skill/SKILL.md"
cat > "$SKILLS_HOME_BAREAGENT_FIXTURE/bareagent-skill/plugin-manifest.json" <<'EOF'
{
  "name": "bareagent-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin with a bare-string agents[] entry (#73; harness defect 14).",
  "skills": [
    {
      "name": "bareagent-skill",
      "source": "."
    }
  ],
  "agents": ["not-an-object"],
  "commands": []
}
EOF

BAREAGENT_RC=0
run_sync "$SKILLS_HOME_BAREAGENT_FIXTURE" "$MONOREPO_BAREAGENT_FIXTURE" \
    "$SCRATCH_DIR/bareagent-stdout.log" "$SCRATCH_DIR/bareagent-stderr.log" || BAREAGENT_RC=$?
BAREAGENT_BOTH="$(cat "$SCRATCH_DIR/bareagent-stdout.log" "$SCRATCH_DIR/bareagent-stderr.log")"

# --- Assertions: defect 14. Verified red against the pre-fix build: the main
# sync loop died at `jq -r ".agents[0].name"` with rc=5 and a raw
# `jq: error (…): Cannot index string with "name"` as the only output, having
# never reached the auto-build stage where prepare-plugin.sh's friendly message
# lives. ---
assert_eq "a bare-string agents[] entry gives the documented exit-1 failure, not jq's rc=5" \
    "1" "$BAREAGENT_RC"
assert_contains "…with the same actionable message prepare-plugin.sh gives, from the loop that meets it first" \
    "ERROR: agent entry must be an object with 'name' and 'source', not a bare string: not-an-object" \
    "$BAREAGENT_BOTH"
assert_not_contains "…and no raw jq type error reaching the operator" \
    "Cannot index string with string \"name\"" "$BAREAGENT_BOTH"
assert_contains "…reported under its own reason, not as a build failure" \
    "bare-string agents[] entry: $SKILLS_HOME_BAREAGENT_FIXTURE/bareagent-skill/plugin-manifest.json" \
    "$BAREAGENT_BOTH"

# ------------------------------------------------------------------
# Defect 18 — the bare-agents guard must be fatal even when NO BUILD RUNS
# ------------------------------------------------------------------
#
# The first version of defect 14's guard set AGENT_COUNT=0 and left the run to
# the auto-build stage, on the stated grounds that "the very next stage runs
# prepare-plugin.sh against this same manifest, which exits 1 on it". That is
# false whenever the build does not run at all — prepare-plugin.sh is invoked
# only when _NEEDS_BUILD is true.
#
# This fixture is that case, and it is the NATURAL one: an already-published
# plugin gains `"agents": ["x"]` in its manifest while its SKILL.md is untouched,
# which is how anyone would add an agent to an existing plugin, in exactly the
# legacy bare-string form #73 exists to tolerate. The drift check compares
# SKILL.md versions, finds them identical, and never builds. Reproduced against
# the guard's first version: one ERROR line, "Sync complete. 1 skills synced",
# README/CHANGELOG/marketplace all regenerated, declared agents silently not
# copied, and rc=0 — a loudness REGRESSION, since before the guard existed the
# same manifest died at jq with rc=5 and wrote nothing.
#
# Three further paths `continue` before the build stage and would have bypassed
# the claimed net identically: the standalone-marketplace skip, the --add-plugin
# skip, and the shadowed-manifest skip. The published copy below is byte-identical
# to the source, which is what pins _NEEDS_BUILD false.
SKILLS_HOME_BAREPUB_FIXTURE="$SCRATCH_DIR/skills-home-barepub"
MONOREPO_BAREPUB_FIXTURE="$SCRATCH_DIR/monorepo-barepub"
mkdir -p "$SKILLS_HOME_BAREPUB_FIXTURE/barepub-skill" \
         "$MONOREPO_BAREPUB_FIXTURE/barepub-skill" \
         "$MONOREPO_BAREPUB_FIXTURE/plugins/barepub-plugin/.claude-plugin" \
         "$MONOREPO_BAREPUB_FIXTURE/plugins/barepub-plugin/skills/barepub-skill"

BAREPUB_SKILL_MD='---
name: barepub-skill
description: Throwaway fixture — already-published plugin whose manifest gains a bare agents[] entry (harness defect 18).
version: 1.0.0
---

# Barepub Skill'
printf '%s\n' "$BAREPUB_SKILL_MD" > "$SKILLS_HOME_BAREPUB_FIXTURE/barepub-skill/SKILL.md"
printf '%s\n' "$BAREPUB_SKILL_MD" > "$MONOREPO_BAREPUB_FIXTURE/barepub-skill/SKILL.md"
# Identical to the source: the drift check finds nothing, so no build is run and
# the auto-build stage never sees this manifest at all.
printf '%s\n' "$BAREPUB_SKILL_MD" > "$MONOREPO_BAREPUB_FIXTURE/plugins/barepub-plugin/skills/barepub-skill/SKILL.md"
cat > "$MONOREPO_BAREPUB_FIXTURE/plugins/barepub-plugin/.claude-plugin/plugin.json" <<'EOF'
{
  "name": "barepub-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin, already published and up to date."
}
EOF
cat > "$SKILLS_HOME_BAREPUB_FIXTURE/barepub-skill/plugin-manifest.json" <<'EOF'
{
  "name": "barepub-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin whose agents[] gained a bare string (harness defect 18).",
  "skills": [
    {
      "name": "barepub-skill",
      "source": "."
    }
  ],
  "agents": ["late-added-agent"],
  "commands": []
}
EOF

BAREPUB_RC=0
run_sync "$SKILLS_HOME_BAREPUB_FIXTURE" "$MONOREPO_BAREPUB_FIXTURE" \
    "$SCRATCH_DIR/barepub-stdout.log" "$SCRATCH_DIR/barepub-stderr.log" || BAREPUB_RC=$?
BAREPUB_STDOUT="$(cat "$SCRATCH_DIR/barepub-stdout.log")"
BAREPUB_STDERR="$(cat "$SCRATCH_DIR/barepub-stderr.log")"

# --- Assertions: defect 18. Verified red against the guard's first version
# (AGENT_COUNT=0 with no record kept): rc=0, "Sync complete. 1 skills synced",
# and README.md regenerated. ---
assert_eq "a bare agents[] entry is fatal even when the drift check runs no build" \
    "1" "$BAREPUB_RC"
assert_contains "…the per-manifest ERROR still names the offending entry" \
    "ERROR: agent entry must be an object with 'name' and 'source', not a bare string: late-added-agent" \
    "$BAREPUB_STDERR"
assert_contains "…and it reaches the collected-failure summary under its own reason" \
    "bare-string agents[] entry: $SKILLS_HOME_BAREPUB_FIXTURE/barepub-skill/plugin-manifest.json" \
    "$BAREPUB_STDERR"
assert_not_contains "…not miscategorised as a build failure, since no build ran" \
    "plugin build failed:" "$BAREPUB_STDERR"
assert_eq "…with the catalogue NOT regenerated on the way out" \
    "false" "$([[ -f "$MONOREPO_BAREPUB_FIXTURE/README.md" ]] && echo true || echo false)"
assert_not_contains "…and no \"Sync complete\" line claiming the run succeeded" \
    "Sync complete." "$BAREPUB_STDOUT"

# ------------------------------------------------------------------
# Defect 19 — the refusal summary must not claim work a --dry-run did not do
# ------------------------------------------------------------------
#
# The summary printed "plugin build failed" and "Skills synced before this point
# are already written" on every path it served. Under --dry-run over a manifest
# with an unreadable skills[], both are false: no build was attempted (the
# failure was a READ) and --dry-run wrote nothing at all. In a change set whose
# theme is that a message must not claim more than happened, that one did.
BADMANIFEST_DRYRUN_RC=0
run_sync "$SKILLS_HOME_BADMANIFEST_FIXTURE" "$MONOREPO_BADMANIFEST_FIXTURE" \
    "$SCRATCH_DIR/dryrun-stdout.log" "$SCRATCH_DIR/dryrun-stderr.log" \
    --dry-run || BADMANIFEST_DRYRUN_RC=$?
DRYRUN_STDERR="$(cat "$SCRATCH_DIR/dryrun-stderr.log")"

assert_eq "--dry-run over an unreadable manifest still refuses (the read happens either way)" \
    "1" "$BADMANIFEST_DRYRUN_RC"
assert_contains "…saying plainly that nothing was written" \
    "Nothing was written — this was a --dry-run." "$DRYRUN_STDERR"
assert_not_contains "…and not repeating the real run's \"already written\" claim" \
    "Skills synced before this point are already written" "$DRYRUN_STDERR"
assert_not_contains "…nor calling a read failure a build failure" \
    "plugin build failed:" "$DRYRUN_STDERR"

# --- Positive control: the goodmanifest fixture carries a WELL-FORMED agents[]
# entry, so a guard stuck ON is caught two ways — no ERROR may be printed on
# either stream, and the agent must actually reach the monorepo. The file
# assertion is the load-bearing half: the guard sets AGENT_COUNT=0, so a
# stuck-ON guard silently copies no agents at all while printing its ERROR to
# stderr where a stdout-only check never looks. ---
assert_not_contains "positive control: a well-formed agents[] entry draws no bare-string ERROR (both streams)" \
    "must be an object with 'name' and 'source'" "$GOODMANIFEST_BOTH"
assert_file_exists "…and the agent is actually copied into the monorepo, so the guard cannot be stuck ON" \
    "$MONOREPO_GOODMANIFEST_FIXTURE/goodmanifest-skill/agents/control-agent.md"
assert_contains "…with its real content, not an empty file" \
    "GOODMANIFEST-AGENT-MARKER" \
    "$(cat "$MONOREPO_GOODMANIFEST_FIXTURE/goodmanifest-skill/agents/control-agent.md" 2>/dev/null || true)"

# ------------------------------------------------------------------
# Defect 13 — the failure record must survive its own reporting
# ------------------------------------------------------------------
#
# A `/` in the manifest's `.name` puts a directory separator in $_BUILD_LOG's
# path, so the `>"$_BUILD_LOG"` redirect fails (its parent does not exist), the
# build is treated as failed, and the `sed` that reports it fails too.
#
# NOTE: rc is 1 both before and after the fix and is therefore NOT the
# discriminator — pre-fix the run dies from `set -e` on the failed sed, which
# also happens to exit 1. The discriminator is whether the collected-failure
# SUMMARY prints: pre-fix the run is dead before `_FAILED_BUILDS=` is assigned,
# so the "names every broken manifest in one pass" line never appears at all.
cat > "$SKILLS_HOME_SLASHLOG_FIXTURE/slashlog-skill/SKILL.md" <<'EOF'
---
name: slashlog-skill
description: Throwaway fixture skill whose manifest name contains a slash (#73; harness defect 13).
version: 1.0.0
---

# Slash Log Skill
EOF
cp "$SKILLS_HOME_SLASHLOG_FIXTURE/slashlog-skill/SKILL.md" \
   "$MONOREPO_SLASHLOG_FIXTURE/slashlog-skill/SKILL.md"
cat > "$SKILLS_HOME_SLASHLOG_FIXTURE/slashlog-skill/plugin-manifest.json" <<'EOF'
{
  "name": "slash/name",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin whose name carries a slash (#73; harness defect 13).",
  "skills": [
    {
      "name": "slashlog-skill",
      "source": "."
    }
  ],
  "commands": []
}
EOF

SLASHLOG_RC=0
run_sync "$SKILLS_HOME_SLASHLOG_FIXTURE" "$MONOREPO_SLASHLOG_FIXTURE" \
    "$SCRATCH_DIR/slashlog-stdout.log" "$SCRATCH_DIR/slashlog-stderr.log" || SLASHLOG_RC=$?
SLASHLOG_STDERR="$(cat "$SCRATCH_DIR/slashlog-stderr.log")"
SLASHLOG_MANIFEST="$SKILLS_HOME_SLASHLOG_FIXTURE/slashlog-skill/plugin-manifest.json"

# --- Assertions: defect 13. Verified red against the pre-fix build: the
# per-manifest "ERROR: prepare-plugin.sh failed for …" line printed, then the
# sed failed and set -e killed the run — so the collected-failure summary below
# was absent from stderr entirely. ---
assert_eq "a manifest name containing a slash still ends the run at exit 1" \
    "1" "$SLASHLOG_RC"
assert_contains "…the per-manifest failure line still prints" \
    "ERROR: prepare-plugin.sh failed for $SLASHLOG_MANIFEST" "$SLASHLOG_STDERR"
assert_contains "…and the collected-failure summary survives the sed that cannot read its own log" \
    "plugin build failed:        $SLASHLOG_MANIFEST" "$SLASHLOG_STDERR"

# ============================================================
# Adversarial round (#91 R1): incompleteness in the issues this PR closes
# ============================================================
#
#  20. #77's fatal `else` covered one of two branches. It is nested inside
#      `[[ -n "$HOOKS_SRC" ]] && [[ != null ]]`, so it only ever caught a source
#      that was PRESENT and unresolvable. A `hooks` object with no `source` KEY
#      — the plausible typo `{"src": "./hooks"}` — makes `.hooks.source` yield
#      null, fails that test, and fell off the end with no else: exit 0, no
#      hooks copied, `--- Hooks ---` printed anyway so the log read as if they
#      had been, and `rsync -a --delete` then removed the published hooks/.
#      `.hooks | has("source")` separates the two intents jq collapses into one
#      null: `{"source": null}` and `{"source": ""}` stay legal no-ops (a
#      deliberate design decision, not an oversight), while a missing key is
#      refused. The header now prints only for a branch that does something.
#
#  21. #79 forwarded --github-user and not --author, on the same command line.
#      `--author "Jane Doe"` put "Jane Doe" in the monorepo LICENSE and
#      marketplace owner.name, and "Abhishek" in every auto-built plugin's own
#      LICENSE — #79's "one run, two identities" verbatim, in a distributed MIT
#      licence. prepare-plugin.sh accepts exactly four flags; three are now
#      forwarded and --dry-run deliberately is not, because the child is never
#      invoked under --dry-run at all.
#
#  22. #78 fixed skill RESOLUTION but not DISCOVERY: validate-pre-sync.sh still
#      enumerated the monorepo only, so a skill living solely in $SKILLS_HOME
#      was structurally invisible — which is every `sync-monorepo.sh --add
#      <new-skill>`, the highest-risk case for the mismatch this gate exists to
#      catch. It now accepts `--add`, mirroring the sync flag whose shape it
#      cannot otherwise see. Named skills are unioned in rather than
#      enumerating all of $SKILLS_HOME: a gate that fails on unrelated local
#      work is a gate people stop running.
#
#  23. `--add` round-tripped the machine-discovered list through a comma-joined
#      string, which is lossy for a directory name containing a comma — the
#      same "names are unconstrained free text" premise #81 rests on. Only the
#      user-typed value is comma-split now.
#
#  24. #37/#102: _lib.sh's extract_field read `description:` as raw text, so the
#      generated plugin README carried whatever YAML syntax the author had
#      written — a bare `>-` for a folded scalar, literal `\"` for a
#      double-quoted one, and (unfiled) a plain scalar's leading quote eaten by
#      an unconditional strip. One awk parser now decodes every scalar style.

# ------------------------------------------------------------------
# Defect 20 — a hooks object with no source key
# ------------------------------------------------------------------
mkdir -p "$PREPARE_FIXTURE_DIR/hookstypo-plugin" "$PREPARE_FIXTURE_DIR/hooksnull-plugin"

cat > "$PREPARE_FIXTURE_DIR/hookstypo-plugin/SKILL.md" <<'EOF'
---
name: hookstypo-plugin
description: Throwaway fixture — manifest declares hooks with a misspelled key (harness defect 20).
version: 0.1.0
---

# hookstypo-plugin
EOF
cat > "$PREPARE_FIXTURE_DIR/hookstypo-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "hookstypo-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture whose hooks object misspells 'source' (harness defect 20).",
  "skills": [{ "name": "hookstypo-plugin", "source": "." }],
  "hooks": { "src": "./hooks" },
  "commands": []
}
EOF

# The control that keeps #77's deliberate no-ops intact: an EXPLICIT null source
# is "no hooks, on purpose" and must still build cleanly. Without this, a fix
# that simply errored on any falsy hooks source would satisfy every assertion
# below while reversing a design decision.
cat > "$PREPARE_FIXTURE_DIR/hooksnull-plugin/SKILL.md" <<'EOF'
---
name: hooksnull-plugin
description: Throwaway fixture — hooks.source explicitly null, a deliberate no-op (harness defect 20 control).
version: 0.1.0
---

# hooksnull-plugin
EOF
cat > "$PREPARE_FIXTURE_DIR/hooksnull-plugin/plugin-manifest.json" <<'EOF'
{
  "name": "hooksnull-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture with an explicitly null hooks source (harness defect 20 control).",
  "skills": [{ "name": "hooksnull-plugin", "source": "." }],
  "hooks": { "source": null },
  "commands": []
}
EOF

HOOKSTYPO_RC=0
run_prepare hookstypo-plugin "$SCRATCH_DIR/hookstypo.stdout" "$SCRATCH_DIR/hookstypo.stderr" || HOOKSTYPO_RC=$?
HOOKSTYPO_STDOUT="$(cat "$SCRATCH_DIR/hookstypo.stdout")"
HOOKSTYPO_STDERR="$(cat "$SCRATCH_DIR/hookstypo.stderr")"

# --- Verified red against the pre-fix build: rc=0, "--- Hooks ---" present,
# no ERROR anywhere, and a plugin assembled with no hooks/ that rsync --delete
# would then strip from the published copy. ---
assert_eq "a hooks object with no 'source' key is refused, not silently skipped" \
    "1" "$HOOKSTYPO_RC"
assert_contains "…naming the malformed value so the typo is visible" \
    "ERROR: 'hooks' is declared but carries no 'source' key: {\"src\":\"./hooks\"}" \
    "$HOOKSTYPO_STDERR"
assert_contains "…and pointing at the deliberate way to say \"no hooks\"" \
    'Use {"source": null} to declare "no hooks" deliberately.' "$HOOKSTYPO_STDERR"
assert_not_contains "…with no \"--- Hooks ---\" header for a branch that copied nothing" \
    "--- Hooks ---" "$HOOKSTYPO_STDOUT"

HOOKSNULL_RC=0
run_prepare hooksnull-plugin "$SCRATCH_DIR/hooksnull.stdout" "$SCRATCH_DIR/hooksnull.stderr" || HOOKSNULL_RC=$?
HOOKSNULL_STDOUT="$(cat "$SCRATCH_DIR/hooksnull.stdout")"
assert_eq "control: an EXPLICIT null hooks source stays a legal no-op and still builds" \
    "0" "$HOOKSNULL_RC"
assert_not_contains "…drawing no missing-source error" \
    "carries no 'source' key" "$(cat "$SCRATCH_DIR/hooksnull.stderr")"
assert_not_contains "…and printing no Hooks header either, since it copied nothing" \
    "--- Hooks ---" "$HOOKSNULL_STDOUT"
assert_file_exists "…while still producing a plugin" \
    "$PREPARE_OUT_DIR/hooksnull-plugin/.claude-plugin/plugin.json"

# ------------------------------------------------------------------
# Defect 21 — --author must reach the auto-built plugin's LICENSE
# ------------------------------------------------------------------
#
# Asserted on the two LICENSEs written by DIFFERENT writers: the monorepo's is
# written by sync-monorepo.sh directly, the plugin's by prepare-plugin.sh as a
# child. Only the second could disagree, so asserting the first alone would
# pass against the unfixed build.
SKILLS_HOME_AUTHOR_FIXTURE="$SCRATCH_DIR/skills-home-author"
MONOREPO_AUTHOR_FIXTURE="$SCRATCH_DIR/monorepo-author"
mkdir -p "$SKILLS_HOME_AUTHOR_FIXTURE/author-skill" "$MONOREPO_AUTHOR_FIXTURE"
cat > "$SKILLS_HOME_AUTHOR_FIXTURE/author-skill/SKILL.md" <<'EOF'
---
name: author-skill
description: Throwaway fixture backing the --author forwarding check (harness defect 21).
version: 1.0.0
---

# Author Skill
EOF
cat > "$SKILLS_HOME_AUTHOR_FIXTURE/author-skill/plugin-manifest.json" <<'EOF'
{
  "name": "author-plugin",
  "version": "1.0.0",
  "description": "Throwaway fixture plugin for the --author forwarding check (harness defect 21).",
  "skills": [{ "name": "author-skill", "source": "." }],
  "commands": []
}
EOF

AUTHOR_RC=0
(
    cd "$RUN_CWD"
    PATH="$GH_DRAIN_SHIM_DIR:$PATH" \
    SKILLS_HOME="$SKILLS_HOME_AUTHOR_FIXTURE" \
        "$SYNC_SCRIPT" --github-user harness-fixture-user \
                       --author "Harness Author" "$MONOREPO_AUTHOR_FIXTURE"
) >"$SCRATCH_DIR/author-stdout.log" 2>"$SCRATCH_DIR/author-stderr.log" </dev/null || AUTHOR_RC=$?

# --- Verified red against the pre-fix build: the monorepo LICENSE said
# "Harness Author" while the plugin's said "Abhishek" — one run, two identities,
# in a distributed MIT licence. ---
assert_eq "the --author run completes" "0" "$AUTHOR_RC"
assert_contains "the monorepo LICENSE carries the requested author (the parent's own writer)" \
    "Harness Author" "$(cat "$MONOREPO_AUTHOR_FIXTURE/LICENSE" 2>/dev/null || true)"
assert_contains "…and so does the auto-built plugin's LICENSE, written by the child" \
    "Harness Author" \
    "$(cat "$MONOREPO_AUTHOR_FIXTURE/plugins/author-plugin/LICENSE" 2>/dev/null || true)"
assert_not_contains "…with no trace of prepare-plugin.sh's hardcoded default" \
    "Abhishek" "$(cat "$MONOREPO_AUTHOR_FIXTURE/plugins/author-plugin/LICENSE" 2>/dev/null || true)"

# ------------------------------------------------------------------
# Defect 22 — validate-pre-sync.sh must be able to see an --add target
# ------------------------------------------------------------------
PRESYNC_ADD_HOME_FIXTURE="$SCRATCH_DIR/presync-add-home"
PRESYNC_ADD_MONOREPO_FIXTURE="$SCRATCH_DIR/presync-add-monorepo"
mkdir -p "$PRESYNC_ADD_HOME_FIXTURE/presync-brandnew" \
         "$PRESYNC_ADD_HOME_FIXTURE/presync-addok" \
         "$PRESYNC_ADD_HOME_FIXTURE/presync-onrepo" \
         "$PRESYNC_ADD_MONOREPO_FIXTURE/presync-onrepo"

# In $SKILLS_HOME only, and MISMATCHED: v2.0.0 against a CHANGELOG topping out
# at 1.0.0. This is exactly what `sync-monorepo.sh --add presync-brandnew`
# would publish.
cat > "$PRESYNC_ADD_HOME_FIXTURE/presync-brandnew/SKILL.md" <<'EOF'
---
name: presync-brandnew
description: Throwaway fixture — home-only skill with a mismatched CHANGELOG (harness defect 22).
version: 2.0.0
---

# Presync Brandnew
EOF
cat > "$PRESYNC_ADD_HOME_FIXTURE/presync-brandnew/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Deliberately older than SKILL.md — this must be REPORTED, not skipped.
EOF

# Same shape, CHANGELOG matching: the control that catches a --add which fails
# everything it is handed.
cat > "$PRESYNC_ADD_HOME_FIXTURE/presync-addok/SKILL.md" <<'EOF'
---
name: presync-addok
description: Throwaway fixture — home-only skill whose CHANGELOG matches (harness defect 22 control).
version: 1.0.0
---

# Presync Addok
EOF
cat > "$PRESYNC_ADD_HOME_FIXTURE/presync-addok/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Matches SKILL.md.
EOF

PRESYNC_ONREPO_MD='---
name: presync-onrepo
description: Throwaway fixture — already in the monorepo, enumerated with or without --add.
version: 1.0.0
---

# Presync Onrepo'
printf '%s\n' "$PRESYNC_ONREPO_MD" > "$PRESYNC_ADD_HOME_FIXTURE/presync-onrepo/SKILL.md"
printf '%s\n' "$PRESYNC_ONREPO_MD" > "$PRESYNC_ADD_MONOREPO_FIXTURE/presync-onrepo/SKILL.md"
cat > "$PRESYNC_ADD_HOME_FIXTURE/presync-onrepo/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Matches SKILL.md.
EOF

PRESYNC_NOADD_RC=0
run_presync "$PRESYNC_ADD_HOME_FIXTURE" "$PRESYNC_ADD_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-noadd.stdout" "$SCRATCH_DIR/presync-noadd.stderr" || PRESYNC_NOADD_RC=$?
PRESYNC_NOADD_STDOUT="$(cat "$SCRATCH_DIR/presync-noadd.stdout")"

# Baseline: WITHOUT --add the home-only skills are correctly out of scope. This
# is not the defect — a discovery-driven sync would not touch them either — and
# asserting it pins that the fix is opt-in rather than a blanket widening.
assert_eq "without --add, only the monorepo's own skills are enumerated" \
    "1" "$(presync_total "$PRESYNC_NOADD_STDOUT")"
assert_eq "…and that run is clean" "0" "$PRESYNC_NOADD_RC"

PRESYNC_ADD_RC=0
run_presync "$PRESYNC_ADD_HOME_FIXTURE" "$PRESYNC_ADD_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-add.stdout" "$SCRATCH_DIR/presync-add.stderr" \
    --add presync-brandnew || PRESYNC_ADD_RC=$?
PRESYNC_ADD_STDOUT="$(cat "$SCRATCH_DIR/presync-add.stdout")"

# --- Verified red against the pre-fix build, which had no --add at all:
# "Total: 1 | Pass: 1 | Fail: 0 … Safe to sync." at rc=0, immediately before
# `sync-monorepo.sh --add presync-brandnew` published the mismatch. ---
assert_eq "--add lets the gate see a skill that is not in the monorepo yet" \
    "1" "$PRESYNC_ADD_RC"
assert_eq "…enumerating it alongside the monorepo's own" \
    "2" "$(presync_total "$PRESYNC_ADD_STDOUT")"
assert_line_present "…and reporting its version/CHANGELOG mismatch by name" \
    "FAIL  presync-brandnew — SKILL.md says v2.0.0 but CHANGELOG latest is v1.0.0" \
    "$PRESYNC_ADD_STDOUT"
assert_not_contains "…so the \"Safe to sync\" banner does not print over it" \
    "Safe to sync" "$PRESYNC_ADD_STDOUT"

PRESYNC_ADDOK_RC=0
run_presync "$PRESYNC_ADD_HOME_FIXTURE" "$PRESYNC_ADD_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-addok.stdout" "$SCRATCH_DIR/presync-addok.stderr" \
    --add presync-addok || PRESYNC_ADDOK_RC=$?
assert_eq "control: --add of a skill whose CHANGELOG matches still exits 0" \
    "0" "$PRESYNC_ADDOK_RC"
assert_eq "…with both skills examined" \
    "2" "$(presync_total "$(cat "$SCRATCH_DIR/presync-addok.stdout")")"

# `--add ,` must fail loudly rather than degrade to a no-op. The emptiness test
# is on the ADD-contributed names, not the union: a union test looks equivalent
# and is not, because the monorepo scan keeps the union non-empty. Caught in
# this fix's own first draft, where `--add ,` silently validated nothing extra
# and still printed "Safe to sync".
PRESYNC_ADDCOMMA_RC=0
run_presync "$PRESYNC_ADD_HOME_FIXTURE" "$PRESYNC_ADD_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-addcomma.stdout" "$SCRATCH_DIR/presync-addcomma.stderr" \
    --add , || PRESYNC_ADDCOMMA_RC=$?
assert_eq "--add with only separators is a usage error, not a silent no-op" \
    "2" "$PRESYNC_ADDCOMMA_RC"
assert_contains "…naming the offending argument" \
    "Error: --add produced no skill names from: ','" \
    "$(cat "$SCRATCH_DIR/presync-addcomma.stderr")"

# Same for an EMPTY value, which the `-n "$ADD_SKILLS"` gate skipped wholesale:
# the run came out identical to one with no --add, "Total: 1", rc=0.
#
# rc IS a valid discriminator on THIS fixture, unlike a naive one: the baseline
# run above asserts rc=0 / Total 1 and the control asserts rc=0 / Total 2, so
# every skill here genuinely passes validation and rc=0 is reachable. On a
# fixture whose skills lack CHANGELOGs, validate-pre-sync returns 1 for every
# case including the controls, and an rc assertion would pass for the wrong
# reason. Total is asserted alongside rc for the same reason.
PRESYNC_ADDEMPTY_RC=0
run_presync "$PRESYNC_ADD_HOME_FIXTURE" "$PRESYNC_ADD_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-addempty.stdout" "$SCRATCH_DIR/presync-addempty.stderr" \
    --add "" || PRESYNC_ADDEMPTY_RC=$?
PRESYNC_ADDEMPTY_STDOUT="$(cat "$SCRATCH_DIR/presync-addempty.stdout")"
assert_eq "--add with an EMPTY value is a usage error here too" \
    "2" "$PRESYNC_ADDEMPTY_RC"
assert_contains "…naming the empty argument" \
    "Error: --add produced no skill names from: ''" \
    "$(cat "$SCRATCH_DIR/presync-addempty.stderr")"
assert_eq "…and producing no report, rather than one identical to a no-flag run" \
    "" "$(presync_total "$PRESYNC_ADDEMPTY_STDOUT")"

# ------------------------------------------------------------------
# Defect 24 — the report is DATA, not a printf format string
# ------------------------------------------------------------------
#
# `printf "$RESULTS"` interpreted the accumulated report as a format string, so
# a skill directory named `pct%s-skill` was reported as `pct-skill` — the `%s`
# consumed as a conversion, and the operator told a directory name that does
# not exist on disk. Pre-existing, but #78 tripled what flows through here by
# making in-repo-source skills reportable at all. `printf '%b'` keeps the `\n`
# expansion the RESULTS strings rely on and stops interpreting data as format.
#
# Its own monorepo, because every presync fixture above pins exact Total counts
# and adding a fourth skill to any of them would mean rewriting another
# defect's evidence to carry this one.
PRESYNC_PCT_HOME_FIXTURE="$SCRATCH_DIR/presync-pct-home"
PRESYNC_PCT_MONOREPO_FIXTURE="$SCRATCH_DIR/presync-pct-monorepo"
mkdir -p "$PRESYNC_PCT_HOME_FIXTURE/pct%s-skill" "$PRESYNC_PCT_MONOREPO_FIXTURE/pct%s-skill"
PCT_SKILL_MD='---
name: pct%s-skill
description: Throwaway fixture whose directory name contains a printf conversion (harness defect 24).
version: 1.0.0
---

# Pct Skill'
printf '%s\n' "$PCT_SKILL_MD" > "$PRESYNC_PCT_HOME_FIXTURE/pct%s-skill/SKILL.md"
printf '%s\n' "$PCT_SKILL_MD" > "$PRESYNC_PCT_MONOREPO_FIXTURE/pct%s-skill/SKILL.md"
cat > "$PRESYNC_PCT_HOME_FIXTURE/pct%s-skill/CHANGELOG.md" <<'EOF'
# Changelog

## [1.0.0] - 2026-01-01

Matches SKILL.md.
EOF

PRESYNC_PCT_RC=0
run_presync "$PRESYNC_PCT_HOME_FIXTURE" "$PRESYNC_PCT_MONOREPO_FIXTURE" \
    "$SCRATCH_DIR/presync-pct.stdout" "$SCRATCH_DIR/presync-pct.stderr" || PRESYNC_PCT_RC=$?
PRESYNC_PCT_STDOUT="$(cat "$SCRATCH_DIR/presync-pct.stdout")"

# --- Verified red against the pre-fix build: `PASS  pct-skill v1.0.0`. ---
assert_eq "a skill whose name contains a printf conversion validates cleanly" \
    "0" "$PRESYNC_PCT_RC"
assert_line_present "…and is reported under its real on-disk name" \
    "PASS  pct%s-skill v1.0.0" "$PRESYNC_PCT_STDOUT"
assert_not_contains "…not with the conversion silently consumed" \
    "PASS  pct-skill" "$PRESYNC_PCT_STDOUT"

# ------------------------------------------------------------------
# Defect 23 — a comma in a DISCOVERED directory name
# ------------------------------------------------------------------
#
# The --add branch joined the discovered list with `tr '\n' ','` and split it
# back apart, so a directory legitimately named `alpha,beta` became two names,
# neither of which resolves. The new per-name --add guard cannot catch it: it
# checks only $ADD_SKILL-contributed names and trusts the discovered list by
# construction — correctly, since that list was intact until the join mangled it.
SKILLS_HOME_COMMA_FIXTURE="$SCRATCH_DIR/skills-home-comma"
MONOREPO_COMMA_FIXTURE="$SCRATCH_DIR/monorepo-comma"
mkdir -p "$SKILLS_HOME_COMMA_FIXTURE/alpha,beta" \
         "$SKILLS_HOME_COMMA_FIXTURE/comma-newcomer" \
         "$MONOREPO_COMMA_FIXTURE/alpha,beta"
COMMA_SKILL_MD='---
name: alpha,beta
description: Throwaway fixture skill whose directory name contains a comma (harness defect 23).
version: 1.0.0
---

# Alpha,Beta'
printf '%s\n' "$COMMA_SKILL_MD" > "$SKILLS_HOME_COMMA_FIXTURE/alpha,beta/SKILL.md"
printf '%s\n' "$COMMA_SKILL_MD" > "$MONOREPO_COMMA_FIXTURE/alpha,beta/SKILL.md"
cat > "$SKILLS_HOME_COMMA_FIXTURE/comma-newcomer/SKILL.md" <<'EOF'
---
name: comma-newcomer
description: Throwaway fixture skill brought in by --add alongside a comma-named sibling (harness defect 23).
version: 1.0.0
---

# Comma Newcomer
EOF

COMMA_RC=0
run_sync "$SKILLS_HOME_COMMA_FIXTURE" "$MONOREPO_COMMA_FIXTURE" \
    "$SCRATCH_DIR/comma-stdout.log" "$SCRATCH_DIR/comma-stderr.log" \
    --add comma-newcomer || COMMA_RC=$?
COMMA_STDOUT="$(cat "$SCRATCH_DIR/comma-stdout.log")"
COMMA_README="$(cat "$MONOREPO_COMMA_FIXTURE/README.md" 2>/dev/null || true)"

# --- Verified red against the pre-fix build: "Skills to sync (4)" listing
# alpha / beta / comma-newcomer, two "no SKILL.md" ERRORs, "Sync complete. 2",
# a 2-row catalogue, and `alpha,beta/` still on disk but absent from the
# published catalogue at rc=0. ---
assert_eq "--add alongside a comma-named skill exits 0" "0" "$COMMA_RC"
assert_line_present "…the comma-named skill survives discovery as ONE name" \
    "alpha,beta" "$(synced_names "$COMMA_STDOUT")"
assert_line_absent "…not split into a bogus first fragment" \
    "alpha" "$(synced_names "$COMMA_STDOUT")"
assert_line_absent "…nor a bogus second fragment" \
    "beta" "$(synced_names "$COMMA_STDOUT")"
assert_not_contains "…and no name fails to resolve" "ERROR: no SKILL.md" "$COMMA_STDOUT"
assert_eq "…both skills are synced, not just the --add target" \
    "2" "$(sync_complete_count "$COMMA_STDOUT")"
assert_eq "…with both catalogue rows written" \
    "2" "$(skill_catalog_row_count "$MONOREPO_COMMA_FIXTURE/README.md")"
assert_contains "…including the comma-named skill's own row, whole" \
    "| [alpha,beta](./alpha,beta/) |" "$COMMA_README"

# ------------------------------------------------------------------
# Defect 24 — YAML scalar styles leaking into the generated README
# ------------------------------------------------------------------
#
# One fixture plugin per scalar style, each built by the real prepare-plugin.sh.
# The description is read at two INDEPENDENT sites — FULL_DESC feeds
# "## What It Does" (prepare-plugin.sh:420/522) and SDESC feeds the "### Skills"
# list (prepare-plugin.sh:462/466) — so both are asserted; a partial fix that
# closed one read would otherwise pass.
#
# Every style is asserted in BOTH directions. A negative alone
# (assert_not_contains ">-") is satisfied identically by a working parser and by
# one that returns the empty string, so each style also carries a positive
# control: a distinctive ALL-CAPS marker that can only appear in the README if
# the scalar was decoded correctly.
#
# The bare-row assertions are the guard for prepare-plugin.sh:464/504
# (`[[ -n "$SDESC_SHORT" && "$SDESC_SHORT" != "." ]]`): on an empty parse those
# take the else branch and emit `- \`name\`` with no description at all — a
# silent degradation nothing else in this suite catches. Asserting the row whole,
# em-dash and text included, is what makes an empty parse fail rather than pass
# quietly.
mkdir -p "$PREPARE_FIXTURE_DIR/foldedscalar-plugin" \
         "$PREPARE_FIXTURE_DIR/dquotescalar-plugin" \
         "$PREPARE_FIXTURE_DIR/squotescalar-plugin" \
         "$PREPARE_FIXTURE_DIR/plainscalar-plugin" \
         "$PREPARE_FIXTURE_DIR/plainregress-plugin"

# #37: a folded block scalar carries no text on its key line.
cat > "$PREPARE_FIXTURE_DIR/foldedscalar-plugin/SKILL.md" <<'EOF'
---
name: foldedscalar-skill
description: >-
  FOLDED-SCALAR-MARKER — a description written as a folded block scalar that
  spans two source lines. Use when: (1) the generator folds it into one line.
version: 0.1.0
---

# foldedscalar-skill
EOF

# #102: a double-quoted scalar whose internal quotes are backslash-escaped.
cat > "$PREPARE_FIXTURE_DIR/dquotescalar-plugin/SKILL.md" <<'EOF'
---
name: dquotescalar-skill
description: "DQUOTE-SCALAR-MARKER — phrases like \"review this\" and \"converge to zero\" must survive intact. Use when: (1) the generator decodes a double-quoted scalar."
version: 0.1.0
---

# dquotescalar-skill
EOF

# The third scalar style. YAML's only single-quote escape is a doubled quote,
# which the old reader never collapsed because it only ever stripped the outer
# pair.
cat > "$PREPARE_FIXTURE_DIR/squotescalar-plugin/SKILL.md" <<'EOF'
---
name: squotescalar-skill
description: 'SQUOTE-SCALAR-MARKER — it''s a single-quoted scalar, kept whole. Use when: (1) the doubled quote collapses to one.'
version: 0.1.0
---

# squotescalar-skill
EOF

# The unfiled defect: a PLAIN scalar that merely opens with a quote. The old
# `s/^["']//` fired unconditionally and ate it. Note the correct output CONTAINS
# the mangled output as a substring, so this one is asserted on whole lines —
# assert_not_contains would go red against the fix as well as against the bug.
cat > "$PREPARE_FIXTURE_DIR/plainscalar-plugin/SKILL.md" <<'EOF'
---
name: plainscalar-skill
description: "PLAIN-OPENQUOTE-MARKER" stays whole when the scalar is plain. Use when: (1) nothing is stripped.
version: 0.1.0
---

# plainscalar-skill
EOF

# Regression control, and deliberately NOT a fail-first assertion: an ordinary
# plain scalar must read identically before and after the parser swap. It passes
# against both builds by design — that is what "unchanged" means — so it is the
# one fixture here whose green result proves nothing about the fix and
# everything about what the fix did not disturb. 42 of the 44 SKILL.md
# descriptions in this repo are this shape.
cat > "$PREPARE_FIXTURE_DIR/plainregress-plugin/SKILL.md" <<'EOF'
---
name: plainregress-skill
description: PLAINREGRESS-MARKER — an ordinary plain scalar with no quoting at all. Use when: (1) plain-scalar output is unchanged.
version: 0.1.0
---

# plainregress-skill
EOF

for _sc in foldedscalar dquotescalar squotescalar plainscalar plainregress; do
    cat > "$PREPARE_FIXTURE_DIR/$_sc-plugin/plugin-manifest.json" <<EOF
{
  "name": "$_sc-plugin",
  "version": "0.1.0",
  "description": "Throwaway fixture plugin exercising one YAML description scalar style (harness defect 24).",
  "skills": [ { "name": "$_sc-skill", "source": "." } ],
  "commands": []
}
EOF
done

SCALAR_FOLDED_RC=0
run_prepare foldedscalar-plugin "$SCRATCH_DIR/scalar-folded.stdout" \
    "$SCRATCH_DIR/scalar-folded.stderr" || SCALAR_FOLDED_RC=$?
SCALAR_FOLDED_README="$(cat "$PREPARE_OUT_DIR/foldedscalar-plugin/README.md" 2>/dev/null || true)"

SCALAR_DQUOTE_RC=0
run_prepare dquotescalar-plugin "$SCRATCH_DIR/scalar-dquote.stdout" \
    "$SCRATCH_DIR/scalar-dquote.stderr" || SCALAR_DQUOTE_RC=$?
SCALAR_DQUOTE_README="$(cat "$PREPARE_OUT_DIR/dquotescalar-plugin/README.md" 2>/dev/null || true)"

SCALAR_SQUOTE_RC=0
run_prepare squotescalar-plugin "$SCRATCH_DIR/scalar-squote.stdout" \
    "$SCRATCH_DIR/scalar-squote.stderr" || SCALAR_SQUOTE_RC=$?
SCALAR_SQUOTE_README="$(cat "$PREPARE_OUT_DIR/squotescalar-plugin/README.md" 2>/dev/null || true)"

SCALAR_PLAIN_RC=0
run_prepare plainscalar-plugin "$SCRATCH_DIR/scalar-plain.stdout" \
    "$SCRATCH_DIR/scalar-plain.stderr" || SCALAR_PLAIN_RC=$?
SCALAR_PLAIN_README="$(cat "$PREPARE_OUT_DIR/plainscalar-plugin/README.md" 2>/dev/null || true)"

SCALAR_REGRESS_RC=0
run_prepare plainregress-plugin "$SCRATCH_DIR/scalar-regress.stdout" \
    "$SCRATCH_DIR/scalar-regress.stderr" || SCALAR_REGRESS_RC=$?
SCALAR_REGRESS_README="$(cat "$PREPARE_OUT_DIR/plainregress-plugin/README.md" 2>/dev/null || true)"

# --- Verified red against the pre-fix build: the folded README's "What It Does"
# read ">-" and its skills row was "- `foldedscalar-skill` — >-"; the
# double-quoted and single-quoted READMEs carried \" and '' verbatim; and the
# plain-scalar row had lost its leading quote. All five builds exited 0 both
# before and after, so rc is a run-level control here, not the discriminator. ---

assert_eq "the folded-scalar fixture builds" "0" "$SCALAR_FOLDED_RC"
assert_eq "the double-quoted-scalar fixture builds" "0" "$SCALAR_DQUOTE_RC"
assert_eq "the single-quoted-scalar fixture builds" "0" "$SCALAR_SQUOTE_RC"
assert_eq "the plain-open-quote fixture builds" "0" "$SCALAR_PLAIN_RC"
assert_eq "the plain-scalar regression fixture builds" "0" "$SCALAR_REGRESS_RC"

# --- #37, folded ---
assert_contains "a folded description is folded into the README's What It Does" \
    "FOLDED-SCALAR-MARKER — a description written as a folded block scalar that spans two source lines." \
    "$SCALAR_FOLDED_README"
assert_line_present "…and into its skills row, whole" \
    '- `foldedscalar-skill` — FOLDED-SCALAR-MARKER — a description written as a folded block scalar that spans two source lines.' \
    "$SCALAR_FOLDED_README"
assert_not_contains "…with no raw block-scalar indicator left anywhere in the README" \
    ">-" "$SCALAR_FOLDED_README"
assert_line_absent "…and the skills row is not the descriptionless fallback" \
    '- `foldedscalar-skill`' "$SCALAR_FOLDED_README"

# --- #102, double-quoted ---
assert_contains "a double-quoted description reaches What It Does unescaped" \
    'DQUOTE-SCALAR-MARKER — phrases like "review this" and "converge to zero" must survive intact.' \
    "$SCALAR_DQUOTE_README"
assert_line_present "…and its skills row, whole" \
    '- `dquotescalar-skill` — DQUOTE-SCALAR-MARKER — phrases like "review this" and "converge to zero" must survive intact.' \
    "$SCALAR_DQUOTE_README"
assert_not_contains "…with no literal backslash-quote sequence surviving" \
    '\"' "$SCALAR_DQUOTE_README"
assert_line_absent "…and the skills row is not the descriptionless fallback" \
    '- `dquotescalar-skill`' "$SCALAR_DQUOTE_README"

# --- single-quoted ---
assert_contains "a single-quoted description reaches What It Does with '' collapsed" \
    "SQUOTE-SCALAR-MARKER — it's a single-quoted scalar, kept whole." \
    "$SCALAR_SQUOTE_README"
assert_line_present "…and its skills row, whole" \
    "- \`squotescalar-skill\` — SQUOTE-SCALAR-MARKER — it's a single-quoted scalar, kept whole." \
    "$SCALAR_SQUOTE_README"
assert_not_contains "…with no doubled single quote surviving" \
    "it''s" "$SCALAR_SQUOTE_README"
assert_line_absent "…and the skills row is not the descriptionless fallback" \
    '- `squotescalar-skill`' "$SCALAR_SQUOTE_README"

# --- unfiled: a plain scalar that opens with a quote ---
assert_contains "a plain scalar opening with a quote keeps it in What It Does" \
    '"PLAIN-OPENQUOTE-MARKER" stays whole when the scalar is plain.' \
    "$SCALAR_PLAIN_README"
assert_line_present "…and its skills row keeps it too" \
    '- `plainscalar-skill` — "PLAIN-OPENQUOTE-MARKER" stays whole when the scalar is plain.' \
    "$SCALAR_PLAIN_README"
assert_line_absent "…not the row an unconditional leading-quote strip produces" \
    '- `plainscalar-skill` — PLAIN-OPENQUOTE-MARKER" stays whole when the scalar is plain.' \
    "$SCALAR_PLAIN_README"
assert_line_absent "…and not the descriptionless fallback either" \
    '- `plainscalar-skill`' "$SCALAR_PLAIN_README"

# --- regression control (green before AND after the fix, by design) ---
assert_contains "control: an ordinary plain scalar is unchanged in What It Does" \
    "PLAINREGRESS-MARKER — an ordinary plain scalar with no quoting at all." \
    "$SCALAR_REGRESS_README"
assert_line_present "control: …and unchanged in its skills row" \
    '- `plainregress-skill` — PLAINREGRESS-MARKER — an ordinary plain scalar with no quoting at all.' \
    "$SCALAR_REGRESS_README"
assert_line_absent "control: …and never degraded to the descriptionless fallback" \
    '- `plainregress-skill`' "$SCALAR_REGRESS_README"

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
