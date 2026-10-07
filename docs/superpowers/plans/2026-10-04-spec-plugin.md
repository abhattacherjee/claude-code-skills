# spec plugin Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Merge `spec-creator`, `spec-review` and `spec-implement` into one `spec` plugin (1.0.0) with skills `create`, `review` and `implement`, and make every command in them runnable as written.

**Issue:** #160 (epic #156). **Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`. **Caller inventory:** scratchpad `spec-callers.md` (the orchestrator's copy; its in-repo rows are listed in Task 4).

## Name map

| Old | New |
|---|---|
| plugin `spec-creator`, skill `spec-creator` (`/spec-creator`) | plugin `spec`, skill `create` (`/spec:create`) |
| plugin `spec-review`, skill `spec-review` | skill `review` (`/spec:review`) |
| plugin `spec-implement`, skill `spec-implement` | skill `implement` (`/spec:implement`) |
| `plugins/spec-<x>/skills/spec-<x>/` | `plugins/spec/skills/<create|review|implement>/` |

## Global constraints

- Plugin `spec`, version `1.0.0`. Each SKILL.md `description` names the old skill ("Was the spec-creator skill") so old-name and plain-language requests still match. `spec:review` reviews a design spec; its description must make clear it is not a code or PR review (the `review` plugin owns that), so plain-language "review my PR" does not land here.
- **Every command must run as written from the user's project directory, in a fresh shell.** Today every command calls `./scripts/<name>.sh`, which resolves against the user's cwd, not the skill, so all of them fail (15 problems found by the review plugin's analyzer; spec-review also reads `$SPEC_FILE` in a block that never sets it, and uses `$PROJECT_ROOT`). Rules:
  - commands write `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`; a skill that calls a sibling skill's script writes `"${CLAUDE_PLUGIN_ROOT}/skills/<sibling>/scripts/<name>.sh"`
  - `references/*.md` get no `${CLAUDE_*}` substitution: if a reference holds a command, SKILL.md defines `<SCRIPTS_DIR>` once and the reference writes `<SCRIPTS_DIR>/<name>.sh`
  - values known only at run time (the spec file path, the project root, a run dir) are `<NAME>` placeholders the model writes literally, never shell variables read in a later block
- The three old plugin dirs and the bare top-level `spec-creator/`, `spec-review/`, `spec-implement/` stay unchanged, except where Task 4 says (in-repo callers). They go in #167.
- bash runs on macOS bash 3.2 and Linux bash 5. Python 3.9+, standard library only.
- No personal values in published files (no home-directory paths, no private repo names).

## Review focus

1. Every command in the three SKILL.md files (fenced and inline) runs as written from a project directory in a fresh shell. A check enforces it in CI.
2. The cross-references between the three skills (create → "run /spec:review next", task-manifest.sh lines, the spec template's next-step text) name the new skills.
3. The scripts behave the same as before from their new location (they may have used paths relative to their own dir).

---

### Task 1: Scaffold the plugin and move the content

**Files:** create `plugins/spec/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `skills/create/`, `skills/review/`, `skills/implement/`.

- Copy each `plugins/spec-<x>/skills/spec-<x>/` to `skills/<new>/` (the old dirs stay).
- Set each SKILL.md `name:` and version metadata to 1.0.0. Skill CHANGELOGs start a fresh 1.0.0 entry naming their origin (spec-creator 2.4.2, spec-review 2.2.2, spec-implement 1.0.0); old history stays below under a "History before 1.0.0" heading (the changelog hook needs strictly descending versions).
- Replace every old skill and plugin name in the moved text with the new one, except deliberate "was …" notes: SKILL.md cross-references, `references/spec-template.md` next-step text, `task-manifest.sh` subject lines.
- README: one page for the three skills with a "Was" column, like `plugins/review/README.md`. Merge the three old READMEs; keep every fact. Install only through `/plugin install` / `claude plugin install` (a loose copy breaks `${CLAUDE_PLUGIN_ROOT}` paths and shadows the plugin).
- Run `scripts/validate-plugin.sh plugins/spec` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Make every command runnable; enforce it repo-wide for opted-in plugins

**Files:** the three SKILL.md files (and references if they hold commands); new `scripts/check-skill-commands.py`; its tests; `.github/workflows/validate-skill.yml`.

- `scripts/check-skill-commands.py <plugin-dir>...`: for each SKILL.md and `references/*.md` under each plugin, run the review plugin's analyzer on fenced blocks and inline command spans, and check every `${CLAUDE_SKILL_DIR}/…` (resolved against that skill's dir) and `${CLAUDE_PLUGIN_ROOT}/…` (resolved against the plugin dir) path exists and, when it starts a command, is executable. Exit 0 clean, 1 with one line per problem (`file:line: message`), 2 on usage error (no args, missing dir). **One analyzer source:** import the helpers (`fenced_blocks`, `block_problems`, `doc_span_problems` or whatever the module exposes for spans) from `plugins/review/skills/adversarial/scripts/test_skill_paths.py` by path; do not copy them. If an import needs a small refactor in that module (e.g. a constant that assumes the review plugin), make the minimal change and keep the review suite green (`python3 plugins/review/skills/adversarial/scripts/test_skill_paths.py -v`, `bash plugins/review/skills/adversarial/scripts/run-tests.sh`).
- Fail first: run it on `plugins/spec` before fixing the text; record the problems (expect the 15 relative-path and `$SPEC_FILE` problems at least).
- Fix the three SKILL.md files per Global constraints until it exits 0.
- Tests for the checker (a shell or Python test under `scripts/`, matching how sibling `scripts/test-*.sh` work): clean plugin → 0; a `./scripts/x.sh` command → 1; a cross-block `$VAR` → 1; a missing `${CLAUDE_SKILL_DIR}` target → 1; a non-executable command target → 1; no args → 2; missing dir → 2. Build fixture plugins in a temp dir.
- CI: run `python3 scripts/check-skill-commands.py plugins/spec plugins/review` and the checker's tests in the existing validate workflow. Only those two plugins opt in for now (other plugins are #151's job; do not touch them).
- Commit.

### Task 3: Script smoke tests and CI

**Files:** `plugins/spec/tests/` (new), `.github/workflows/validate-skill.yml`.

- The four kinds of scripts (`discover-conventions.sh`, `discover-project-architecture.sh`, `extract-spec-sections.sh`, `task-manifest.sh` ×3) have no tests. For each: run it from a temp project dir (not the skill dir) the way its SKILL.md calls it, with a small fixture (a tiny repo with a package.json or pyproject, a small spec markdown file) and assert exit 0 plus a key part of the output (valid JSON where `--json` is used, the expected section names, the task subjects naming the new skills). Also one bad-input case each where the script has one (missing file → non-zero).
- If a script finds its own resources relative to the cwd rather than its own dir, fix it to use its own dir, with a test that runs it from elsewhere.
- CI job `spec-tests` (ubuntu, plus macos for bash 3.2 if the scripts use bash features that differ) runs them.
- Commit.

### Task 4: Marketplace, catalogue, changelogs, in-repo callers

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, `plugins/spec/CHANGELOG.md`, `LOCAL-TESTING.md` if it names them, `scripts/test-discovery-guards.sh`, and the see-also lines in `context-shield` and `figma-ui-designer` (both the bare dir copy and the `plugins/` copy of each, so a sync cannot revert one from the other).

- Add a `spec` entry (source `./plugins/spec`, version 1.0.0).
- Prefix the three old entries' descriptions with `Deprecated: use the spec plugin (spec:create / spec:review / spec:implement).` Keep their sources.
- README catalogue: add the `spec` row; mark the three old rows deprecated.
- `scripts/test-discovery-guards.sh` hard-codes `$REPO_ROOT/spec-creator/scripts/discover-conventions.sh` and `$REPO_ROOT/spec-review/scripts/discover-project-architecture.sh`: point it at `plugins/spec/skills/create/scripts/…` and `plugins/spec/skills/review/scripts/…`, and run it.
- context-shield and figma-ui-designer see-also lines: old names → `/spec:create`, `/spec:review`, `/spec:implement`. Bump those two skills' patch versions per the repo's convention, with a CHANGELOG line each.
- CHANGELOG entries under `[Unreleased]`, inside the existing block.
- Run `scripts/validate-plugin.sh` over all plugins, every `scripts/test-*.sh`, and `./scripts/commit-preflight.sh`.
- Commit.

### Task 5 (orchestrator, after merge): live cut-over

Not part of the implementation pass. After the PR merges:
1. `claude plugin install spec@claude-code-skills`; `codex plugin add spec@claude-code-skills`.
2. Move out-of-repo callers, one PR per repo: claude-code-config (settings, MANIFEST, and the live skills it tracks: prd-creator, architecture-page, ui-from-requirements, review-feedback-loop if tracked there), codex-config (config.toml), cc-token-router (`inject_rubric.py` skip list: add `/spec:create`, keep the old name), control-tower (classifier: add the new names, keep the old ones for old transcripts), docs, prime-plays-ui, tiny-vacation-agent (`implement-story` `Skill(skill=...)` calls and the others).
3. Update `~/.claude`, `~/.agents`, `~/.codex` copies; uninstall/remove the three old plugins in Claude Code and Codex.
4. Dogfood each skill through a plain-language `claude -p` request.
