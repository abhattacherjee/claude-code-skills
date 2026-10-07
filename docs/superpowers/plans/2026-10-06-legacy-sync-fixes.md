# Legacy Sync Fixes (#92, #93, #106) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three defects in `skill-kit:publish`'s legacy sync path (skills copied from `~/.claude/skills`, plugins auto-built from `plugin-manifest.json`), and stop the test suite turning off plugin validation for every case.

**Architecture:** Small, separate fixes in `plugins/skill-kit/skills/publish/scripts/`. No change to the plugin-only path or `catalogue.py` from #190.

**Tech Stack:** bash 3.2-compatible shell, jq, the hermetic `scripts/test-sync-hygiene.sh` harness.

**Spec:** `docs/superpowers/specs/2026-10-05-catalogue-drift-guard-design.md` (section "Split"); design approved in chat on 2026-10-06.

## Global Constraints

- bash 3.2 compatible (no `mapfile`, no `${x,,}`, no associative arrays).
- Every test runs in a `mktemp -d` fixture with the existing `gh` shim; nothing touches the network or the live repo.
- Every new test is shown failing on the base commit (`3be5aa8` plus this plan) in a scratch copy before the fix lands.
- Run EVERY job in `.github/workflows/validate-skill.yml` locally before pushing (the #190 implementer's `ci-local.sh` in the scratchpad works), not just `scripts/test-*.sh`.
- Commits: `./scripts/commit-preflight.sh` as its own command, stage by name, `Co-Authored-By: <the model you are> <noreply@anthropic.com>`. CHANGELOG entries dated 2026-10-06 under the existing skill-kit `[Unreleased]`-style top entry conventions (read the file first).
- Plain English in comments, docs and CHANGELOGs.

## Review Focus

1. A manifest whose `skills[0].source` is `"."` (spec-creator style) must still resolve to the manifest's own directory, as `prepare-plugin.sh` does — the #92 fix must not break it.
2. `--skills` naming a skill that is not on disk must keep today's refusal (exit 1 / #80, #85 behaviour), not add a phantom row.
3. A placeholder inside a fenced block or inline code (`<monorepo-dir>` in a usage line) is legitimate and must NOT drop the section.
4. A SKILL.md whose every section has a placeholder must still yield a valid README (heading and description), not an empty file.
5. Removing the suite-wide opt-out must not make any existing case pass for the wrong reason: each changed fixture keeps its original assertion.

---

### Task 1: #92 — drift checks resolve skills through the manifest's `source`

**Files:** `plugins/skill-kit/skills/publish/scripts/sync-monorepo.sh` (auto-build drift check near `_FIRST_SRC_DIR=$(skill_source_dir "$_FIRST_SKILL")`, ~line 1417, and the plugin resync drift check that calls `skill_source_dir` on the manifest's skill name, ~line 1590 area), `_lib.sh` if a helper is added, `scripts/test-sync-hygiene.sh`.

- [ ] **Step 1: Failing tests.** Fixture: a `~/.claude/skills/my-statusline/plugin-manifest.json` with `"skills":[{"name":"install-statusline","source":"."}]` (name differs from the directory), synced once. Then edit the source `SKILL.md`. Assert: the next sync rebuilds the plugin (the published `plugins/<p>/skills/install-statusline/SKILL.md` holds the edit) — both via the auto-build drift check and via plugin resync. Second case: a manifest whose `skills[0].source` points at a missing directory → sync exits 1 and the error names the manifest path; tree digest unchanged. Control: the existing name == directory fixture still behaves as before.
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement.** Resolve the skill source with `resolve_source_path "$(jq -r '.skills[0].source' "$MANIFEST")" "$(dirname "$MANIFEST")"` (the function `prepare-plugin.sh` already uses; move it to `_lib.sh` if it is not shared yet), in every drift check that today calls `skill_source_dir` on a manifest-declared name. Enumerate every such call site first and list them in the commit body. An empty or missing resolved directory is an error: print `Error: <manifest>: skill source <source> does not resolve` and exit 1 before any write.
- [ ] **Step 4: Run, see them pass; run the whole suite.**
- [ ] **Step 5: Commit** `sync: drift checks resolve plugin skills through the manifest source (#92)`.

### Task 2: #93 — `--skills` re-syncs a subset but keeps the full catalogue

**Files:** `sync-monorepo.sh` (catalogue rows built from `SKILLS_TO_SYNC`, `{{SKILL_COUNT}}`, `{{SKILL_INSTALL_ALL_COMMANDS}}`), `scripts/test-sync-hygiene.sh`.

- [ ] **Step 1: Failing test.** 3-skill fixture (alpha, beta, gamma) synced fully; then `--skills alpha` after editing alpha. Assert: README skill catalogue still has 3 rows, the "A curated collection of 3" count is 3, the install-all block has 3 lines, beta and gamma rows are byte-identical to before, and alpha's row reflects the edit.
- [ ] **Step 2: Run, see it fail** (today: 1 row, count 1).
- [ ] **Step 3: Implement.** Build the catalogue rows, the count and the install-all lines from every top-level skill in the monorepo after the sync (the `list_top_level_candidates` + SKILL.md test discovery uses), not from `SKILLS_TO_SYNC`. Skills not re-synced take their row from their published `<repo>/<name>/SKILL.md`. Keep `--skills` refusals unchanged (Review Focus 2). Update the `--skills` help text and the publish SKILL.md sentence that describes it.
- [ ] **Step 4: Run, see it pass; whole suite.**
- [ ] **Step 5: Commit** `sync: --skills keeps the full catalogue (#93)`.

### Task 3: #106 — no `<placeholder>` prose in generated plugin READMEs

**Files:** `plugins/skill-kit/skills/publish/scripts/prepare-plugin.sh` (README build from `extract_section` / `extract_headings`, ~lines 405-663), `_lib.sh` (`extract_section`), `scripts/test-sync-hygiene.sh`.

- [ ] **Step 1: Failing tests.** (a) A fixture copy of `plugins/skill-publishing/skills/skill-publishing/SKILL.md` built through `prepare-plugin.sh` → the README has no `<github-user>` or `<skill-name>`. (b) A fixture SKILL.md with three sections: one with a prose placeholder (`see https://github.com/<user>/<repo>`), one with a placeholder only in a fenced block and in inline code, one plain. Assert the first is dropped and a line `dropped section "<title>": placeholder <user> in prose` is printed; the other two appear verbatim (positive control). (c) A SKILL.md whose every extracted section has a prose placeholder still yields a README with its heading and description.
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement** one function `section_has_prose_placeholder` (strip fenced blocks and inline code spans, then match `<[a-z][a-z0-9_-]*>`), used by every place the README inlines an extracted section. Print the dropped-section note on stderr.
- [ ] **Step 4: Run, see them pass; whole suite.** Then, per #106's last acceptance bullet, check whether `plugins/deep-review/README.md` and `plugins/skill-publishing/README.md` are still manual exclusions anywhere (grep), and report what you found; change nothing there unless the exclusion is now dead code.
- [ ] **Step 5: Commit** `prepare-plugin: drop README sections with placeholder prose (#106)`.

### Task 4: Stop disabling plugin validation suite-wide

**Files:** `scripts/test-sync-hygiene.sh` (`export SKILL_KIT_NO_PLUGIN_VALIDATION=1` at ~line 348), `prepare-plugin.sh` (~672-680) if the variable goes away, CHANGELOGs.

- [ ] **Step 1: Measure.** Remove the export in a scratch copy and run the suite. List every case that now fails and why (an invalid fixture skill vs a test that needs one).
- [ ] **Step 2: Decide by the count.** If the failing fixtures can be made valid without changing what their test asserts, make them valid and delete `SKILL_KIT_NO_PLUGIN_VALIDATION` from `prepare-plugin.sh` and both CHANGELOG notes that describe it. Otherwise set the variable only on the specific calls that need an invalid skill, each with a one-line reason. Report the count and the decision.
- [ ] **Step 3: Run the whole suite; every original assertion still holds** (Review Focus 5).
- [ ] **Step 4: Commit** `test-sync-hygiene: plugin validation stays on (#190 follow-up)`.

### Task 5: Docs, versions, CHANGELOGs

- [ ] skill-kit plugin and the publish skill: patch bump (read how #190 bumped them, follow the same rules), CHANGELOG entries for each fix, root `CHANGELOG.md` `[Unreleased]`. Run `python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .` after the version bump and `./scripts/check-docs.sh`.
- [ ] Run every CI job locally, then push.

## Pre-review self-check (before reporting done)

One line per class with the cases found and the test for each, or "none" plus what was checked: fail-open paths, exit codes, date boundaries, doc counts, broken Markdown.
