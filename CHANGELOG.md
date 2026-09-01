# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own `CHANGELOG.md` within its directory.

Format: Monorepo-level events only. For per-skill change details, see `<skill>/CHANGELOG.md`.

## [Unreleased]

### Changed

- **Refreshed the harden-repo hooks and scripts to the released v1.2.0 templates.** The installed copies predated upstream #43, #73, #83 and #84, so this repo was running guards with two live bypasses: a `cd` to a path that does not exist turned all four guards off while the command still ran here, and the secret scan could not see `scripts/`. Also gains the command parser, worktree-stable preflight identity, and the advisory drift check. Two artifacts were missing and are now installed: `scripts/check-assertion-strength.sh` and `.github/workflows/ci.yml` — the CI file ships with its `__HARDEN_LINT_JOB__` / `__HARDEN_TEST_JOB__` blocks still on the installer placeholder (comments, so the YAML is valid), and it adds a secret-scan and a CHANGELOG gate to pull requests alongside the existing `validate-skill.yml`. Left alone as locally modified: `scripts/bump-version.sh` (UNRECOGNIZED). `scripts/commit-preflight.sh` has no harden marker blocks so the doctor could not classify or repair it, and it was therefore left at its old generation apart from one necessary edit: its preflight token key (see below), without which the upgraded hook would have denied every commit.
  The preflight token key was updated to match: the v1.2.0 hook keys it on the repo's git common dir, so `commit-preflight.sh` had to key it the same way or every commit would be denied.

### Added

- **`deep-review`: a Red Flag for a negative control that re-implements the assertion instead of invoking it.** A control built from the guard's own logic tests the copy, not the guard — gut the real assertion and the control still passes, so the suite stays green over an unguarded path. Measured on openclaw#336: a doc-contract test added specifically to prevent vacuous assertions carried three controls of this shape, and three mutations each gutting a real assertion all survived. The rule is that a control must call the same function the suite calls, or parametrize over the same table it does.

### Security

