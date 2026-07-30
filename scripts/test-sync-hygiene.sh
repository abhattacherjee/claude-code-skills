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
#      `rm -rf`s on entry — and echoed to stderr on failure. The run still exits
#      0: that is a separate defect, tracked as #73, deliberately unchanged here.
#   9. The .gitignore template fix (defect 3) reaches freshly --init-ed monorepos
#      only. write_file does not overwrite, so an already-published monorepo gets
#      "SKIP    .gitignore (already exists)" — indistinguishable from "already
#      correct" — and no signal that it lacks the rule. A non-fatal NOTE now says
#      so, naming the pattern to add.
#
# The whole run is hermetic: two throwaway SKILLS_HOMEs and nine throwaway
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
# nine runs and leave every other assertion reading around it.
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
# AUTO-SYNCED / ERROR lines into all nine runs above and perturb their counts.
SKILLS_HOME_HOOKS_FIXTURE="$SCRATCH_DIR/skills-home-hooks"
MONOREPO_HOOKS_FIXTURE="$SCRATCH_DIR/monorepo-hooks"

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

# ============================================================
# Sync invocations
# ============================================================
#
# Nine runs, all from the same throwaway cwd:
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
# Run 7 is the only one expected to exit non-zero. An ADD_SKILL that reduces to
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
# so a broken manifest in the shared home would print into all nine runs.
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
# names a skill source that does not exist. prepare-plugin.sh exits 1; the sync
# warns and carries on to a clean exit 0 (that part is #73's, not this harness's).
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

# Run 11: the forced rebuild, with hooks-src gone. Expected to exit 0 — the
# sync layer's existing "warn and keep going" handling for a failed auto-build
# (proven by run 8's BUILDFAIL fixture) is deliberately left alone here; #73's
# hard-failure behaviour is out of scope for this task.
HOOKS2_STDOUT_LOG="$SCRATCH_DIR/hooks2.stdout"
HOOKS2_STDERR_LOG="$SCRATCH_DIR/hooks2.stderr"
HOOKS2_RC=0
run_sync "$SKILLS_HOME_HOOKS_FIXTURE" "$MONOREPO_HOOKS_FIXTURE" "$HOOKS2_STDOUT_LOG" "$HOOKS2_STDERR_LOG" || HOOKS2_RC=$?
HOOKS2_STDOUT="$(cat "$HOOKS2_STDOUT_LOG")"
HOOKS2_STDERR="$(cat "$HOOKS2_STDERR_LOG")"

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
assert_eq "--skills -n run exits 0 on the fixture" "0" "$SKILLSN_RC"
assert_eq "--add -n run exits 0 on the fixture" "0" "$ADDN_RC"
assert_eq "failing-auto-build run exits 0 on the fixture" "0" "$BUILDFAIL_RC"
assert_eq "pre-existing-.gitignore run exits 0 on the fixture" "0" "$GITIGNORE_RC"
assert_eq "hooks no-ops + positive-control run exits 0 on the fixture" "0" "$HOOKS_RC"
assert_eq "hooks forced-rebuild-failure run exits 0 on the fixture (soft warn, #73 out of scope)" "0" "$HOOKS2_RC"

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
# /dev/null. Asserted on that line's *content*: a Warning that says "failed" and
# nothing else is precisely the undiagnosable state this closes.

assert_contains "control: the auto-build failure path actually ran" \
    "Warning: prepare-plugin.sh failed for" "$BUILDFAIL_STDOUT"

assert_line_present "the failing child's own error line reaches the operator" \
    "    |   ERROR: skill source not found: $BROKEN_SKILL_SOURCE" "$BUILDFAIL_STDERR"

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
# run down under `set -e` with an empty stderr — rc=1 and no clue why. This is
# the only run in this harness expected to fail; the assertions are about the
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
assert_file_exists "positive control: hooks-ok-plugin's hooks/ was copied" \
    "$MONOREPO_HOOKS_FIXTURE/plugins/hooks-ok-plugin/hooks/pre-tool-use.sh"

# None of the four no-op/positive-control builds may have errored.
HOOKS_ERROR_LINES=$(printf '%s\n%s\n' "$HOOKS_STDOUT" "$HOOKS_STDERR" | grep 'ERROR' || true)
assert_eq "no ERROR line from the run-10 hooks fixtures" "" "$HOOKS_ERROR_LINES"

# Run 11: hooks-src is gone and the SKILL.md version bump forced a rebuild
# attempt. The child must refuse — matching the skills/commands/agents
# siblings' error shape — and the sync layer must surface that refusal rather
# than reporting success.
assert_contains "control: run 11 actually attempted to rebuild hooks-ok-plugin" \
    "Warning: prepare-plugin.sh failed for" "$HOOKS2_STDOUT"
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

for _hp in hooks-none-plugin hooks-null-plugin hooks-empty-plugin hooks-ok-plugin; do
    _hp_readme="$(cat "$MONOREPO_HOOKS_FIXTURE/plugins/$_hp/README.md" 2>/dev/null || true)"
    assert_contains "plugins/$_hp/README.md carries the forwarded --github-user" \
        "harness-fixture-user" "$_hp_readme"
    assert_not_contains "plugins/$_hp/README.md does not fall back to USERNAME" \
        "USERNAME" "$_hp_readme"
done

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
