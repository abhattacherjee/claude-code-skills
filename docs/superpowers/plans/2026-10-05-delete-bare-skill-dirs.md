# Delete the bare skill directories Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** #167 (epic #156). Delete the 11 top-level bare skill directories (changelog-keeper, claudeception, context-shield, conversation-search, deep-review, figma-ui-designer, skill-authoring, spec-creator, spec-implement, spec-review, worktree). Every one has a plugin home and holds nothing the plugin lacks (survey 2026-10-05: 0 commits to any bare dir after its plugin home was created; every bare version is in its plugin's "History before 1.0.0"; claudeception's examples/ and resources/ are identical in plugins/skill-kit/skills/extract/). Make every check that used to scan them scan `plugins/*/skills/*` or fail closed.

**Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`, "Removing the bare directories (#167)".

**Out of scope (moved to #190 by the user's decision):** redesigning skill-kit:publish's sync and README/catalogue generation, deleting its bare-skill code paths, rewriting `scripts/test-sync-hygiene.sh` for a new model, and closing #84/#92/#93. Here those scripts only learn to refuse to run.

## Tasks

### Task 1: validate-plugin.sh stops masking a failing skill
- `scripts/validate-plugin.sh:198` runs `if "$VALIDATE_SKILL" "$skill_dir" 2>&1 | sed …; then pass` under `set -eu` without pipefail, so the `if` takes sed's exit code. Reproduced: a skill that `validate-skill.sh` fails with rc 1 is reported "PASS skill worktree" and the plugin passes with rc 0. Fix it so the skill's own exit code decides (pipefail or capture rc), and make a plugin with zero skill subdirectories (`:209-213`, a warning today) a failure.
- `plugins/skill-kit/skills/publish/scripts/validate-plugin.sh` is a byte-identical copy; keep it identical. Find any test that checks that copy and keep it green.
- Test: add a check to an existing repo test script (`scripts/test-discovery-guards.sh` or a new `scripts/test-validate-plugin.sh` wired into CI and `commit-preflight.sh` the way the other `scripts/test-*.sh` are) that builds a scratch plugin with a skill `validate-skill.sh` rejects and asserts `validate-plugin.sh` exits non-zero and prints the FAIL line; plus a zero-skill plugin case.
- Run `validate-plugin.sh` over every `plugins/*`. Two skills fail today and were masked: `plugins/context-bar/skills/context-bar` and `plugins/custom-statusline/skills/install-statusline` (missing "Use when:" in description; non-standard frontmatter `version`, `user_invocable`). Both plugins are deprecated. Fix their frontmatter minimally (move version under `metadata:`, add a "Use when:" clause to the deprecated description, drop or move `user_invocable`) and bump each plugin's patch version (plugin.json, marketplace entry, README row, plugin CHANGELOG). Check with `validate-skill.sh` that nothing else fails.

### Task 2: CI scans plugin skills
- `.github/workflows/validate-skill.yml` validate-skills job (lines ~20, 26, 50) matches only `^[a-z][a-z0-9-]+/SKILL\.md` and top-level `/(scripts|references)/`, so it never sees `plugins/*/skills/*` and prints "No skill directories changed". Switch it to `plugins/<group>/skills/<name>/` paths. Make it fail, not pass, if the changed-path list names a skill dir that does not exist after the change only when that is an error (a deleted skill is fine); say what you chose.
- `plugins/skill-kit/skills/publish/references/workflow-monorepo.yml` carries the same regex (lines ~20, 26); fix it the same way so a future sync does not put the old regex back.

### Task 3: publish scripts refuse to run with no top-level skills
In `plugins/skill-kit/skills/publish/scripts/`:
- `sync-monorepo.sh` `discover_skills` (~295-317, a second scan ~434) and the auto-build loop (~912), `validate-pre-sync.sh` (~102-105, prints "Safe to sync" on TOTAL=0): after #167 they find zero skills and report success. Make each exit non-zero with one plain message: the monorepo has no top-level skill directories; plugins under `plugins/` are the source (#167); sync is being redesigned in #190. Do not delete or redesign their other logic.
- `release-monorepo.sh` (~131, 176) counts `find . -maxdepth 2 -name SKILL.md -not -path ./plugins/*`, which becomes "Skills: 0". Releases must keep working: count `plugins/*/skills/*/SKILL.md` instead.
- Tests: `scripts/test-sync-hygiene.sh` uses hermetic fixtures; add cases for the refusal (a monorepo fixture with no top-level skill dir → non-zero exit and the message) for sync-monorepo.sh and validate-pre-sync.sh, and a release-monorepo count check if there is an existing harness for it (else say so). Existing fixtures that build top-level skill dirs keep passing.
- Bump skill-kit's version (patch) everywhere it is recorded, with CHANGELOG entries (plugin and publish skill).

### Task 4: tests that read the bare dirs
- `plugins/github-board/tests/test_structure.py`: CALLERS (~114) lists `skill-authoring/SKILL.md` and `skill-authoring/references/task-tracking-pattern.md`; `test_the_two_skill_authoring_copies_are_identical` (~140-145) compares `REPO/"skill-authoring"` with the deprecated plugin. Remove those two entries and that test (the comment ~119 already says "old paths stay until #167"). Bump github-board's patch version if plugin files change; tests alone may not need it — follow how earlier PRs handled test-only changes (check `git log -- plugins/github-board/tests`).
- `scripts/test-discovery-guards.sh:247-259`: delete the loop that diffs `spec-review/…` and `spec-creator/…` against the plugin copies, and its "Remove this loop when #167…" comment.

### Task 5: delete the 11 directories and fix what named them
- Before deleting: `spec-review/README.md` (120 lines) has "How It Works" phases, a "Bruno API Test Plan" section and "Design Simplification Notes" that `plugins/spec/README.md` lacks (0 "Bruno" hits; partly in `plugins/spec/skills/review/SKILL.md`). Carry any user-facing fact missing from the spec plugin's README/SKILL.md into `plugins/spec/README.md`, and bump spec's patch version. Diff the other 7 bare READMEs the same way and carry anything that is not install/update text for retired paths.
- `git rm -r` the 11 directories.
- Fix current docs that describe them: `README.md` (the "Skills" section lists 7 top-level skills and "7 reusable Agent Skills" — remove the section and the count, leave the plugin catalogue for #190), `CONTRIBUTING.md:22` ("Create a new directory at the repo root" → `plugins/<group>/skills/<name>/`), `AGENTS.md` and `CLAUDE.md` ("Each skill lives in its own top-level directory"), `scripts/validate-skill.sh` comment and usage example (`changelog-keeper/` → a plugin skill path). `validate-skill.sh` has byte-identical copies in plugins (`plugins/{dev-flow,context,skill-kit,…}/skills/*/scripts/validate-skill.sh`) that tests `cmp` against the root copy — update every copy together (find them with `find plugins -name validate-skill.sh`). Also the `sync-monorepo.sh` CONTRIBUTING heredoc (~1806-1822) says "Create a new directory at the repo root": fix the text.
- Deprecated plugins with links into deleted dirs: `plugins/skill-authoring/README.md:126` (`../../claudeception/`) and `skills/skill-authoring/SKILL.md:474` (`tree/main/skill-authoring`); `plugins/skill-publishing/README.md:112` and `SKILL.md:504` (`tree/main/skill-publishing`, already dead). Point them at the plugin that replaced them. Bump those deprecated plugins' patch versions.
- Grep the whole repo for each of the 11 names followed by `/` (and `](./<name>`), and fix every live reference. Leave `docs/` plans and specs and CHANGELOG history.

### Task 6: changelog and full verification
- Root CHANGELOG `[Unreleased]` entry inside the existing block, naming #167 and the validate-plugin masking fix.
- Run: `bash scripts/validate-plugin.sh` on every `plugins/*` (all must pass), `scripts/validate-skill.sh` on every `plugins/*/skills/*`, every `scripts/test-*.sh`, `python3 scripts/check-skill-commands.py plugins/spec plugins/review plugins/skill-kit plugins/context plugins/dev-flow plugins/ui-design plugins/demo-video`, every `plugins/*/tests/run-tests.sh`, `python3 -m pytest plugins/github-board/tests -q`, and `./scripts/commit-preflight.sh`.