- **`scripts/bump-version.sh`: hardening inherited from the harden-repo template, plus a real base-10 bugfix (harden-repo#55):** the shared template fed parsed version components into bash arithmetic without validating them, allowing an array-subscript payload in the version source to run as a command substitution. **This repo was not exploitable by that route** — it has no version file, deriving the version from `git describe --tags`, and the only payload shape that executes in bash arithmetic (an array subscript) cannot be a tag name, because `git check-ref-format` refuses any ref containing `[`. Both halves of that were verified rather than assumed. The guard is therefore defense-in-depth here.

  The base-10 half is a live bug regardless: without `10#`, a zero-padded tag such as `v1.08.09` was read as an invalid octal literal, and the bump silently produced an empty version and exited 0. It now yields `1.08.10`.

  Also included: `CURRENT_VERSION` is semver-validated before any arithmetic with each core component bounded to 9 digits; any `-prerelease` / `+build` suffix is stripped before the components are split, so only digit runs reach `$(( ))`; and a symmetric guard refuses a `NEW_VERSION` that is not semver-shaped, which converts the silent empty-version exit 0 above into a clean failure.

## [3.18.0] - 2026-08-09

### Added

- **deep-review** 1.2.1 -> 1.3.0: Phase 0 gained a fifth scoping step to record environment/toolchain coverage gaps (e.g. GNU `tar`/`gawk` behaviour unreachable from a macOS/BSD review host), labeling them **not executed locally**, then either **deferred to CI** after confirming a CI job actually covers that environment, or **UNCOVERED** when none does, with a recommended cross-platform check; the Final report gained a matching portability-coverage bullet; and Red Flags gained "Imply portability coverage from an unavailable toolchain." Re-applied from closed PR #98, which targeted `main` from a docs branch whose head branch no longer exists and had patched the generated plugin copy rather than this authoring source — a rebuild would have silently discarded it. Motivating case, from this repo: `_lib.sh:44` (shipped in #107) asserts "POSIX awk only, so this runs on macOS BSD awk and gawk alike" — a portability claim the review host could not execute, because `gawk` is not installed on it. Original change proposed by @lntutor in #98. (#50)

### Fixed

- **skill-publishing** 4.3.0 -> 4.4.0: `extract_field()` read a frontmatter field as raw text rather than as a YAML scalar, producing three defects at once — a block scalar (`>-`/`|-`) returned the literal indicator into the generated README (#37, invisible because `>-` renders as an empty blockquote); a double-quoted scalar kept every internal `\"` (#102); and a plain scalar that merely began or ended with a quote silently lost that character (previously unfiled). One awk-based scalar reader closes all three, since they share the root cause. Measured across all 44 monorepo `SKILL.md` files: **42 extract byte-identically, 2 change** — the `deep-review` pair, which is the bug. `short_desc()`'s `echo "$1"` also replaced with `printf` (mangled values starting with `-n`/`-e`). Minor rather than patch because previously-mangled output now differs. Two further parser corrections found in review: `description: >-2` (chomping written before the indentation indicator, which YAML permits) still returned the literal `>-2` — #37's own failure inside #37's fix — and the reader could return **multi-line** output, which `sync-monorepo.sh:604` would splice into a Markdown table row and break the table at exit `0`. Single-line output is now a stated contract: a literal `|` block folds to spaces rather than preserving newlines (matching `validate-skill.sh:121-131`), and `\n`/`\t`/`\r` decode to a space. (#37, #102)
- **skill-publishing** 4.3.0 -> 4.4.0, round-2 review findings. Four more defects in the same parser, plus one it had just introduced. (1) An **unrecognized** block header still FAILED OPEN — `description: >10` measured as `[>10]`, `>--` as `[>--]`, the indicator becoming the description, which is #37 arrived at from a third direction. `extract_field()` now writes a diagnostic to stderr and **exits 3**, which under `set -eu` stops the build at `prepare-plugin.sh:420` — deliberately, because a description the reader cannot decode must stop the build rather than publish a corrupt artifact at exit `0`. (2) The whitespace collapse was **non-local**: `"Cost:  100  USD."` kept its double spaces, but `"Cost:  100  USD.\tNote."` had its *beginning* reformatted because a `\t` appeared at the *end*. Decoded whitespace now carries an internal marker so only what the decode introduced is collapsed; the `sawws` flag is gone. (3) Folding a multi-line literal `|` block can change meaning and did so silently — it now emits a stderr note naming the file and field and suggesting `>`. (4) A literal CR/VT/FF byte in the source line travelled into the value and into a Markdown table cell; a single `emit()` point now maps all three to a space. (5) This change had itself **diverged** `_lib.sh` from `validate-skill.sh`, which still carried the old header regex, so the same file could pass CI validation and publish corrupt; the alternation is ported to all three `validate-skill.sh` copies. (#37, #102)
- **skill-publishing** 4.3.0 -> 4.4.0: `scripts/test-sync-hygiene.sh` gains **108 assertions** across folded (`>`, `>-`, `>+`, `>2`, `>-2`), literal (`|-`), double-quoted (escaped, escape-free, and carrying `\n`/`\t` escapes), single-quoted, plain, plain-opening-with-a-quote, absent, empty, percent-bearing, `echo`-option-shaped, unrecognized-block-header, deliberate-double-space and literal-CR descriptions; the suite is 434 assertions and green. **Three** broad mutation arms were run, because no single one covers the section (both copies of `_lib.sh` mutated together, so the authoring-parity assertion contributes no spurious red): develop's `extract_field` restored reds 44; an empty-returning stub reds 70 and is the only arm that trips the descriptionless-fallback guards; an awk compile error inside `extract_field` reds 214 and is the only arm that trips the run-level `assert_eq "…fixture builds" "0"` checks. **Ten** targeted arms were run on top, each reverting one guarantee and each turning at least two assertions red: block-scalar terminator (5), header regex narrowed to `/^>-$/` (14), trailing-whitespace trim (3), literal-scalar newline join (2), pre-fix header regex (3), `\n` decoded to `"XX"` (2), the fail-closed header guard (3), the marker-based collapse reverted to `sawws` (3), the literal-fold stderr note (2), and the control-byte scrub (3). Every style carries a positive control alongside its leaked-syntax negative, since an absence-only assertion passes identically for a working parser and one that emits nothing.

- **skill-publishing** 4.3.0 -> 4.4.0, round-3 review findings. (1) The `exit 3` fail-closed guard was **swallowed at two of its ten call sites**: `sync-monorepo.sh`'s CHANGELOG-inventory read and `release-monorepo.sh`'s release-inventory read were both `X=$(extract_field … | sed …)`, and a pipeline's rc is its last command's with no script here setting `pipefail`, so `exit 3` arrived as rc `0` with an empty description — a description-less inventory row published at exit `0`, the exact fail-open shape the guard exists to remove. Both are now two statements (`extract_field`, then `short_desc`), which also removes two of the three inline reimplementations of `short_desc`'s sed. Measured and recorded in `_lib.sh`: the terser `X=$(short_desc "$(extract_field …)")` **does not work** — the assignment takes the outer substitution's rc and discards the inner `3`. Output change, stated: `short_desc` keeps the sentence's period where the inline seds dropped it, so those inventory rows now match the README catalogue row exactly. (2) `_lib.sh`'s header comment now carries a **caller-analysis table for all ten call sites** (`ABORTS` for the seven bare assignments, `SUPPRESSED` for `prepare-plugin.sh:462/481/502`), plus an explicit statement of which rows the suite covers and which it does not; the previous version analysed `prepare-plugin.sh`'s four reads only. (3) `scripts/test-sync-hygiene.sh` gains **21 assertions** (**455** total, green): a block-scalar fixture with a **blank line** between two content lines, asserted as a whole row — deleting `_lib.sh`'s blank-line skip previously left the whole suite green — and three runs driving a bad-header skill through the **sync** and **release** paths, which the `badblock` fixture had never reached. Mutation-verified: blank-line skip deleted reds **3** (was **0**); sync inventory read reverted to the pipeline reds **2**; release inventory read reverted reds **4** (rc `128` instead of `3` — the release ran past the bad header and published an empty description); both reverts red **6**; against the pre-round-3 suite each of these reds **0**. (#37, #102)

### Changed

- `plugins/deep-review/README.md` **stays hand-curated** — the explicit decision #102 asked for. The generated form is a bare section-heading list where the curated one has written feature bullets; it stays curated because the generated output is *worse*, not because a sync would clobber it. **Correction:** the 3.17.0 entry below, and this repo's plan file, claimed a routine `sync-monorepo.sh` run would `rsync --delete` over it. It would not — `sync-monorepo.sh:1053-1068` and `:1177-1193` copy any existing `plugins/<name>/README.md` aside, rsync, then restore it, unconditionally for every plugin. Side effect worth naming: that blanket preserve means **no plugin README is ever refreshed by a generator improvement**; every already-published one is frozen until deleted or hand-edited. (#102)
- `plugins/skill-publishing/README.md` was **also** excluded from its rebuild in this change, for an unrelated defect filed as **#106**: the generator inlines SKILL.md body sections verbatim, and `skill-publishing`'s body documents a template, so regenerating emits a literal `https://github.com/<github-user>/<skill-name>`. Two manual README exclusions is a pattern — the generator is not yet safe to run unattended. (#106)

## [3.17.0] - 2026-08-05

### Changed

- Authoring source for **deep-review** moved into the monorepo, completing the plugin-only migration the `spec-*` family received in #59. `deep-review/` is now a top-level source directory whose manifest uses the in-repo `"source": "."` form; `plugins/deep-review/` is regenerated from it and the local bare skill at `~/.claude/skills/deep-review` has been removed, so the marketplace plugin is the single distribution channel and the plugin is rebuildable from a clone. This also retires deep-review's instance of the resolve-by-`source` vs resolve-by-`name` detector mismatch tracked in #92 — nothing now depends on `$SKILLS_HOME/deep-review` existing. **Not a general fix for #92:** `custom-statusline` remains affected and that issue stays open. (#101)
- **deep-review** 1.2.0 -> 1.2.1: skill-relative reference links disambiguated — both `references/delegated-verification.md` links are now `./references/…` under a Path-convention note, and the Step 2.1 `scripts/gemini-review.sh` note names the `adversarial-review` plugin that owns it, so bare `scripts/`/`references/` unambiguously means the project under review. (#101)

### Fixed

- `plugins/deep-review/README.md` is hand-curated (written at #33, never regenerated) and was **deliberately excluded** from the #101 rebuild rather than overwritten. `prepare-plugin.sh`'s generator reads the SKILL.md `description:` line raw instead of YAML-parsing it, so a double-quoted scalar containing `\"` escapes — which deep-review's is — emits literal backslash-quote sequences into the README body. Same class as #37 (folded `>-` leak), filed as #102; until it is fixed, a full `sync-monorepo.sh` auto-build would regress this README. (#101, #102)

## [3.16.0] - 2026-07-30

### Fixed

- **spec-creator** 2.4.1 -> 2.4.2: `detect_epic_structure`'s `| head -1 > /dev/null &&` guard always exited `0`, so every project was reported as using `epic-subdirs` regardless of actual layout, silently losing epics for flat-layout `story-*.md` projects. `discover-conventions.sh` now tests the glob directly and a regression harness covers both layouts. (#62)
- **spec-review** 2.2.1 -> 2.2.2: `detect_data_flow`, `detect_i18n`, and `detect_security_patterns` used the same broken `grep -rlq PATTERN | head -1 > /dev/null &&` idiom, so every one of the 13 patterns reported present on every project, including this one. All three detectors now test the pipeline's real result; positive controls added for all 9 previously-uncovered guards. (#62)
- **skill-publishing** 4.0.0 -> 4.2.0: `prepare-plugin.sh` resolved a relative in-repo manifest `source` against the caller's cwd instead of the manifest's own directory, so assembling `spec-creator`/`spec-review`/`spec-implement` failed from any directory other than the monorepo root; `sync-monorepo.sh` now falls back to an in-repo top-level source directory when `$SKILLS_HOME/<name>` is absent, so drift detection and auto-rebuild cover the in-repo-source arrangement. The in-repo-source manifest form is now documented in the SKILL.md manifest schema. (#61)
- **skill-publishing** 4.2.0 -> 4.2.1: `sync-monorepo.sh` treated every top-level monorepo directory as a skill, so `docs/` and `build/` entered the sync loop and emitted a spurious `ERROR: no SKILL.md` line on every run; the plugin auto-build stage assembled into `./build/<name>` in the caller's cwd, leaving an untracked `build/` tree that the script's own `git add -A` next-step banner would commit; and neither `.gitignore` site — the template written into a freshly `--init`-ed monorepo, nor this repo's own file — listed `build/`. Discovery now filters non-skill directories at **both** scan sites, including the `--add` branch (announcing each drop on stderr), auto-builds go to a `mktemp -d` stage cleaned up by an EXIT trap, and both `.gitignore` sites list `/build/`, root-anchored so a plugin shipping its own `build/` subdirectory is not silently excluded from that `git add -A`. (#74)
- **skill-publishing** 4.2.1: `sync-monorepo.sh` printed `echo: write error: Broken pipe` to stderr when run against a large CHANGELOG — a latent `| head -1` that only became visible once an auto-build EXIT trap was registered, which stops bash from leaving SIGPIPE at its default disposition in the command-substitution subshell so `echo`'s failed write is reported instead of silently killing it. It is a write/reader race rather than a hard threshold: measured 0/50 reproductions below 64 KiB, ~53% at 84 KiB, and 10/10 at 154 KiB. Replaced with a parameter expansion; generated output is byte-identical. An empty skill list also reported `Skills to sync (1)` and a bare `  - ` bullet, and the two remaining `echo` sites in `discover_skills()` ate a skill named `-n`: `--skills -n` synced nothing while exiting 0, and `--add -n` into a monorepo with no skills yet aborted the run with an empty stderr. (#74)
- **skill-publishing** 4.2.1: the `--add -n` fix above cured the cause, not the shape — an `--add` argument that reduces to nothing after comma-splitting (the literal argument `,`) still left the discovery pipeline's trailing `grep -v '^$'` with nothing to match, so it exited 1 and `set -e` killed the run with rc=1 and an empty stderr. `discover_skills()` now detects the empty result itself and exits with a message naming the offending argument. (#74)
- **skill-publishing** 4.2.1: a failed plugin auto-build was left undiagnosable. `prepare-plugin.sh` ran under `>/dev/null 2>&1` and the only output on failure was `Warning: prepare-plugin.sh failed for <manifest>`. That was survivable while the partial `./build/<name>/` tree stayed in the caller's cwd to inspect and re-run by hand; the temp-stage fix above deletes the stage on every path including this one, which left the discarded child output as the only evidence a failure ever produced. The child's output is now captured to a log in the stage root — not inside the build directory, which `prepare-plugin.sh` `rm -rf`s on entry — and echoed to stderr on failure. The run still exits 0; that is tracked separately as #73 and deliberately unchanged here. (#74)
- **skill-publishing** 4.2.1: the `.gitignore` template fix above reaches only a freshly `--init`-ed monorepo. `write_file` does not overwrite, so every already-published monorepo takes the `SKIP    .gitignore (already exists)` branch, which reads identically whether the existing file carries the rule or not — the operator got no signal that theirs lacks it. A non-fatal `NOTE` naming the missing `/build/` pattern is now emitted for that case. (#74)
- **skill-publishing** 4.2.1 -> 4.3.0: six defects surfaced by dogfooding #74, five of them the same shape — a write path that reported success while not doing its job. `prepare-plugin.sh` silently skipped a declared `hooks.source` that does not exist, after which `sync-monorepo.sh`'s `rsync -a --delete` removed the previously published `hooks/` from the plugin; a declared, non-empty source that does not resolve is now a manifest error, while an absent `hooks` key and an explicitly `null` source both remain legal no-ops. **Latent guardrail, not an active repair here:** all 14 `plugin-manifest.json` files on the authoring machine were audited and none declares `hooks.source`, so nothing in this repo was losing hooks — the fix protects other repos using this tooling that do ship them. (#77)
- **skill-publishing** 4.2.1 -> 4.3.0: the plugin auto-build stage invoked `prepare-plugin.sh` without `--github-user`, so the child re-derived the value via `gh api user` and fell back to the literal `USERNAME` when unauthenticated — one run could advertise the resolved account in the monorepo README and `USERNAME` in every auto-built plugin's own README. `GITHUB_USER` is resolved well before that stage and is now forwarded, which also removes one `gh` call per sync. (#79)
- **skill-publishing** 4.2.1 -> 4.3.0: a legacy manifest declaring skills as bare strings (`"skills": ["name"]`) aborted every one of `prepare-plugin.sh`'s eight `.skills[…]` reads with `jq: error … Cannot index string with "name"`, and `sync-monorepo.sh` read the same shape at two sites under `2>/dev/null`, so its reversion guard saw no skills and its drift check saw no first skill — the plugin was never rebuilt at all. (That class is **not fully closed**: `custom-statusline` is still never rebuilt, for the unrelated reason filed as **#92** — the drift detectors resolve plugin skills by `name` while `prepare-plugin.sh` resolves them by `source`. Pre-existing and out of scope here; do not read this entry as shutting the class.) Manifests are now shape-normalised once into a temp copy that every read is pointed at, with `MANIFEST_DIR` deliberately left on the *original* manifest's directory so relative `source` values still resolve; bare strings in `commands[]`/`agents[]` are refused rather than guessed at, since those sources are files. A failed plugin auto-build is now fatal — the run names every broken manifest in one pass and exits 1 before any catalogue-regenerating stage, instead of publishing a README, CHANGELOG and marketplace entry describing a plugin it could not build. **Consequence worth stating plainly:** `github-release-board-promote`, the only real legacy-shape manifest, has no `plugins/` directory and no marketplace entry today — it was never published *at all*, not merely left stale. The next real sync run will publish it for the first time; this release deliberately does not. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: `validate-pre-sync.sh` hardcoded each skill's source as `$SKILLS_HOME/<name>` and `continue`d when that path had no `SKILL.md`, counting the skill as neither examined nor failed — i.e. as a pass. Every skill whose only source is its in-repo directory was therefore never validated while the summary still printed "Safe to sync". It now resolves through the same `skill_source_dir()` the sync uses, hoisted from `sync-monorepo.sh` into `_lib.sh` so there is one definition of where a skill's source lives instead of two that can disagree. A skill with no source anywhere is still skipped rather than failed, but the skip is now announced on stderr. (#78)
- **skill-publishing** 4.2.1 -> 4.3.0: a `--skills` value resolving to zero names republished an empty catalogue, silently. `--skills ,` produced no names at all, exited 0 and regenerated the README with an empty catalogue table plus a CHANGELOG entry claiming "Synced 0 skills"; `--skills nosuchskill` printed one inline `ERROR: no SKILL.md` line and did the same destructive rewrite. `discover_skills()` now refuses the first by name, and a second guard sited immediately after the main sync loop — ahead of the auto-build, which `rsync --delete`s into `plugins/` — refuses the second. A discovery-driven run against a monorepo that genuinely holds no skills stays a legitimate zero and still exits 0. `--add` and `--skills` are now rejected as mutually exclusive rather than one silently winning. (#80)
- **skill-publishing** 4.2.1 -> 4.3.0: unquoted `for` iteration over newline-delimited lists IFS-split any skill or plugin name containing a space into fragments, none of which resolved — `filter_skill_candidates` accepted `my skill` as one entry, then the loop emitted two `ERROR:` lines and a closing summary still claiming the full count had synced, with rc=0. All five sites in `sync-monorepo.sh` — and a sixth in `validate-pre-sync.sh`, converted by the same issue in a different task — are now `while IFS= read -r … done <<< "$LIST"` (here-strings, not pipes, so the loops keep assigning in the current shell), and the closing count is resolved-minus-refused. The same honest figure is used at every past-tense result site — the README template's `{{SKILL_COUNT}}`, the minimal-README fallback, the CHANGELOG's "Synced N skills" entry and the `--init` commit message; only the pre-loop "Skills to sync (N):" line keeps the requested count, being a plan rather than a claim. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: #81's own conversion introduced a truncation the old `for` loops could not have. `done <<< "$LIST"` binds the list to the loop **body's** stdin, and those bodies shell out to `gh`, `rsync`, `cp`, `diff`, `find`, `jq`, `sed` and `grep` — any child that reads stdin consumes the rest of the skill list and the loop exits early, reporting success. #81's count fix makes the truncation self-consistent: `{{SKILL_COUNT}}` is `SKILLS_RESOLVED_COUNT`, which counts the loop's own iterations, so the catalogue, the published count and the CHANGELOG inventory all agree with each other while the rest of the catalogue silently disappears. Demonstrated with a `gh` shim that drains stdin: a three-skill monorepo synced **one** skill, rewrote the README to a single catalogue row and exited **0**. Latent in production only because the real `gh repo view --json url` happens not to read stdin. All five sites in `sync-monorepo.sh` and the one in `validate-pre-sync.sh` now bind the list to **fd 3** (`read … <&3` / `done 3<<<`), leaving the body's stdin inherited so no child can reach it. The harness was structurally blind to this — its `gh` shim never touched stdin — so a draining shim is now part of it. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: consolidating the two `.skills[]` reads in the plugin auto-build stage onto one `manifest_skill_names … 2>/dev/null || true` was documented as preserving "the pre-existing tolerance of an unreadable manifest", and only half of that was true. The reversion guard's read was a command substitution in a `for` word-list, which does not trip `set -e`; the drift check's was an **assignment**, which did. The consolidation silently downgraded the second from fatal to skipped, on the destructive path — with the name list empty the reversion guard cannot fire, so a plugin is rebuilt from the stale local source the main loop just refused and `rsync -a --delete`'d over the published copy under an `AUTO-SYNCED` line; and an already-published plugin is never rebuilt at all. Reachable via `"skills": [123]`, which makes `jq` exit 5 while the `.name` read earlier in the same stage succeeds. A failed read is now recorded as a build failure and joins the collected-failure exit. Side effect, deliberate: `--dry-run` now also fails on a structurally unreadable manifest, since that is a defect a dry run can genuinely see. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: the collected-failure record was written *after* a command that can abort. `_BUILD_LOG` is named from the manifest's `.name`, which is free text; a `/` in it makes the log redirect fail, so the `sed` that reports the failure fails too, and `set -e` killed the run before `_FAILED_BUILDS=` was ever assigned — losing the whole point of collecting failures, since the summary naming every broken manifest in one pass then never printed. The assignment now precedes the `sed`, and the `sed` carries `|| true`. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: #73's bare-entry rejection landed in `prepare-plugin.sh` only, and `sync-monorepo.sh`'s main sync loop runs **first** — so a manifest carrying `"agents": ["x"]` killed the sync at `jq -r ".agents[$ai].name"` with a raw `jq: error … Cannot index string with "name"` and rc=5, and `prepare-plugin.sh`'s friendly explanation never printed because the run never reached the auto-build stage. The same `manifest_bare_entries` check, with the same message text, now runs in the main loop too, scoped to `agents[]` — the only array that loop indexes. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: `--add <unresolvable>` against a **populated** monorepo printed one inline `ERROR: no SKILL.md` and exited **0** having regenerated the README, CHANGELOG and marketplace — the same shape #80 closed for `--skills`, on the flag that is the documented way to introduce a new skill. #80's post-loop guard cannot catch it: it fires only when *zero* names resolve, and a populated monorepo always contributes resolvable ones through the existing-directory scan. `discover_skills()` now rejects any `--add`-contributed name with no `SKILL.md`, before anything is written, splitting on commas so a legitimate `--add a,b` is unaffected. This also closes #85, which tracked the narrower empty-monorepo case. (#80, closes #85)
- **skill-publishing** 4.2.1 -> 4.3.0: the `--skills` branch used `sort` where the `--add` branch used `sort -u`, under a comment claiming it mirrored `--add`. `--skills alpha,alpha` therefore synced one skill twice: two `--- alpha ---` stanzas, two identical catalogue rows, two identical `cp -r` lines published as install instructions, and a doubled count in the summary, the README and the CHANGELOG — every figure agreeing with every other. Now `sort -u`. (#80)

### Changed

- **skill-publishing** 4.2.1 -> 4.3.0: minor rather than patch because the batch above introduces new **refusals** — `prepare-plugin.sh` and `sync-monorepo.sh` invocations that previously exited 0 while quietly skipping work now exit 1. The exit-status contract is now documented in `--help`: `0` success; `1` usage/setup error (including a `--skills` value that resolves to no valid skill) or a failed plugin auto-build; `3` completed, but skills were refused by the reversion guard. `1` wins over `3`. `--dry-run` cannot predict a `1` from a failed build — plugins are not assembled at all under `--dry-run` — but it does still predict a `3`. (#73, #77, #78, #79, #80, #81)

### Added

- **deep-review** 1.1.1 -> 1.2.0: a Red Flag covering the hardcoded-**false** direction. The existing vacuous-test warning catches a guard stuck ON — the absent-pattern fixture fails — but says nothing about one stuck OFF, where an "expect nothing" assertion passes precisely *because* the detector is dead. The new entry requires both directions, prefers proving it by mutation over inspection, and adds a third axis independent of both: **fixture reachability**. PR #76 supplied the counterexample: its `--add ,` assertion had a fail-first negative genuinely attached to the comma case, and a working-`--add` positive control existed elsewhere in the suite — and it was still blind, because `MONOREPO_ADDCOMMA_FIXTURE` was created bare, so it exercised only the half that already worked (`--add ,` refused against an empty monorepo, exited 0 with a "Sync complete" banner against a populated one). No stricter assertion against that fixture could have caught it; PR #91 is where the blindness was found and fixed. Also reconciles the version sites **forward**: the live `plugin-manifest.json` was still 1.0.0 while the derived `plugin.json`/`marketplace.json` read 1.1.1 and the README row read 1.0.0, so the first sync that *rebuilds* the plugin would regress the published version to 1.0.0 — latent rather than pending, since the rebuild is gated on drift between the live `SKILL.md` and the in-repo copy and those were byte-identical; bumping the live manifest to 1.2.0 removes the trap before anything can spring it. `~/.claude/skills/deep-review/CHANGELOG.md` is created for the first time for the same reason: without it the publishing tooling fabricates a stub that would overwrite the real entry once anything triggers a rebuild (#82). `ship`'s duplicated Phase 4 wording is deliberately left alone — it is unversioned, out-of-tree, and was the orchestrator of the session that made this change. (#69)
- `scripts/test-discovery-guards.sh` — regression harness for the `spec-creator`/`spec-review` discovery-guard fixes above, with positive and negative controls. (#62)
- CI job `discovery-guards` in `.github/workflows/validate-skill.yml` runs the harness unconditionally on every PR — the existing path filters never matched `scripts/test-discovery-guards.sh`, and the detectors scan the whole tree, so path-filtering it would miss regressions. (#62)
- `scripts/test-sync-hygiene.sh` — regression harness for the `skill-publishing` sync-hygiene fixes above. Builds two throwaway `SKILLS_HOME`s and nine throwaway monorepos and runs the real `sync-monorepo.sh` against them from a throwaway cwd, one run per monorepo — a plain sync; an `--add` sync (the second, otherwise-uncovered discovery site); a sync of a monorepo holding no skills at all; three carrying a skill named `-n` reached in turn by discovery, by `--skills`, and by `--add` into an empty monorepo, one per `echo`-eats-`-n` site; an `--add ,` run, the only one expected to exit non-zero, which must fail with an explanation rather than an unexplained abort; a run against the second `SKILLS_HOME`, whose one manifest names a source that does not exist, so the auto-build fails (kept in a `SKILLS_HOME` of its own so the deliberate failure cannot print into the other eight runs); and a monorepo whose `.gitignore` already exists without `/build/`, the only way to reach `write_file`'s "already exists" branch. Asserts the non-skill filtering at both sites, the absent `build/` leftover in the caller's cwd, the auto-build temp stage's cleanup, the failing child's own error text reaching the operator, all three `.gitignore` surfaces (the template, this repo's own pattern staying root-anchored, and the advisory for an existing file — with a negative case proving the advisory is conditional), CHANGELOG top-entry preservation, the empty-list count, and authoring-copy parity across the whole skill tree rather than the sync script alone, so that a `SKILL.md` version or `CHANGELOG.md` left stale in the live copy is caught too — each behind a positive control that the corresponding stage actually ran and wrote to disk. The temp-stage leak scan attributes stages by a plugin name carrying the run's PID, so two copies of the harness running concurrently cannot claim each other's in-flight stage as a leak, and `comm`'s exit status is checked rather than discarded so the scan cannot degrade to a vacuous pass. `gh` is shimmed off `PATH` so the run reaches no network. Every assertion was proven red against a build with the matching fix reverted. (#74)
- CI job `sync-hygiene` in `.github/workflows/validate-skill.yml` runs that harness unconditionally, for the same reason `discovery-guards` is unconditional. (#74)
- `scripts/test-sync-hygiene.sh` grew from 59 to 194 **assertion call sites** in the source (198 executed at runtime; the difference is call sites inside loops) covering the six fixes above, across twenty throwaway monorepos and eight throwaway `SKILLS_HOME`s, with `prepare-plugin.sh` and `validate-pre-sync.sh` also driven directly (neither is reachable from a sync run in the shapes under test). Every new assertion was proven in both directions — red against a build with the matching fix reverted, *and* red against a positive control patched to a no-op — so a guard stuck OFF and a guard stuck ON are both caught. A closing mutation audit re-ran the whole suite against a scratch copy of each fix individually reverted and confirmed all 194 still execute under a combined revert of all six, so nothing goes green by not running. (#73, #77, #78, #79, #80, #81)
- `scripts/test-sync-hygiene.sh` grew again to 317 **assertion call sites** (326 executed at runtime), across thirty-four throwaway monorepos and eighteen throwaway `SKILLS_HOME`s, covering the fixes above. The headline addition is a second `gh` shim that **drains stdin**, closing the instrument gap that made the suite structurally unable to see the fd-3 defect: the shim reports how many bytes it consumed, and the run asserts every invocation read **zero** — a direct measurement that the skill list is out of any child's reach, not an inference from the skill count. That shim is itself controlled (fed four bytes, it must report four), so a shim broken to always report zero cannot make the assertion pass vacuously. Each fix was proven red against a scratch build with only that fix reverted (8 / 5 / 4 / 1 / 7 / 3 assertions red respectively), and two guards were separately proven red when patched *stuck ON* — one of which exposed a real gap: the bare-agent control read stdout only, where the message goes to stderr, and passed against a guard that suppressed all agent copying. It now reads both streams and asserts a well-formed agent actually lands on disk. Two assertions that do **not** discriminate for the fd-3 defect (the install-all and CHANGELOG-inventory loops re-read the list and spawn nothing) are labelled as controls on the conversion rather than left implying a fail-first they do not have. (#73, #80, #81)
- **skill-publishing** 4.2.1 -> 4.3.0: the bare-`agents[]` guard added above was itself non-fatal, and its own comment's safety net did not hold. It set `AGENT_COUNT=0` and left the run to the auto-build stage, which invokes `prepare-plugin.sh` only when the drift check sets `_NEEDS_BUILD`. Adding `"agents": ["x"]` to an already-published plugin's manifest without touching its `SKILL.md` — the natural way to add an agent, in the legacy bare-string form this batch exists to tolerate — therefore printed one `ERROR`, copied no agents, regenerated README/CHANGELOG/marketplace and exited **0**; the standalone-marketplace, `--add-plugin` and shadowed-manifest skips bypass the claimed net identically. A loudness regression: before the guard, that manifest died at `jq` with rc=5 and wrote nothing. Now collected and exited on through the shared refusal gate, which also moved out of the `[[ -x "$PREPARE_SCRIPT" ]]` block so a missing `prepare-plugin.sh` cannot disarm it. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: the refusal summary claimed more than had happened on two of the three paths it now serves — `plugin build failed` for a manifest whose `skills[]` merely could not be *read*, and "Skills synced before this point are already written" under `--dry-run`, which writes nothing. Each reason now has its own labelled row and `--dry-run` says plainly that nothing was written. `manifest_skill_names`' stderr is also captured separately rather than merged into the variable that *is* the skill-name list on the success path, where a diagnostic accompanying a zero exit would become a phantom skill name and silently suppress the rebuild. That last one is hardening, not a repair — no such warning is reachable today — and it carries no assertion for exactly that reason. (#73)
- **skill-publishing** 4.2.1 -> 4.3.0: `SKILL.md`'s Quick Reference asserted that `--skills` and `--add` both refuse an unresolvable name. They do not: `--skills good,typo` exits 0 and publishes a one-row catalogue, while `--add good,typo` exits 1 and writes nothing. This was the *second* false claim on that one sentence — the first promised `--skills` would not publish a "partial" catalogue, and its correction introduced this one — so the whole block was re-read for the same shape rather than the named clause patched. The correct asymmetry already existed in `--help`; it had not propagated to the line users skim. (#80)
- `scripts/test-sync-hygiene.sh` also gained coverage for #81's **sixth** conversion site. #81 is described throughout as five sites in `sync-monorepo.sh`; the sixth, in `validate-pre-sync.sh`, was converted by the same issue in a different task, and the space-name fixtures were then built entirely sync-side — so reverting *that loop alone* to `for SKILL_NAME in $SKILLS` left the harness at 248 PASS / 0 FAIL. Every earlier N-1-of-N on this branch was within one file; this is the first that crossed a file boundary, with the fix in one task's scope and the coverage in another's. Closed with a third presync monorepo carrying a space-named skill on **each** side of the report — one that must FAIL (mismatched CHANGELOG) and one that must PASS — because "examined" has two correct outcomes and a fix reaching only one list would otherwise look complete. The failing one makes the run's exit status a discriminator too: word-split, its fragments never enter `TOTAL` and the run prints "Safe to sync" at exit 0 over a genuinely broken skill. A dedicated fixture rather than growing the two existing presync monorepos, whose exact Total/Pass/Fail assertions are #78's evidence. Proven red (11 assertions) against a build with only that loop reverted, and separately against a build patched to examine nothing (19 red, including the ordinary-named control). The two proofs are kept apart: the word-splitting revert leaves all eight fd-3 assertions green, and the fd-3 revert leaves all twelve presync assertions green — the presync loop's only children are `grep`, `sed` and `head`, none of which read its stdin, so the fd-3 change is defence in depth there and the mutants say so. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: an adversarial pass found four of the six issues this PR closes were closed incompletely, each an N-1 of its own fix. #77's fatal `else` was nested inside the present-and-unresolvable test, so a `hooks` object with no `source` key (`{"src": "./hooks"}`) still fell through silently, printed a `--- Hooks ---` header as if it had worked, and let `rsync -a --delete` strip the published `hooks/`; `.hooks | has("source")` now separates that from the deliberate `{"source": null}` no-op, which is preserved. #79 forwarded `--github-user` but not `--author` on the same command line, so one run wrote two different names into a distributed MIT licence and the marketplace entry beside it. #78 fixed skill resolution but not discovery, leaving `validate-pre-sync.sh` structurally blind to every `--add <new-skill>` — the highest-risk case for the mismatch it exists to catch — now addressable via its own `--add`. And #81's `--add` path round-tripped the machine-discovered list through a comma-joined string, deleting a legitimately comma-named skill from the published catalogue at rc=0. Two smaller ones alongside: `printf "$RESULTS"` interpreted the report as a format string, and `_lib.sh` carried a `SKILLS_HOME` claim that contradicted the paragraph five lines below it. (#77, #78, #79, #81)
- **skill-publishing** 4.2.1 -> 4.3.0: the `--add ,` guard in `sync-monorepo.sh` tested emptiness on the union of discovered plus typed names, so it fired only when the monorepo was also empty. Against a populated one the run completed at rc=0 with the next-steps banner having added nothing — this PR's own defect class, in the function the same round had just rewritten. The root cause was the fixture: `MONOREPO_ADDCOMMA_FIXTURE` is created bare, so the `--add ,` assertion looked like coverage while testing only the half that already worked, which is how the bug survived into the commit that fixed its identical twin in `validate-pre-sync.sh`. Fixed on both sides, with a second populated fixture, and the two comments claiming the sync "already refuses by name for this exact argument" corrected — it did not. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: `--add ""` was the same silent no-op via a shorter argument — both `--add ,` guards sit inside `if [[ -n "$ADD_SKILL" ]]`, so an empty value skipped the branch wholesale and the run was byte-identical to one with no `--add`, at rc=0. Both scripts now gate on whether the flag was *passed* rather than on whether its value is non-empty. Pre-existing, landed rather than filed: shipping the previous entry's fix for one degenerate value only would re-instantiate its own finding. Also corrected a falsified absolute in the `.gitignore` comment — "only ever reaches a freshly `--init`-ed monorepo" is false, since any monorepo without a `.gitignore` gets the template; the error was pessimistic, so unlike the others on this branch it suppressed no audit. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: `--help`'s `Stdin:` block claimed "**Every** list-driven loop reads its list from fd 3". False, and a live trap rather than a documentation nit: `filter_skill_candidates()` reads stdin and *must*, being a pipeline filter invoked as `find … | filter_skill_candidates | sort`. A maintainer converting it for the consistency that sentence promised gets `Skills to sync (0)`, `Sync complete. 0 skills synced`, an emptied catalogue and **exit 0** — measured, not theorised. `--help` now scopes the rule to loops iterating a captured list in the current shell and names both deliberate exceptions, and the function itself carries a do-not-convert comment at the trap site, so the warning is where the edit happens rather than only in `--help`. Found by re-running the absolutes sweep over the **whole file** instead of the diff: a diff-scoped sweep structurally cannot catch a false absolute introduced by the commit immediately before it, and this one was. A whole-file pass over 124 absolute-bearing lines found no others. (#81)
- The `marketplace.json` builder was the one converted loop with no control, and a botched conversion of it is invisible. It is the only one reached through a process substitution rather than a here-string, and the newest of the eight. Reverting `3< <(…)` to `< <(…)` — the same botched-conversion mode the install-all and CHANGELOG-inventory loops already had controls for — writes an empty `"plugins": []` and exits **0**: the marketplace catalogue silently emptied, #80's shape on the marketplace side. The suite's only marketplace assertion tested existence, and the file *is* written, just empty; the README's plugin row comes from a different loop and survives. Measured: that mutant passed all 279 assertions at rc=0. One assertion on the catalogue's **contents** closes it, and it is red against the mutant and green against shipped code. (#81)
- **skill-publishing** 4.2.1 -> 4.3.0: the comment justifying that fd-3 conversion over-claimed, and it was the third half-true safety comment on this branch — inside the fix for the second. It said "no child can reach the list at all"; file descriptors are inherited across `exec`, so a child that deliberately reads `<&3` truncates the list exactly as a stdin-reading child did (measured: a 4-line list drove 2 iterations). fd 3 is a **convention** — stdin is read by filters by nature, fd 3 by nothing unless written to — not a barrier. Every such loop now also runs its body with `</dev/null`, which is the unconditional half, and the comment states the convention and its limit instead of swapping one absolute for another. A new assertion feeds the sync a known non-empty stdin and requires every `gh` invocation to still read **zero** bytes, which the run-level `</dev/null` of the existing drain fixture could not have discriminated. (#81)

## [3.15.0] - 2026-07-25

### Added

- `spec-implement` published as a marketplace plugin (#59).

### Fixed

- **deep-review** 1.1.0 -> 1.1.1: bundled `delegated-verification.md` into the plugin + relative reference path, so the verification step resolves for third-party installers (no longer a dangling `~/.claude/...` pointer). (#57)
- `spec-creator`, `spec-review`, and `spec-implement` no longer reference
  `~/.claude/skills/` paths; all three resolve their scripts and references
  relative to the skill directory, making them installable by third parties (#59).

### Changed

- **deep-review** 1.0.0 -> 1.1.0: synced skill from maintainer live copy — delegated-verification wiring (Story 1.4) + gemini-review.sh usage corrections. (#55)
- Authoring source for the `spec-*` family moved into the monorepo.

## [3.14.0] - 2026-06-15

### Added
- adversarial-review: regression fixture + extractor test for the fenced-JSON-inside-`.response` envelope shape in gemini-review.sh (#41)
- adversarial-review: judge passes now apply refutation pressure (default-to-refute-unless-grounded prompt hardening for both Gemini `--mode judge` and Claude's cross-examiner) and `synthesize.py` surfaces a per-direction confirm-rate with a `low_signal` flag that detects a rubber-stamping (near-unanimous) judge. (#31)

### Fixed
- adversarial-review: `synthesize.py` now recovers cross-examiner verdicts keyed by a descriptive slug — or via a `file:line` token in the verdict reason — instead of the canonical `G-NNN`/`C-NNN` id, so a refuted finding is reported as **rejected** rather than silently mis-filed as **unconfirmed**; truly-unmatched verdict ids now emit a loud stderr warning. The `adversarial-cross-examiner` agent contract is hardened to echo the canonical id verbatim. (#30)

## [2026-06-06] — Monorepo sync

Synced 7 skills from local source.

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [3.13.0] - 2026-06-08

### Added

- **deep-review** plugin (v1.0.0) — two-phase convergence harness for high-assurance changeset review: Phase 1 drives the `pr-review-toolkit` reviewers in fix→re-review rounds until they converge to zero actionable (Critical/Important) findings; Phase 2 runs an adversarial Claude↔Gemini cross-examination so only findings the *opposing* model confirms survive. Orchestrates the existing `pr-review-toolkit` and `adversarial-review` capabilities rather than reimplementing them, and degrades to Claude-only self-cross-examination (with a loud banner) when the Gemini adversary is unavailable. (#33)
- **github-board-move** skill (v1.0.0) — moves an issue/PR's Project (v2) card to a target Status column (`scripts/board-move.sh`): board discovery, Status field/option lookup, fuzzy column matching, `--list-status`, `--dry-run`, `--add`, and the `updateProjectV2ItemFieldValue` mutation. Fills the mid-lifecycle gap between `create-gh-board` and `github-release-board-promote`. (#28)

### Fixed

- **Publishing scripts** — `validate-skill.sh` now parses folded YAML block-scalar descriptions (`description: >-`) by folding continuation lines, instead of reading only the `description:` line and failing the mandatory `Use when:` check on a 2-char value. `prepare-plugin.sh` no longer emits phantom `` `Command: /null` `` entries: the `seq 0 $((COUNT-1))` loops (which run twice at COUNT=0 under BSD/macOS `seq`) were replaced with C-style `for ((i=0; i<COUNT; i++))` loops. (#34)

## [3.12.0] - 2026-06-02

### Added

- adversarial-review plugin (v0.1.0) — Claude↔Gemini **symmetric** adversarial PR review: both models discover findings independently in round 1, then cross-examine each other's findings in round 2; only findings the opposing model confirms survive (both-confirm rule). Unconfirmed (single-model) and rejected (with refuter + reason) findings are always surfaced, never silently dropped. PR + local modes; loud degradation to Claude-only when the Gemini adversary is unavailable. Guided Gemini setup with headless-credential detection.

## [3.11.0] - 2026-06-01

### Changes

- chore: harden repo — added Git Flow (develop branch + rules), quality-gate hooks, a commit preflight that validates changed skills/plugins, a git-tag-based release pipeline, and branch protection on `main` and `develop`
- docs: refreshed README to reflect current skills & plugins — removed the extracted `git-flow` plugin (now its own repo) and corrected `obsidian-brain` to v2.5.1 / 18 skills

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `obsidian-brain` v2.5.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.10.0] - 2026-05-16

### Changes

- sync: obsidian-brain v2.5.1 — /check-items reliability & ergonomics

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `obsidian-brain` v2.5.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.9.0] - 2026-05-14

### Changes

- sync: obsidian-brain v2.5.0 — smarter /check-items v2 pipeline

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `obsidian-brain` v2.5.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.8.0] - 2026-05-05

### Changed

- remove git-flow plugin (now distributed standalone) (#13)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `obsidian-brain` v2.4.3 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.7.0] - 2026-04-26

### Changes

- Sync obsidian-brain v2.4.2 (8 fixes since v2.4.1):
  - #105 cwd-gone session-id resolution
  - #101+#86+#110 source-session basename stability
  - #93 (+8 follow-ups) vault-doctor immutable capture-time signals
  - #81 vault-doctor duplicate session_id collision detection
  - #50 E2E snapshot to /recall integration tests
  - #68 vault-doctor snapshot_migration cross-midnight backlink
  - #45 /compress rank-gap delta guard
  - #78 /recall N=1 picker

## [3.6.0] - 2026-04-22

### Changes

- Sync obsidian-brain v2.4.1 (recall checkoff verify hardening)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.4.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.5.0] - 2026-04-21

### Changes

- sync(obsidian-brain): v2.4.0

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.4.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.4.0] - 2026-04-16

### Changes

- sync: obsidian-brain v2.3.0 — ACT-R access tracking, 7-signal scorer, /vault-stats

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.3.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.3.0] - 2026-04-14

### Changes

- Sync obsidian-brain v2.2.0: FTS5 hybrid reranking

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.2.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.2.0] - 2026-04-13

### Changes

- Sync obsidian-brain v2.1.0 + skills (2026-04-13)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.1.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.1.0] - 2026-04-12

### Added

- sync obsidian-brain v2.0.1 — wikilink escaping + revert-merge fix

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.0.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [3.0.0] - 2026-04-12

### Added

- sync obsidian-brain v2.0.0 — security hardening, vault index, vault-config

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v2.0.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.20.0] - 2026-04-11

### Added

- sync v1.9.0

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.9.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.19.0] - 2026-04-10

### Changes

- sync: obsidian-brain v1.8.2

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.8.2 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.18.0] - 2026-04-10

### Changes

- sync: obsidian-brain v1.8.1

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.8.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.17.0] - 2026-04-10

### Changes

- sync obsidian-brain v1.8.0 — recall performance + bug fixes

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.8.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.16.2] - 2026-04-09

### Changes

- sync: obsidian-brain v1.7.2 — Haiku summarization timeout retry

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.7.2 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.16.1] - 2026-04-09

### Changes

- sync: obsidian-brain v1.7.1 — sub-agent summary fallback

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.7.1 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.16.0] - 2026-04-09

### Changed

- sync to v1.6.2
- sync obsidian-brain to v1.6.1 (#1)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.7.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.15.0] - 2026-04-07

### Changes

- sync: obsidian-brain v1.6.0 — open items dashboard + auto-checkoff

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.6.0 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.14.3] - 2026-04-06

### Changes

- sync: obsidian-brain v1.5.3 — permission-aware setup + README troubleshooting

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.5.3 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.14.2] - 2026-04-06

### Changes

- sync: obsidian-brain v1.5.2 — Python 3.9 compat, deferred summarization, standup highlights

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.5.2 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.14.1] - 2026-04-06

### Fixed

- register obsidian-brain in marketplace.json

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.5.2 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.14.0] - 2026-04-06

### Added

- add obsidian-brain plugin (v1.5.2)

### Fixed

- enforce changelog/version discipline across skills

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (13 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `obsidian-brain` v1.5.2 — Persistent brain for Claude Code sessions using Obsidian. Auto-logs sessions, captures curated insights, enables project-scoped context resume, and provides fast cross-project search via tags and metadata.
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.13.0] - 2026-04-05

### Added

- add GitHub release creation to /finish for release/hotfix branches

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.12.0] - 2026-03-20

### Changes

- Sync skill-authoring v2.6.0 — MCP Tool Constraint section

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.6.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.11.0] - 2026-03-17

### Added

- add Agent Teams support to 6 skills/plugins

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.2.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.5.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.3.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.10.0] - 2026-03-16

### Added

- add spec-review plugin v2.1.0 — 4-agent parallel spec review with codebase verification, architecture checks, simplification, Bruno test plans

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (12 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.2.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `spec-review` v2.1.0 — Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.9.0] - 2026-03-16

### Added

- add spec-creator plugin v2.3.0 — TDD implementation steps, success metrics, Figma UX gates, brainstorming

### Changed

- remove project-specific screenshots and references, use generic examples
- detailed README with workflow, screenshots, agent descriptions

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (11 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.2.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `spec-creator` v2.3.0 — Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.8.0] - 2026-03-16

### Added

- v4.2.0 — storyteller agent, progress tracking, preview improvements

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (10 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.2.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.7.0] - 2026-03-15

### Added

- add smart-screen-recorder plugin v4.1.0

### Changed

- remove bare skill for product-video-creation (plugin-only)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (10 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `smart-screen-recorder` v4.1.0 — AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos.
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.6.0] - 2026-03-15

### Added

- add product-video-creation skill and plugin v2.0.0

### Changed

- restore custom-statusline README with screen examples

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion (React) with AI-crafted storytelling (Opus 4.6), real app screenshots, animated phone mockups, brand-aligned styling, and TTS voiceover (OpenAI or macOS)
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (9 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `product-video-creation` v2.0.0 — Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music.
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.5.0] - 2026-03-15

### Added

- add statusline-creator plugin, update custom-statusline to v1.3.0

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (8 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.3.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos
- `statusline-creator` v1.0.0 — Creates and customizes Claude Code statusline scripts from composable items

## [2.4.0] - 2026-03-15

### Added

- custom-statusline v1.2.0 — double-arrow git indicators + comprehensive README

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (7 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.0.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [2.3.1] - 2026-03-14

### Changed

- add preview examples to custom-statusline README
- remove bare skill copy of custom-statusline (plugin-only)

### Fixed

- update custom-statusline plugin to v1.1.0

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (7 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.0.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [2.3.0] - 2026-03-14

### Added

- custom-statusline v1.1.0 — tmux-aware width detection

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `custom-statusline` v1.1.0 — Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (7 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.0.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [2.2.0] - 2026-03-14

### Added

- add custom-statusline plugin v1.0.0
- add custom-statusline skill v1.0.0

### Changed

- update context-bar README with install instructions and statusline setup

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `custom-statusline` v1.0.0 — Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (7 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `custom-statusline` v1.0.0 — 4-tier adaptive statusline with icons for folder, git branch, and context usage
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [2.1.0] - 2026-03-13

### Added

- add context-bar plugin v1.0.0 — color-coded context window statusline

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (6 plugins)

- `context-bar` v1.0.0 — Color-coded context window usage bar for Claude Code statusline and /context-bar command
- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [2.0.0] - 2026-03-13

### Added

- migrate skill-publishing from bare skill to plugin format

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v4.0.0 — Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## [1.14.0] - 2026-03-06

### Added

- v3.6.0 — mandatory pre-sync validation gate and release enforcement

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.4.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.6.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.13.2] - 2026-03-05

### Added

- v3.5.1 — fix plugin CHANGELOG sync drift

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.13.1] - 2026-03-05

### Fixed

- sync plugin CHANGELOGs from source skill

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.13.0] - 2026-03-05

### Added

- v2.3.0 — add progress tracking for long-running workflows

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.3.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.12.1] - 2026-02-28

### Changed

- sync CHANGELOGs for context-shield, figma-ui-designer, skill-publishing

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.12.0] - 2026-02-28

### Added

- auto-resync plugins when bare skill content changes

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.11.2] - 2026-02-28

### Fixed

- sync plugin SKILL.md cross-references for context-shield and figma-ui-designer

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.11.1] - 2026-02-28

### Added

- sync skill-publishing plugin to v3.5.0 (auto GitHub releases)

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.11.0] - 2026-02-28

### Added

- auto-create GitHub releases in release-monorepo.sh

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.5.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.3] - 2026-02-28

### Changed

- add conversation-search ↔ context-shield cross-references

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.2] - 2026-02-28

### Added

- v1.3.0 — 6 new common patterns and expanded triggers

### Changed

- add bidirectional context-shield cross-references across skills

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.3.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.3.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.1] - 2026-02-28

### Changed

- sync context-shield plugin to v1.2.0 (auto-ralph)

### Fixed

- preserve plugin CHANGELOGs like READMEs + enrich bare-bones entries

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.2.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.2.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed for large workloads.
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.10.0] - 2026-02-28

