# skill-kit plugin Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Merge `skill-authoring`, `skill-publishing` and `claudeception` into one `skill-kit` plugin (1.0.0) with skills `author`, `publish` and `extract`. Make `plugins/skill-kit/skills/publish/` the publishing skill's only source (#105, restated), and make every command in the three skills runnable as written.

**Issues:** #161 and #105 (epic #156). **Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`. **Caller inventory:** the orchestrator's scratchpad copy; its in-repo rows are listed in Task 4.

## Name map

| Old | New | Copy from |
|---|---|---|
| skill `skill-authoring` (2.6.1; its plugin.json said 2.3.1) | `skill-kit:author` | `plugins/skill-authoring/skills/skill-authoring/` |
| skill `skill-publishing` (4.5.0) | `skill-kit:publish` | `plugins/skill-publishing/skills/skill-publishing/` |
| skill `claudeception` (3.2.0, bare only, no plugin) | `skill-kit:extract` | `claudeception/` (with `examples/`, `resources/`, `scripts/`) |

The in-repo copies are newer than the live `~/.claude/skills` clones (live: 2.6.0, 4.4.0, 3.2.0 with an older validator). Copy from the repo, never from `~/.claude`.

## Global constraints

- Plugin `skill-kit`, version `1.0.0`. Each SKILL.md `description` names the old skill ("Was the skill-publishing skill"), so old-name and plain-language requests still match. Keep each description a double-quoted single line (a folded `>-` breaks `validate-skill.sh`).
- **Every command must run as written from the user's project directory, in a fresh shell.** Same rules as the spec plugin (#160):
  - commands write `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`; a skill calling a sibling skill's script writes `"${CLAUDE_PLUGIN_ROOT}/skills/<sibling>/scripts/<name>.sh"`
  - `references/*.md` get no `${CLAUDE_*}` substitution: if a reference holds a command, SKILL.md defines `<SCRIPTS_DIR>` once and the reference writes `<SCRIPTS_DIR>/<name>.sh`
  - values known only at run time (the monorepo dir, a skill name, a GitHub user) are `<NAME>` placeholders the model writes literally, never shell variables read in a later block
  - `publish` SKILL.md has 30+ such problems today (`$SCRIPTS`, `$MONOREPO_DIR`, `~/.claude/skills/skill-publishing/scripts/…`). Fix them all.
- **Paths that stay:** `~/.claude/skills/<name>` as the place a user's *own* skills live (what `extract` writes to, what `sync-monorepo.sh` reads as `SKILLS_HOME`) is correct and stays. Only references to these three skills' *own* old locations (`~/.claude/skills/skill-publishing`, `~/.claude/skills/skill-authoring`, `~/.claude/skills/claudeception`) go. The sync scripts keep syncing bare skills until #167.
- **One validator.** All three skills ship `scripts/validate-skill.sh`. Make each a byte-identical copy of the repo root `scripts/validate-skill.sh` (the newest; the `skill-authoring` and `claudeception` copies are older).
- The old `plugins/skill-authoring/`, `plugins/skill-publishing/` and the bare `skill-authoring/`, `claudeception/` stay unchanged. They are removed in #167.
- bash runs on macOS bash 3.2 and Linux bash 5. Python 3.9+, standard library only.
- No personal values in published files (no home-directory paths, no private repo names).
- Commit trailer: `Co-Authored-By: <the model you are> <noreply@anthropic.com>`. Run `./scripts/commit-preflight.sh` before each commit. Stage files by name, never `git add -A`.

## Review focus

1. Every command in the three SKILL.md files (fenced and inline) runs as written from a project directory in a fresh shell. `check-skill-commands.py` enforces it in CI.
2. `publish` still does its job from its new location: `prepare-plugin.sh` assembles a plugin and `sync-monorepo.sh` passes the hygiene suite.
3. The hygiene suite no longer depends on a maintainer-only path.
4. Cross-references between the three skills, and the activator hook text, name the new skills.

---

### Task 1: Scaffold the plugin and move the content

