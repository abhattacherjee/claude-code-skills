# Changelog

All notable changes to this project will be documented in this file.

## [4.3.0] - 2026-07-30

Minor, not patch. Five of the six defects below share one shape — a write path that
reported success while not doing its job — and closing them introduces new
**refusals**: `prepare-plugin.sh` and `sync-monorepo.sh` invocations that previously
exited `0` while quietly skipping work now exit `1`. Anything scripted against a `0`
from those paths needs re-checking before upgrading.

### Fixed

- `prepare-plugin.sh` silently skipped a declared `hooks.source` that does not resolve
  to a directory: the existence check had no `else`, unlike its skills/commands/agents
  siblings, which all error and exit. The plugin was then assembled with no `hooks/`,
  and `sync-monorepo.sh`'s `rsync -a --delete` removed the previously published `hooks/`
  from `plugins/<name>/`. A declared, non-empty source that does not exist is now a
  manifest error. `hooks` absent from the manifest, and `hooks.source` explicitly
  `null`/empty, both remain legal no-ops.

  **This is a latent guardrail in this repo, not the repair of an active breakage.**
  All 14 `plugin-manifest.json` files on the authoring machine were audited and none
  declares `hooks.source`, so nothing here was losing hooks. It protects other repos
  that use this tooling and do ship hooks. (#77)

- `sync-monorepo.sh`'s plugin auto-build stage invoked `prepare-plugin.sh` without
  `--github-user`, so the child re-derived the value itself via `gh api user` and fell
  back to the literal string `USERNAME` when unauthenticated. One run could therefore
  advertise two different accounts — the parent's resolved user in the monorepo README
  and `USERNAME` in every auto-built plugin's own README. `GITHUB_USER` is resolved well
  before that stage, so it is now forwarded. Side effect: one fewer `gh` call per sync,
  making the run less network-dependent. (#79)

- A legacy manifest declaring its skills as bare strings (`"skills": ["name"]`) rather
  than objects killed every one of `prepare-plugin.sh`'s eight `.skills[…]` reads with
  `jq: error … Cannot index string with "name"`, and `sync-monorepo.sh` read the same
  shape at two sites under `2>/dev/null` — so its reversion guard saw no skills to check
  and its drift check saw no first skill, and the plugin was never rebuilt at all. The
  "never rebuilt at all" class is **not fully closed**: `custom-statusline` still is not,
  for the unrelated reason filed as **#92** — the drift detectors resolve a plugin's skills
  by `name` while `prepare-plugin.sh` resolves them by `source`, so a manifest whose two
  disagree stays permanently drift-blind. Pre-existing, and out of scope here, but do not
  read this entry as shutting the class. The
  manifest is now shape-normalised once into a temp copy that every read is pointed at
  (`normalize_manifest()` in `_lib.sh`), with `MANIFEST_DIR` deliberately left pointing
  at the *original* manifest's directory so relative `source` values still resolve; the
  two sync-side reads go through `manifest_skill_names()`. A bare string in `commands[]`
  or `agents[]` is refused rather than guessed at — those sources are files, so `"."`
  has no defensible meaning. And a failed plugin auto-build is now fatal: the run reports
  every broken manifest in one pass and exits `1` before any catalogue-regenerating
  stage, rather than warning and going on to publish a README, CHANGELOG and marketplace
  entry describing a plugin it could not build.

  **Consequence worth stating plainly:** `github-release-board-promote` — the only real
  legacy-shape manifest — has no `plugins/` directory and no marketplace entry today. It
  was never published *at all*, not merely left stale. With the tooling fixed, the next
  real sync run will publish it for the first time and add a new marketplace entry. This
  release does not do that; publishing it is a separate, deliberate act. (#73)

- `validate-pre-sync.sh` hardcoded each skill's source as `$SKILLS_HOME/<name>` and
  `continue`d when that path had no `SKILL.md` — counting the skill as neither examined
  nor failed, i.e. as a pass. Every skill whose only source is its in-repo directory was
  therefore never validated, while the summary still printed "Safe to sync". It now
  resolves through the same `skill_source_dir()` the sync uses, hoisted from
  `sync-monorepo.sh` into `_lib.sh` so there is one definition of "where does this
  skill's source live" instead of two that can disagree. A skill with no source anywhere
  is still skipped rather than failed, but the skip is now announced on stderr instead of
  being silent. Its `for SKILL_NAME in $SKILLS` loop was converted line-wise at the same
  time (see #81 below). (#78)

- `--skills` resolving to zero names republished an empty catalogue, silently. A value
  that is nothing but separators (`--skills ,`) produced no names at all, exited `0`, and
  regenerated the monorepo README with an empty catalogue table plus a CHANGELOG entry
  claiming "Synced 0 skills"; `--skills nosuchskill` printed one inline `ERROR: no
  SKILL.md` line and then did the same destructive rewrite. `discover_skills()` now
  refuses the first case by name, and a second guard sited immediately after the main
  sync loop — ahead of the plugin auto-build, which `rsync --delete`s into `plugins/` —
  refuses the second. A discovery-driven run against a monorepo that genuinely contains
  no skills is deliberately exempt and still exits `0`. `--add` and `--skills` are now
  rejected as mutually exclusive rather than one silently winning, since the guard cannot
  otherwise tell which flag's value it is refusing. (#80)

- Unquoted `for` iteration over newline-delimited lists IFS-split any skill or plugin
  name containing a space into fragments, none of which resolved. `filter_skill_candidates`
  correctly accepted `my skill` as one entry; the loop then produced two loud `ERROR:` lines
  and a closing summary that still claimed the full count had synced, with `rc=0`. All five
  sites in `sync-monorepo.sh` — the main sync loop, the plugin reversion-guard check, the
  plugin catalogue loop, the install-all command builder and the CHANGELOG skill inventory —
  are now `while IFS= read -r … done <<< "$LIST"`, here-strings rather than pipes so the
  loops keep assigning in the current shell.

  The closing summary, the CHANGELOG's "Synced N skills" entry, and the `--init` commit
  message now report the number of skills that actually resolved *and* were copied —
  resolved minus refused — rather than the number discovered or requested. The README's
  `{{SKILL_COUNT}}` (both the templated and no-template-fallback paths) instead reports the
  number resolved, refusals included: a skill refused by the reversion guard still keeps its
  catalogue row (built from the in-repo metadata, before the refusal `continue`), so that
  figure has to match the catalogue's actual row count rather than how many were freshly
  copied. The CHANGELOG's skill-inventory list likewise still lists a refused skill — it
  didn't leave the monorepo, it just wasn't recopied this run — now annotated `(REFUSED —
  stale local source, not synced this run)` so it doesn't read as a silent contradiction
  next to a "Synced 0 skills" entry. Only the pre-loop "Skills to sync (N):" line keeps the
  requested count, because it is a plan rather than a claim about what happened. (#81)

- **The line-wise conversion above introduced a truncation the old `for` loops could not
  have.** `done <<< "$LIST"` binds the list to the loop *body's* stdin, and those bodies
  shell out to `gh`, `rsync`, `cp`, `diff`, `find`, `jq`, `sed` and `grep`. Any child that
  reads stdin consumes the rest of the skill list; the loop then exits early having synced
  only what it read, and reports success. The count fix above makes that self-consistent —
  `{{SKILL_COUNT}}` is `SKILLS_RESOLVED_COUNT`, which counts the loop's own iterations — so
  the catalogue, the published count and the CHANGELOG inventory all agree with each other
  while the rest of the catalogue silently disappears. Demonstrated with a `gh` shim that
  drains stdin: a three-skill monorepo synced **one** skill, rewrote the README to a single
  catalogue row, and exited `0`.

  Latent in production only because the real `gh repo view --json url` happens not to read
  stdin — a property of today's `gh`, not a guarantee. All five sites in `sync-monorepo.sh`
  and the one in `validate-pre-sync.sh` now bind the list to **fd 3** (`read … <&3` /
  `done 3<<<`), leaving the body's stdin inherited from the caller so no child can reach
  the list at all. Only the main sync loop and the plugin-catalogue loop have
  stdin-consuming children today; the other four are defence in depth, and the regression
  harness's mutants report that honestly rather than claiming a fail-first at all six. The
  `marketplace.json` builder is now on fd 3 too — its `< <(find …)` is the loop body's
  stdin exactly as a here-string is, and it is the one such loop that actually spawns
  children (`dirname`, three `jq`s per iteration), so exempting it would have applied the
  rule everywhere except where it most obviously belongs.

  **fd 3 is a convention, not a barrier, and the comment saying otherwise was wrong.** It
  claimed "no child can reach the list at all"; descriptors are inherited across `exec`, so
  a child that deliberately reads `<&3` consumes the list exactly as a stdin-reading child
  did — measured: a 4-line list drove 2 iterations when the body read one line from fd 3.
  What fd 3 actually buys is that stdin is read by filters *by nature* while nothing reads
  fd 3 unless written to. Every one of those loops therefore also runs its body with
  `</dev/null`, which is the half that IS unconditional: every child gets immediate EOF, so
  the reachable case is closed rather than merely made unlikely. It also removes the one
  downside of moving the list off stdin — the body would otherwise inherit the caller's
  stdin, turning a truncation into a hang on an interactive terminal. `--help` states both
  halves and which one is load-bearing. (#81)

- The `marketplace.json` builder — the only one of the eight converted loops reached through
  a process substitution, and the last converted — had no control, so a botched conversion
  of it was invisible. Reverting `3< <(…)` to `< <(…)` writes an empty `"plugins": []` and
  exits 0, silently emptying the marketplace catalogue while the sole existing assertion
  (file exists) stays green, because the file is written and merely empty. Measured: that
  mutant passed all 279 assertions. Now asserted on contents, not existence. (#81)

- **Process note, recorded because it caught a fifth instance.** Four half-true safety
  comments shipped on this branch, and twice the correction produced another. The shape is
  mechanical: an absolute — "no", "never", "always", "still", "only", "cannot" — describing
  a property that is actually conditional. Grepping this branch's own added comment lines
  for those words and testing each against a counterexample found one more that had
  survived review: "`_UNREADABLE_MANIFESTS` is the only one of the three a `--dry-run` can
  produce". It is not — `_BARE_ENTRY_MANIFESTS` is too, since the main sync loop's guard is
  not gated on `DRY_RUN` either, verified by running a `--dry-run` over an already-published
  plugin with `"agents": ["x"]` and getting exit 1. Two further absolutes were tightened in
  the same pass. The check is cheap and belongs in review, not in hindsight. (#81)

- **The line-wise conversion above had a sixth site with no test coverage at all.** It is
  described everywhere as five sites in `sync-monorepo.sh`; the sixth is
  `validate-pre-sync.sh`'s own skill loop, converted by the same issue but in a different
  task, after which the space-name fixtures were built entirely sync-side. Reverting *that
  loop alone* to `for SKILL_NAME in $SKILLS` left the regression harness fully green. No
  behaviour changed here — the loop was already correct — but a correct loop with no test
  is one refactor away from being an incorrect one, and this is the first N-1-of-N on this
  work that crossed a file boundary rather than sitting inside one. Now covered by a third
  presync fixture with space-named skills on both sides of the report. (#81)

- The plugin auto-build stage's `manifest_skill_names … 2>/dev/null || true` was documented
  as keeping "the pre-existing tolerance of an unreadable manifest". Only half true: the
  base commit had *two* reads, and only one was tolerant. The reversion guard's was a
  command substitution in a `for` word-list, which does not trip `set -e`; the drift
  check's was an **assignment**, which did. Consolidating both onto one tolerant read
  silently downgraded the second from fatal to skipped, on the destructive path — with the
  name list empty the reversion guard cannot fire, so a plugin is rebuilt from the stale
  local source the main loop just refused and `rsync -a --delete`'d over the published
  copy under an `AUTO-SYNCED` line; and an already-published plugin is never rebuilt at
  all. Reachable via `"skills": [123]`, which makes `jq` exit 5 while the `.name` read
  earlier in the same stage succeeds on the same file, so nothing catches it first. A
  failed read is now recorded as a build failure and joins the collected-failure exit,
  relaying `jq`'s own message. (#73)

- The collected-failure record was written *after* a command that can abort. `_BUILD_LOG`
  is named from the manifest's `.name`, which is free text; a `/` in it makes the log
  redirect fail, so the `sed` that reports the failure fails too, and `set -e` killed the
  run before `_FAILED_BUILDS=` was ever assigned — losing the point of collecting failures,
  since the summary naming every broken manifest in one pass never printed. The assignment
  now precedes the `sed`, and the `sed` carries `|| true`: reporting a failure must not be
  able to destroy the record of it. (#73)

- The bare-entry rejection added to `prepare-plugin.sh` above landed there only, and
  `sync-monorepo.sh`'s main sync loop runs **first** — so a manifest carrying
  `"agents": ["x"]` killed the sync at `jq -r ".agents[$ai].name"` with a raw
  `jq: error … Cannot index string with "name"` and rc=5, and the friendly explanation
  never printed because the run never reached the auto-build stage. The same
  `manifest_bare_entries` check, with the same message text, now runs in the main loop too,
  scoped to `agents[]` — the only array that loop indexes. (#73)

- **That bare-entry guard was itself non-fatal, and its own comment's safety net did not
  hold.** It set `AGENT_COUNT=0` and left the run to the auto-build stage, on the stated
  grounds that "the very next stage runs `prepare-plugin.sh` against this same manifest,
  which exits 1 on it" — false whenever no build runs, since `prepare-plugin.sh` is invoked
  only when the drift check sets `_NEEDS_BUILD`. Adding `"agents": ["x"]` to an
  already-published plugin's manifest without touching its `SKILL.md` — the natural way to
  add an agent, in exactly the legacy bare-string form this batch exists to tolerate —
  therefore printed one `ERROR`, copied no agents, regenerated README/CHANGELOG/marketplace
  and exited **0**. Three further paths `continue` before the build stage and bypassed it
  identically: the standalone-marketplace skip, the `--add-plugin` skip and the
  shadowed-manifest skip. A loudness **regression**: before the guard existed, the same
  manifest died at `jq` with rc=5 — ugly, but fatal, and nothing downstream was written.
  Now collected and exited on through the shared refusal gate, which also moved out of the
  `[[ -x "$PREPARE_SCRIPT" ]]` block — two of its three lists are filled inside that block
  but the third is not, so nesting it there let a missing `prepare-plugin.sh` disarm the
  bare-entry refusal. (#73)

- The refusal summary claimed more than had happened on two of the three paths it now
  serves: it said `plugin build failed` for a manifest whose `skills[]` merely could not be
  **read** (no build was attempted), and "Skills synced before this point are already
  written" under `--dry-run`, which writes nothing. Each reason now has its own labelled
  row, and the `--dry-run` path says plainly that nothing was written. In a change set
  whose theme is that a message must not claim more than happened, this one did. (#73)

- `manifest_skill_names`' stderr is captured separately instead of via `2>&1`. On the
  **success** path that variable *is* the skill-name list, feeding the reversion guard and
  the drift check's first skill; a diagnostic accompanying a zero exit would become a
  phantom skill name, which resolves nowhere, so the drift check falls through and the
  plugin is silently never rebuilt — #73 re-entering through its own fix. No such warning
  is reachable for this filter today, so this is hardening rather than a repair, and it
  carries no regression assertion for that reason: asserting a condition the code cannot
  reach passes vacuously and reads as coverage. (#73)

- `--add <unresolvable>` against a **populated** monorepo printed one inline
  `ERROR: no SKILL.md` and exited `0` having regenerated the README, CHANGELOG and
  marketplace — the same shape closed above for `--skills`, on the flag that is the
  documented way to introduce a new skill. That guard cannot catch it: it fires only when
  *every* name fails to resolve, and a populated monorepo always contributes resolvable
  ones through the existing-directory scan. `discover_skills()` now rejects any
  `--add`-contributed name with no `SKILL.md`, before anything is written, splitting on
  commas so a legitimate `--add a,b` is unaffected. (#80, closes #85)

- The `--skills` branch used `sort` where the `--add` branch used `sort -u`, under a
  comment claiming it mirrored `--add`. `--skills alpha,alpha` therefore synced one skill
  twice: two `--- alpha ---` stanzas, two identical catalogue rows, two identical `cp -r`
  lines published as install instructions, and a doubled count in the summary, the README
  and the CHANGELOG — every figure agreeing with every other, so nothing flagged it.
  Now `sort -u`. (#80)

### Changed

- Exit-status contract, now documented in `--help`:
  `0` success; `1` usage/setup error — including a `--skills` value that resolves to no
  valid skill, or an `--add` value naming a skill with no `SKILL.md` — or a failed plugin
  auto-build, or a manifest whose `skills[]` cannot be read; `3` completed, but skills were
  refused by the reversion guard. `1` wins over `3`: a run that both refused a skill and
  failed a build stops at the build failure, so the end-of-run refusal summary never
  prints. `--dry-run` cannot predict a `1` from a failed *build*, because plugins are not
  assembled at all under `--dry-run`; it does predict a `3`, a bad `--skills`/`--add`
  value, and an unreadable manifest (that read happens whether or not a build follows).

- `--skills` and `--add` are refused on different thresholds, deliberately. `--skills` is
  refused only when *every* named skill fails to resolve — a partial resolution is a
  legitimate run. `--add` is refused when *any* name it contributes fails, because `--add`
  names are typed to introduce a skill, so an unresolvable one is a typo rather than a
  subset. (#80)

- **`--skills` rewrites the published catalogue to exactly the named subset.** Skills left
  out stay on disk but lose their catalogue row, their place in the skill count and their
  CHANGELOG inventory entry until the next full sync. This is long-standing behaviour, now
  stated plainly in `SKILL.md` — an earlier draft of that documentation promised `--skills`
  would not "publish an empty/partial catalogue", which was true only of the empty half.
  Use `--add` to introduce one skill without disturbing the rest. (#80)

- **`SKILL.md`'s Quick Reference now states the `--skills`/`--add` asymmetry rather than
  asserting parity.** The fix for the "partial catalogue" overclaim above introduced a
  different false claim in its place — "both refuse an unresolvable name rather than
  publish" — when in fact `--skills good,typo` exits 0 and publishes a one-row catalogue
  while `--add good,typo` exits 1 and writes nothing. Someone trusting the shorter claim
  could run `--skills prod-skill,typo-skll` expecting a safe refusal and publish a silently
  shrunk catalogue instead. The correct asymmetry was already right in `--help` and in the
  entry above; it simply had not propagated to the line users skim. Third pass on the same
  sentence, so the whole block was re-read for the same shape — assertions of symmetry,
  universality or guarantee over a conditional implementation — rather than patching the
  one clause. The de-duplication half was verified true for both flags and kept. (#80)

## [4.2.1] - 2026-07-26

### Fixed

- `sync-monorepo.sh` treated every top-level directory in the monorepo as a skill, so
  directories that exist for other reasons — `docs/`, `build/` — entered the sync loop and
  produced a spurious `ERROR: no SKILL.md ...` line on every run. Both directory-scan sites
  in `discover_skills()` now filter through `filter_skill_candidates()` — the plain scan,
  and the `--add` branch's `existing=` scan, which runs only when `--add` is passed — each
  applying the same test `skill_source_dir()` does and announcing what it dropped on stderr
  instead of discarding it silently. The filter emits through `printf` rather than `echo`,
  so a directory named `-n`/`-e`/`-E` cannot be eaten by `echo`'s option parsing and vanish
  without even a SKIP line. (#74)
- The plugin auto-build stage assembled each plugin into `./build/<name>` in the *caller's*
  working directory, so a sync run from the monorepo root left an untracked `build/` tree
  behind — which the script's own "Next steps: `git add -A`" banner would then commit.
  Builds now go into a `mktemp -d` stage removed by an EXIT trap, passed through to
  `prepare-plugin.sh` via `--output-dir`. (#74)
- The `.gitignore` template written into a freshly `--init`-ed monorepo did not list
  `build/`, so every newly generated monorepo shipped with the same defect. The pattern is
  written root-anchored as `/build/`: unanchored, it matches at every depth, so a plugin
  that legitimately ships a `build/` subdirectory would be silently excluded from the very
  `git add -A` the ignore rule exists to protect. (#74)
- The CHANGELOG-parsing step read its first line via `echo "$ALL_ENTRIES" | head -1`.
  `head` exits after one line, so `echo` races it and takes EPIPE once the entry text is
  well past the 64 KiB pipe buffer. With the auto-build EXIT trap now registered, bash no
  longer leaves SIGPIPE at its default disposition in the command-substitution subshell —
  the trap does not itself run there — so `echo`'s failed write is reported rather than
  silently killing it: `echo: write error: Broken pipe` on stderr. It is a write/reader
  race, not a hard threshold: measured 0/50 reproductions below 64 KiB, ~53% at 84 KiB and
  10/10 at 154 KiB, so it reproduces reliably well past the buffer. Replaced with a
  parameter expansion; generated output is byte-identical. (#74)
- `Skills to sync (N)` counted an empty list as 1 and printed a bare `  - ` bullet,
  because `echo ""` emits a newline for `wc -l` to count. Newly reachable now that
  discovery filters non-skill directories: a monorepo holding only `docs/` and `build/`
  yields an empty list. (#74)
- The two remaining `echo` sites in `discover_skills()` ate a skill whose name begins
  `-n`/`-e`/`-E`, the same class the filter fix above closed. `--skills -n` printed
  `Skills to sync (0):`, synced nothing and still exited 0 — a silent no-op; `--add -n`
  into a monorepo with no skills yet (the only case where the comma-join leaves the bare
  name as the whole argument) produced no output at all, so the trailing `grep -v '^$'`
  exited 1 and aborted the run under `set -e` with nothing on stderr to explain it. Both
  now emit through `printf`. (#74)
- The `--add -n` fix above cured the cause, not the shape: an `--add` argument that
  reduces to nothing after comma-splitting (e.g. the literal argument `,`) still left the
  trailing `grep -v '^$'` with nothing to match, so it still exited 1 and still aborted
  the run under `set -e` — rc=1, empty stderr, no explanation. `discover_skills()` now
  checks for that empty result itself and exits with `Error: --add produced no skill
  names from: '<value>'` naming the offending argument, instead of letting `grep`'s exit
  status propagate unexplained. (#74)
- A failed plugin auto-build was undiagnosable. `prepare-plugin.sh` ran under
  `>/dev/null 2>&1`, and on failure the only output was
  `Warning: prepare-plugin.sh failed for <manifest>`. That was survivable while the build
  stage was `./build/<name>/` in the caller's cwd — the partial tree stayed behind to
  inspect and re-run by hand — but the temp-stage fix above deletes the stage on every
  path including this one, leaving the discarded child output as the only evidence a
  failure ever produced. The child's stdout and stderr are now captured to a log and
  echoed to stderr, prefixed, when the build fails. The log lives in the stage root
  rather than inside the build directory, which `prepare-plugin.sh` `rm -rf`s on entry —
  a log written there would be unlinked out from under the open descriptor and read back
  empty. The run still exits 0: that is a separate defect, tracked as #73, and is
  deliberately unchanged here. (#74)
- The `.gitignore` template fix above reaches a freshly `--init`-ed monorepo only.
  `write_file` does not overwrite, so every already-published monorepo takes the
  `SKIP    .gitignore (already exists)` branch instead — a line that reads exactly the
  same whether the existing file carries the rule or not, so the fix reached nobody who
  already had a monorepo and said nothing about it. A non-fatal `NOTE` now names the
  missing `/build/` pattern and why it matters (the `git add -A` in the script's own
  Next-steps banner). Advisory only: the file belongs to the monorepo, and refusing to
  sync over a hand-edited `.gitignore` would be a worse failure than the untracked
  `build/` tree it warns about. (#74)
- The manifest-shadowing lookup read `$_SEEN_MANIFESTS` through an `awk` that `exit`s on
  first match — the same early-exiting-reader shape as the `| head -1` removed above, and
  likewise evaluated with the auto-build EXIT trap already registered, the condition that
  turns a silent SIGPIPE into a reported `write error: Broken pipe`. The payload is a few
  KiB at this repo's scale, far below the 64 KiB pipe buffer, so it could not fire; the
  reader now drains its input (`$1==n && !f {print $2; f=1}`, first-match-wins preserved)
  so it cannot start to. (#74)

## [4.2.0] - 2026-07-25

### Fixed

- `prepare-plugin.sh` resolved a relative manifest `source` against the caller's working
  directory, so a manifest whose source lives beside it — the in-repo arrangement #59
  introduced — only assembled when invoked from exactly the right cwd. Relative sources now
  resolve against the manifest file's own directory. `~`-prefixed and absolute sources are
  unchanged. (#61)
- `sync-monorepo.sh` looked for every skill's source under `$SKILLS_HOME` only. Once a
  skill's local copy is removed in favour of an in-repo source directory, drift went
  undetected and the plugin quietly served stale content while the source looked updated.
  Discovery, auto-build and drift-resync now fall back to `$MONOREPO_DIR/<name>`, and a
  same-directory source is skipped rather than copied onto itself. (#61)
- `copy_file` now returns early when source and destination are the same file (device +
  inode comparison, so symlink/hardlink aliases count too). Previously `cp a a` failed and,
  under `set -e`, aborted the entire sync mid-run — reachable for an in-repo skill whose
  manifest declares agents, since the agents-copy block runs for in-place sources. (#61)
- `resolve_source_path` no longer resolves an empty `"source": ""` to the manifest's own
  directory; it returns empty so callers report "source not found" as they did before the
  relative-source change. (#61)

### Added

- Manifest-schema documentation for the in-repo `source` form and its resolution rule. (#61)
- Reversion guard in `sync-monorepo.sh`: source resolution is local-first, so a stale local
  copy left behind after a skill moved into the monorepo silently overwrote newer in-repo
  content with older content — and then rebuilt the plugin from the reverted source, exiting
  0. A skill whose in-repo `SKILL.md` version is strictly newer than the local one (semver
  comparison via `sort -V`) is now REFUSED with both paths and both versions named, skipped
  in both the main sync loop and the plugin auto-build, and reported in a closing summary
  with exit status 3. Equal versions with differing content still sync forward (with a
  note); an unknown or unparseable version never refuses. `--force-local` overrides. (#61)
- Reversion guard now covers the plugin auto-resync stage as well, closing the path that
  mattered most: the resync resolved its own sources through the same local-first lookup and
  copied `SKILL.md`, `scripts/`, `references/`, the skill `CHANGELOG.md` and the plugin-root
  `CHANGELOG.md` of a refused skill straight into `plugins/<name>/` — the copy installers
  actually receive — so a run announced its refusal and then reverted the shipped plugin
  anyway, leaving `marketplace.json` advertising a version the artifact no longer was. Its
  drift detection is guarded too, so a refused skill alone no longer opens a resync at all,
  and the root-CHANGELOG skill inventory is now read from the in-repo copy rather than
  recording a version the monorepo never received. Refused skills are skipped individually,
  so a plugin whose other skills legitimately drifted still resyncs those. (#61)

### Changed

- `sync-monorepo.sh` skips the `git-flow` manifest during plugin discovery: that plugin is
  distributed via its own standalone marketplace (`abhattacherjee/git-flow`), not this
  monorepo. Previously shipped but undocumented.

## [4.1.0] - 2026-03-17

### Added

- **Team mode note** — when Agent Teams are enabled and publishing multiple skills, each skill's validation + sync can be assigned to a separate teammate for parallel processing

## [4.0.0] - 2026-03-13

### Changed (BREAKING)

- **Plugin-first publishing** — plugins are now the default distribution format. Every skill with a `plugin-manifest.json` is auto-assembled and synced as a plugin during `sync-monorepo.sh`. Bare skills (without manifests) remain supported as a secondary path.
- **`sync-monorepo.sh` auto-discovers plugins** — scans `$SKILLS_HOME/*/plugin-manifest.json` during regular sync, runs `prepare-plugin.sh` automatically, and syncs built plugins to `plugins/`. The `--add-plugin` flag is now a manual override, no longer required for known plugins.
- **SKILL.md rewritten for plugin-first** — frontmatter, architecture, interactive publishing flow, and key decisions table all updated to reflect plugins as primary, bare skills as secondary, individual repos as optional.
- **Target selection defaults to Plugin** when a `plugin-manifest.json` exists (previously defaulted to Bare Skill)
- **Quick Reference reordered** — monorepo sync (auto-discovers plugins) listed first, manual plugin commands second, individual repo last

### Added

- **Auto-build on drift** — `sync-monorepo.sh` detects when plugin source skills have changed and rebuilds the plugin automatically, with README preservation
- **Manifest creation prompt** — when publishing a skill without a `plugin-manifest.json`, the flow now suggests creating a minimal manifest with a JSON template

## [3.6.0] - 2026-03-06

### Added

- **`scripts/validate-pre-sync.sh`** — mandatory pre-sync gate that verifies each skill's CHANGELOG.md has an entry matching its SKILL.md version. Exits non-zero on mismatch, blocking sync until fixed. Supports `--fix` (remediation guidance) and `--json` (machine-readable) modes.
- **Step 4: Pre-Sync Validation (MANDATORY GATE)** — new step in the Interactive Publishing Flow. Runs `validate-pre-sync.sh` before `sync-monorepo.sh` and blocks if any skill's CHANGELOG is behind its version.
- **Step 6: Monorepo Release (MANDATORY)** — after every sync that changes skill content, ALWAYS create a monorepo release. No longer optional/ask-the-user. Includes bump level decision table.

### Changed

- **Interactive Publishing Flow** — renumbered from 5 steps to 7 steps: added Step 4 (pre-sync validation) and Step 6 (mandatory release). Previous "Post-Publish" is now Step 7.
- **Quick Reference** — added `validate-pre-sync.sh` commands

### Fixed

- **Changelog drift on publish** — previously, syncing a skill with a bumped SKILL.md version but stale CHANGELOG.md went undetected. The new validation gate makes this impossible.
- **Optional monorepo releases** — previously, the post-publish step "asked whether to create a release", making it easy to skip. Releases are now mandatory after content changes.

## [3.5.1] - 2026-03-05

### Fixed

- **Plugin CHANGELOG sync** — `sync-monorepo.sh` now syncs CHANGELOGs from source skills to plugin copies during auto-resync. Previously, plugin CHANGELOGs were preserved (stale) while bare-skill CHANGELOGs were updated, causing version history drift.
- **CHANGELOG drift detection** — Added CHANGELOG diff check to the plugin drift detection phase, so CHANGELOG-only changes trigger a resync
- **`--add-plugin` path** — No longer preserves stale plugin CHANGELOGs; only README is preserved (CHANGELOGs come from source skill)

## [3.5.0] - 2026-02-28

### Added

- **Auto GitHub releases** — `release-monorepo.sh` now creates a GitHub release (via `gh release create`) after pushing the tag, with categorized commit summary and skill/plugin inventory. Falls back gracefully if `gh` CLI fails.
- **Auto plugin resync** — `sync-monorepo.sh` now detects when plugin copies of SKILL.md, scripts/, references/, or agents/ have drifted from their source skills and patches them automatically during sync. Eliminates the silent plugin-content-drift problem.

### Changed

- **SKILL.md** — version bumped to 3.5.0
- **plugin-manifest.json** — version bumped to 3.5.0

## [3.4.0] - 2026-02-28

### Added

- **Agent auto-discovery in bare skill sync** — `sync-monorepo.sh` now detects agent files referenced in SKILL.md (via `agents/*.md` path patterns) and copies them from `~/.claude/agents/` into the monorepo alongside their skills
- **Plugin CHANGELOG preservation** — `sync-monorepo.sh` preserves both README.md and CHANGELOG.md in plugin destinations during `--add-plugin` rsync, preventing overwrite of hand-written content

### Fixed

- **Bare-bones CHANGELOG enrichment** — when a plugin's CHANGELOG only has a template entry, it's replaced with the source skill's CHANGELOG content during sync

## [3.3.0] - 2026-02-28

### Added

- **Rich plugin README generation** — `prepare-plugin.sh` now extracts What It Does, Key Features, Usage, See Also, Prerequisites, and agent/command descriptions from SKILL.md frontmatter and headings. Plugin READMEs are now informative without hand-editing.

### Changed

- **Contents section enhanced** — skills, commands, and agents now include short descriptions extracted from their YAML frontmatter
- **`_lib.sh`** — added `extract_section()` and `extract_headings()` helpers for markdown section extraction

## [3.2.3] - 2026-02-28

### Added

- **Agent cross-reference validation** — `validate-plugin.sh` now scans SKILL.md files for agent path references (e.g., `agents/figma-ux-expert.md`) and warns if the referenced agent is not included in the plugin's `agents/` directory. Prevents silent omission of associated agents during plugin assembly.

## [3.2.2] - 2026-02-27

### Fixed

- **Plugin CHANGELOG preservation** — `sync-monorepo.sh --add-plugin` now preserves both README.md and CHANGELOG.md (previously only README was preserved)
- **Bash 3.2 compatibility** — replaced `declare -A` associative array with temp files for macOS default bash

## [3.2.1] - 2026-02-27

### Fixed

- **Plugin README preservation** — `sync-monorepo.sh --add-plugin` now preserves hand-written README.md files instead of overwriting them with the auto-generated template

## [3.2.0] - 2026-02-27

### Added

- **Auto-sync on publish** — when Monorepo or Plugin targets are selected in the Interactive Publishing Flow, the skill now automatically runs `sync-monorepo.sh`, commits, and pushes instead of leaving it as a manual step
- **Build artifact cleanup** — Post-Publish step now cleans up `build/` directories after publishing
- **Push-blocked fallback** — documents workaround when `prevent-direct-push` hook blocks monorepo pushes

### Changed

- **Interactive Publishing Flow** — Step 4 renamed from "Post-Publish" to "Auto-Sync to Monorepo", Step 5 is now "Post-Publish"
- **SKILL.md** — version bumped to 3.2.0

## [3.1.0] - 2026-02-27

### Added

- **Interactive Publishing Flow** — when invoked, detects current publishing state and presents a multiSelect prompt for target selection (individual repo, monorepo, plugin)
  - Dynamic labels show current state (e.g., "Monorepo (synced)", "Individual repo (published)")
  - Deselecting a published target triggers removal with confirmation
  - Post-publish step offers versioned release if monorepo was modified

### Changed

- **SKILL.md** — added "Interactive Publishing Flow" section before individual workflows
  - Version bumped to 3.1.0

## [3.0.0] - 2026-02-27

### Added

- **Plugin distribution support** — assemble, validate, and publish Claude Code plugins
- **scripts/prepare-plugin.sh** — assembles plugin from a JSON build manifest (`plugin-manifest.json`)
- **scripts/validate-plugin.sh** — validates assembled plugin structure (plugin.json, commands, skills)
- **scripts/install-plugin.sh** — consumer-facing installer/uninstaller for plugins
- **scripts/_lib.sh** — shared library extracted from all scripts (extract_field, extract_version, write_file, etc.)
- **Workflow E** in SKILL.md — full plugin publishing workflow (manifest → assemble → validate → sync → install)
- **Monorepo marketplace support** — auto-generates `.claude-plugin/marketplace.json` during sync
- **`/plugin` install instructions** — README shows `/plugin marketplace add` as recommended install method
- **Plugin section in monorepo README** — auto-generated table with plugin inventory
- **Plugin inventory in releases** — release script includes plugin count and inventory in CHANGELOG, tag, and summary
- **CI validation for plugins** — `validate-plugins` job in GitHub Actions workflow
- **PR template plugin checkboxes** — plugin.json validation, bundled skills, command frontmatter checks

### Changed

- **scripts/sync-monorepo.sh** — added `--add-plugin` flag, plugin discovery, README plugin section, marketplace.json generation
- **scripts/release-monorepo.sh** — includes plugin inventory in CHANGELOG entry, commit message, tag annotation
- **All existing scripts** — refactored to source `_lib.sh` shared library, removed duplicated helpers
- **SKILL.md** — version bumped to 3.0.0, description updated for plugin triggers

## [2.1.0] - 2026-02-24

### Added

- **scripts/release-monorepo.sh** — creates versioned releases of the monorepo with semver tags
  - `patch`, `minor`, `major` bump levels
  - `--dry-run` to preview without changes
  - `--github-user` override (auto-detects via `gh api`)
  - Reads current version from latest `v*` tag, calculates next version
  - Updates CHANGELOG top entry from "Monorepo sync" to versioned section
  - Creates annotated tag with skill inventory
  - Pushes branch + tag to origin

### Changed

- **SKILL.md** — added Workflow D (monorepo release) with bump level table
  - Updated Quick Reference with release commands
  - Updated description to mention versioned releases
  - Version bumped to 2.1.0

### Fixed

- **scripts/sync-monorepo.sh** — CHANGELOG generation now produces audit-style entries instead of duplicating per-skill changelogs
- **scripts/release-monorepo.sh** — version detection uses `git tag -l 'v[0-9]*'` instead of `git describe --tags` to avoid non-semver tags

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option

## [1.0.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — workflow for converting any skill directory into a GitHub repo
  - Step-by-step guide: prepare files, review, init git, create repo, push
  - Key decisions table (why `.claude/` is gitignored, why MIT, etc.)
  - Known gotchas (`gh repo create` remote conflict, username discovery)
- **scripts/prepare-skill-repo.sh** — generates `.gitignore`, `LICENSE`, `CHANGELOG.md`, `README.md` from `SKILL.md` frontmatter
  - Dry-run mode, skip-existing safety, `--github-user` flag
- **references/readme-template.md** — template with install/update/uninstall/compatibility sections