### Added

- auto-detect ralph-loop for large workloads (v1.2.0)

### Fixed

- unbound variable with empty array under set -u

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.2.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.9.0] - 2026-02-28

### Added

- add figma-ui-designer as bare skill (+ agents)

### Skill Inventory (8 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.8.1] - 2026-02-28

### Changed

- bump skill-publishing to v3.4.0 (agent auto-discovery in sync)

### Fixed

- auto-discover agents from plugin-manifest.json in bare skill sync
- include content-distiller agent in context-shield bare skill

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.4.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.8.0] - 2026-02-28

### Added

- add context-shield skill and plugin (v1.1.0)

### Skill Inventory (7 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `context-shield` v1.1.0 — Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.3.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (5 plugins)

- `context-shield` v1.1.0 — Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries
- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.7.0] - 2026-02-28

### Added

- re-assemble skill-authoring & skill-publishing plugins with enriched READMEs
- rich plugin README generation (v3.3.0)

### Changed

- replace barebones figma-ui-designer README with enriched version

### Fixed

- remove stale build/ artifacts, add --exclude='build' to rsync

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.3.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.6.1] - 2026-02-28

### Added

- add agent cross-reference validation to validate-plugin.sh (v3.2.3)
- add figma-ux-expert agent to figma-ui-designer plugin

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.3 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.6.0] - 2026-02-28