**Files:** create `plugins/skill-kit/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `skills/author/`, `skills/publish/`, `skills/extract/`. Copy the shape of `plugins/spec/`.

- Copy each source in the name map to its new dir (the old dirs stay). `extract` keeps `examples/`, `resources/` and `scripts/` (with `claudeception-activator.sh`). Keep executable bits.
- Set each SKILL.md `name:` and version metadata to 1.0.0. Skill CHANGELOGs start a fresh 1.0.0 entry naming their origin (skill-authoring 2.6.1, skill-publishing 4.5.0, claudeception 3.2.0); old history stays below under a "History before 1.0.0" heading (the changelog hook needs strictly descending versions).
- Replace every old skill name in the moved text with the new one, except deliberate "was …" notes. This covers SKILL.md cross-references and see-also lines, `Skill(claudeception)` in `claudeception-activator.sh` (→ `Skill(skill-kit:extract)`), and its install comment (copy the script from the installed plugin, not from `~/.claude/skills/claudeception`).
- Do NOT register the activator as a plugin hook. It stays opt-in, as today.
- Validators: replace each skill's `scripts/validate-skill.sh` with the root copy.
- README: one page for the three skills with a "Was" column, like `plugins/spec/README.md`. Merge the three old READMEs (`plugins/skill-authoring/README.md`, `plugins/skill-publishing/README.md`, `claudeception/README.md`); keep every fact. Install only through `/plugin install` / `claude plugin install`.
- Run `scripts/validate-plugin.sh plugins/skill-kit` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Make every command runnable

**Files:** the three SKILL.md files and any `references/*.md` holding commands; `.github/workflows/validate-skill.yml`.

- Fail first: run `python3 scripts/check-skill-commands.py plugins/skill-kit` before fixing the text and record the problem count.
- Fix the SKILL.md files per Global constraints until it exits 0. If the checker flags something that is genuinely not a command, say so in your report rather than contorting the text. Change the checker only if it is plainly wrong, and then add a test to `scripts/test-check-skill-commands.sh`.
- Grep the moved scripts' usage/help text for `~/.claude/skills/skill-publishing`, `~/.claude/skills/skill-authoring`, `~/.claude/skills/claudeception`, and fix each to describe the plugin location. Examples that use `~/.claude/skills/<some-other-skill>` as a user's own skill stay.
- CI: add `plugins/skill-kit` to the existing `check-skill-commands.py` step.
- Commit.

### Task 3: Tests — #105, smoke tests, CI

**Files:** `scripts/test-sync-hygiene.sh`, `plugins/github-board/tests/test_structure.py`, `plugins/skill-kit/tests/run-tests.sh` (new), `.github/workflows/validate-skill.yml`.

- `scripts/test-sync-hygiene.sh`: point `SYNC_SCRIPT` (and any other path into `plugins/skill-publishing/…`) at `plugins/skill-kit/skills/publish/scripts/`. Delete the live-copy parity block (`LIVE_SKILL_DIR`, `IN_REPO_SKILL_DIR`, the `if [[ -d "$LIVE_SKILL_DIR" ]]` assertion and its SKIP branch, and the comments that describe skill-publishing as authored outside the repo). Do not re-point it: the source and the shipped copy are now the same files.
  - Record the suite's pass and skip counts before and after. Then run it with `LIVE_SKILL_DIR=/nonexistent`: the pass count must equal the normal run's and the skip count must not go up. Put all three result lines in your report.
- `plugins/github-board/tests/test_structure.py`: add `plugins/skill-kit/skills/author/SKILL.md`, `…/author/references/task-tracking-pattern.md` and `…/publish/scripts/validate-pre-sync.sh` to `CALLERS`. Keep the old paths (those files still exist until #167). Run `python3 -m pytest plugins/github-board/tests -q`.
- `plugins/skill-kit/tests/run-tests.sh`, modelled on `plugins/spec/tests/run-tests.sh` (temp project dir, clean env, plugin copy under a path with a space):
  - each skill's `validate-skill.sh` passes on its own skill dir and fails (non-zero) on a fixture skill with bad frontmatter
  - `author/scripts/generate-task-manifest.sh` runs from the temp dir the way SKILL.md calls it; assert exit 0 and a key line
  - `extract/scripts/claudeception-activator.sh` prints `Skill(skill-kit:extract)` and not `Skill(claudeception)`
  - `publish/scripts/prepare-plugin.sh` assembles a fixture plugin from a fixture `plugin-manifest.json` (one tiny skill) into a temp output dir; assert exit 0, the assembled `plugin.json` name and version, and the skill's SKILL.md present. Then `publish/scripts/validate-plugin.sh` passes on the output. Read `prepare-plugin.sh --help` for its real arguments.
  - one bad-input case per script that has one (missing file → non-zero)
- CI job `skill-kit-tests` (ubuntu and macos, like `spec-tests`) runs it.
- **Dogfood (local only, not CI; put the output in your report):** run the new `prepare-plugin.sh` on `~/.claude/skills/context-shield/plugin-manifest.json` into a temp dir and `diff -r` the result against `plugins/context-shield/`. Expect no difference, or explain every difference.
- Commit.

### Task 4: Marketplace, catalogue, changelogs, in-repo callers

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, `plugins/skill-kit/CHANGELOG.md`, `LOCAL-TESTING.md` if it names them, `plugins/spec/skills/create/SKILL.md` (see-also), `plugins/spec/README.md` (see-also), plus `plugins/spec/.claude-plugin/plugin.json` and the spec CHANGELOGs for that bump.

- Add a `skill-kit` entry (source `./plugins/skill-kit`, version 1.0.0).
- Prefix the `skill-authoring` and `skill-publishing` entries' descriptions with `Deprecated: use the skill-kit plugin (skill-kit:author / skill-kit:publish).` Keep their sources. `claudeception` has no marketplace entry.
- README catalogue: add the `skill-kit` plugin row. Mark the old `skill-authoring` / `skill-publishing` plugin rows and the bare `claudeception` / `skill-authoring` skill rows deprecated, pointing at the new names. Change the `cp -r` install lines for those two bare skills to say they are deprecated and to install the skill-kit plugin.
- spec plugin see-also: `skill-authoring` → `skill-kit:author`. Bump `spec` to 1.0.1 with a CHANGELOG line (plugin and the `create` skill). Do not touch `plugins/spec-creator/` or the bare `spec-creator/` (deprecated, frozen).
- Do not touch `plugins/obsidian-brain/` (a stale mirror removed by #166; its source is the obsidian-brain repo).
- CHANGELOG entries under `[Unreleased]`, inside the existing block. The root entry names #161 and #105.
- Run `scripts/validate-plugin.sh` over all plugins, every `scripts/test-*.sh`, `python3 scripts/check-skill-commands.py plugins/spec plugins/review plugins/skill-kit`, `bash plugins/skill-kit/tests/run-tests.sh`, and `./scripts/commit-preflight.sh`.
- Commit.

### Task 5 (orchestrator, after merge): live cut-over

Not part of the implementation pass. After the PR merges:
1. `claude plugin install skill-kit@claude-code-skills`, and the Codex equivalent.
2. Diff each loose copy (`~/.claude/skills/{skill-authoring,skill-publishing,claudeception}` and the `~/.agents/skills/` copies) against the plugin, and carry over anything only they have (expected: nothing; the repo is newer).
3. Move out-of-repo callers, one PR per repo: claude-code-config (`hooks/claudeception-activator.sh`, `skills/MANIFEST.md`, `CLAUDE.md`, `README.md`, `skills/test-vacuity-audit` see-also); the live `~/.claude/skills` see-also lines (scaffold-backport, cc-session-cost-analysis, review-feedback-loop, test-vacuity-audit, trip-photo-guide, restic-backup) and `hookify.claudeception-compress-nudge.local.md`; codex-config (`hooks-inventory.json`, the Codex hook); obsidian-brain (`compress` Layer 1 markers: match the new `Skill(skill-kit:extract)` and keep the old one; the `obsidian-setup` nudge); tiny-vacation-agent (`settings.local.json` permissions).
4. Remove the loose copies in `~/.claude/skills` and `~/.agents/skills`, with backups.
5. Dogfood each skill through a plain-language `claude -p` request.