### Added

- v3.1.0 — UX expert agent for brainstorming
- add figma-ui-designer plugin v3.0.0

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (4 plugins)

- `figma-ui-designer` v3.1.0 — Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP
- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.3] - 2026-02-27

### Changes

- Sync all plugins with source CHANGELOGs

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.2] - 2026-02-27

### Fixed

- preserve plugin CHANGELOG.md during sync, bash 3.2 compat

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.1] - 2026-02-27

### Fixed

- preserve plugin READMEs during --add-plugin sync

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.0] - 2026-02-27

### Changes

- Sync skill-publishing v3.2.0: auto-sync on publish

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.1] - 2026-02-27

### Changed

- enrich plugin READMEs with detailed feature descriptions and usage

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.0] - 2026-02-27

### Added

- add skill-authoring and skill-publishing as plugins

### Changed

- remove stale individual repo links for skill-authoring and skill-publishing

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.3.0] - 2026-02-27

### Added

- add interactive publishing flow with target selection

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.1] - 2026-02-27

### Added

- add plugin marketplace support

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.0] - 2026-02-27

### Added

- add plugin support + git-flow plugin (skill-publishing v3.0.0)

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.1.2] - 2026-02-24

### Fixed

- sync changelog-keeper v1.1.1 + release-monorepo.sh newline fix

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.1] - 2026-02-24

### Added

- sync validate-skill.sh with version-mismatch check

### Changed

- sync skill-authoring v2.1.0 CHANGELOG entry
- sync changelog-keeper v1.1.0 — multi-script CHANGELOG coordination

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.0] - 2026-02-24

### Added

- `worktree` v1.0.0 — creates isolated git worktrees for parallel Claude Code sessions
- `claudeception` v3.2.0 — extracts reusable knowledge from work sessions into skills
- `changelog-keeper` v1.0.0 — keeps CHANGELOG.md up to date from git commit history
- `release-monorepo.sh` — versioned release workflow with semver tags (patch/minor/major)
- Contribution workflow for all repos: CONTRIBUTING.md, PR template, CI validation, branch protection rulesets
- "Install all skills" section in monorepo README

### Changed

- CHANGELOG rewritten as audit log (was duplicating per-skill changelogs on every sync)
- `sync-monorepo.sh` generates compact skill inventory instead of dumping full per-skill changelogs
- `sync-individual-repos.sh` skips READMEs with custom sections (preserves claudeception fork attribution)
- `skill-authoring` v2.0.0 → v2.1.0 (added `((var++))` bash pitfall docs)
- `skill-publishing` v2.0.0 → v2.1.0 (added release-monorepo.sh, Workflow D)

### Fixed

- `validate-skill.sh` — `((var++))` arithmetic bug with `set -e`, missing `--help` flags
- `sync-monorepo.sh` — copy local READMEs instead of generating generic ones
- Restored `claudeception/README.md` with original fork attribution and research references

### Skill Inventory (7 skills)

- `changelog-keeper` v1.0.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history by topic, date, branch, or project
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices
- `skill-publishing` v2.1.0 — Publishes skills to GitHub repos and monorepo with versioned releases
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions

## [1.0.0] - 2026-02-24

### Added

- Initial monorepo with 3 skills:
  - `conversation-search` v1.1.0 — searches Claude Code conversation history
  - `skill-authoring` v2.0.0 — creates and optimizes Claude Code skills
  - `skill-publishing` v2.0.0 — publishes skills to GitHub repos and monorepo
- Auto-generated root README with skill catalog table
- MIT license
