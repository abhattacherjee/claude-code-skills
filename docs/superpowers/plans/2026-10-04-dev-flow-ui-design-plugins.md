# dev-flow and ui-design plugins Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Two consolidations in one PR (epic #156):

- #165: merge the bare `worktree` (1.0.1) and `changelog-keeper` (1.1.1) skills into one `dev-flow` plugin (1.0.0) with skills `worktree` and `changelog`.
- #164: move `figma-ui-designer` (3.2.2) into a `ui-design` plugin (1.0.0) with skill `figma` and agent `figma-ux-expert`.

Make every command runnable as written and dispatch the agent by plugin agent type.

**Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`. **Caller inventory:** the orchestrator's scratchpad copy; its in-repo rows are listed in Task 5. **Model:** `plugins/context/` (PR #179) and `plugins/skill-kit/` (PR #174). The plan for `context` (`docs/superpowers/plans/2026-10-04-context-plugin.md`) is the closest template; read it first.

## Name map

| Old | New | Copy from |
|---|---|---|
| skill `worktree` (1.0.1, bare only, no plugin) | skill `dev-flow:worktree` | `worktree/` |
| skill `changelog-keeper` (1.1.1, bare only, no plugin) | skill `dev-flow:changelog` | `changelog-keeper/` |
| plugin + skill `figma-ui-designer` (3.2.2) | skill `ui-design:figma` | `plugins/figma-ui-designer/skills/figma-ui-designer/` (the bare copy matches it byte for byte, apart from its README and agents dir) |
| agent `figma-ux-expert` | agent `ui-design:figma-ux-expert` | `plugins/figma-ui-designer/agents/figma-ux-expert.md` |

The version drift that #164 names (bare 3.2.0, plugin 3.1.0) was fixed in 3.2.1 (#173): `plugin.json`, the marketplace entry and both SKILL.md copies are all 3.2.2 now. Nothing to fix there.

The in-repo copies are newer than or equal to every loose copy, with two exceptions the orchestrator handles at cut-over: the live `worktree` copy names a private repo in its virtualenv note (the repo copy is the generic version, already carried over in 1.0.1), and the live `figma-ui-designer` copy has `disable-model-invocation: true`. Neither goes into the plugin.

## Global constraints

- Plugins `dev-flow` and `ui-design`, version `1.0.0` each. The agent lives at `plugins/ui-design/agents/figma-ux-expert.md`. Keep its `name:` as the bare name; Claude Code adds the plugin prefix. Each SKILL.md `description` names the old skill ("Was the changelog-keeper skill"). Descriptions stay double-quoted single lines. Keep `/worktree` working as a phrase in `worktree`'s description.
- **Dispatch the agent by plugin agent type.** `figma` today launches `subagent_type: "general-purpose"` with a prompt telling it to "follow the instructions in ~/.claude/agents/figma-ux-expert.md". That file goes away at cut-over. Change it to `subagent_type: "ui-design:figma-ux-expert"` and drop the path instruction. Fix every other mention of `~/.claude/agents/...` in the skill.
- **Every command runs as written from the user's project directory, in a fresh shell** (same rules as #160, #161 and #163). Use `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. Use `<NAME>` placeholders for run-time values. No shell variable may be read in a block that did not set it. `references/*.md` use `<SCRIPTS_DIR>`. Today `worktree` calls `~/.claude/skills/worktree/scripts/setup-worktree.sh`, `changelog` sets `SCRIPT=~/.claude/skills/changelog-keeper/...` and uses `$SCRIPT` in later blocks, and `figma` calls `./scripts/extract-design-tokens.sh`, which only works from the skill directory.
- **Never write `${CLAUDE_SKILL_DIR}` or `${CLAUDE_PLUGIN_ROOT}` in SKILL.md prose** (outside a fenced command block). Claude Code substitutes them everywhere, so prose would show the skill's own absolute path. `run-tests.sh` enforces this.
- **One validator.** `worktree` and `changelog-keeper` each ship `scripts/validate-skill.sh`. Make each a byte-identical copy of the repo-root `scripts/validate-skill.sh`. `figma` has none; do not add one.
- **Scripts must not depend on their old install path.** Grep each script's usage/help text and body for `~/.claude/skills/worktree`, `changelog-keeper` and `figma-ui-designer`, and fix each one.
- The old `plugins/figma-ui-designer/` and bare `worktree/`, `changelog-keeper/`, `figma-ui-designer/` stay unchanged. They are removed in #167.
- bash 3.2 (macOS) and bash 5 (Linux): no `((n++))` under `set -e` (use `n=$((n + 1))`). Python 3.9+, stdlib only. No personal values or private repo names in published files.
- Commit trailer: `Co-Authored-By: <the model you are> <noreply@anthropic.com>`. Run `./scripts/commit-preflight.sh` before each commit. Stage files by name.

## Review focus

1. Every command in the three SKILL.md files runs as written from a project directory in a fresh shell. `check-skill-commands.py` enforces this in CI.
2. `figma` reaches its agent through `ui-design:figma-ux-expert`, and nothing still points at `~/.claude/agents/`.
3. The scripts behave the same from their new location. `setup-worktree.sh` prints a `cd` + `claude` command and may find its repo relative to the cwd. `update-changelog.sh` reads git history from the cwd.
4. Nothing in the old names' marketplace entry or catalogue rows says the old plugin is current.

---

### Task 1: Scaffold `dev-flow` and move the content

**Files:** create `plugins/dev-flow/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `skills/worktree/`, `skills/changelog/`. Copy the shape of `plugins/context/`.

- `worktree` gets `SKILL.md`, `CHANGELOG.md` and `scripts/`. `changelog` gets `SKILL.md`, `CHANGELOG.md` and `scripts/`.
- Set each SKILL.md `name:` and version to 1.0.0. Add fresh 1.0.0 CHANGELOG entries naming the origin (worktree 1.0.1, changelog-keeper 1.1.1). Put the old history under "History before 1.0.0".
- Replace old skill names in the moved text with the new ones, except deliberate "was …" notes.
- README: one page with a "Was" column, merged from the two old READMEs, keeping every fact. Install only through `/plugin install` / `claude plugin install`. Both old LICENSEs match the plugin LICENSE (MIT, "Copyright (c) 2026 Abhishek"), so one plugin LICENSE is enough.
- Run `scripts/validate-plugin.sh plugins/dev-flow` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Scaffold `ui-design` and move the content

**Files:** create `plugins/ui-design/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `agents/figma-ux-expert.md`, `skills/figma/`.

- `figma` gets `SKILL.md`, `CHANGELOG.md` and `scripts/`. The agent goes to the plugin root.
- Version 1.0.0, a CHANGELOG entry naming the origin (figma-ui-designer 3.2.2), and old history under "History before 1.0.0". The plugin CHANGELOG is the same shape.
- README: from `plugins/figma-ui-designer/README.md` (108 lines; the bare README is 50 lines, so check it for any fact the plugin README lacks). Add a "Was" column, keep every fact, and install only through the plugin.
- Validate as in Task 1. Commit.

### Task 3: Runnable commands and agent dispatch

**Files:** the three SKILL.md files and `.github/workflows/validate-skill.yml`.

- Fail first: run `python3 scripts/check-skill-commands.py plugins/dev-flow plugins/ui-design` and record the count.
- Fix the three SKILL.md files per Global constraints until it exits 0. Switch `figma`'s agent dispatch to `ui-design:figma-ux-expert`.
- The token-extractor examples take a project path (`./frontend`). That path is the user's project and stays relative; only the script path changes.
- CI: add `plugins/dev-flow plugins/ui-design` to the existing `check-skill-commands.py` step, and update its comment.
- Commit.

### Task 4: Tests and CI

**Files:** `plugins/dev-flow/tests/run-tests.sh` and `plugins/ui-design/tests/run-tests.sh` (new), `.github/workflows/validate-skill.yml`.

Model both on `plugins/context/tests/run-tests.sh`: temp project dir, clean env (`env -i`), a plugin copy under a path with a space, and `HOME` pointed at a temp dir so nothing real is read or written. No network.

- `worktree/scripts/setup-worktree.sh`: in a temp git repo with a `develop` branch and one commit, run `create --new <name>`, `list` and `remove <branch>` as SKILL.md calls them. Assert exit 0, that the worktree directory exists after create and is gone after remove, and that the output contains the `cd` line. Read the script first to find where it puts worktrees, and make sure that place is inside the temp dir. Bad input: an unknown subcommand, and `remove` of a branch with no worktree, each exit non-zero with a message. Outside a git repo, it exits non-zero.
- `changelog/scripts/update-changelog.sh`: in a temp git repo with a tag and three conventional commits (`feat:`, `fix:`, `docs:`), run `--dry-run` and the write mode as SKILL.md calls them. Assert the categories are right, `--dry-run` leaves `CHANGELOG.md` untouched (checksum before and after), and the write mode adds the entry inside the existing `[Unreleased]` block. Bad input: an unknown option exits non-zero.
- `figma/scripts/extract-design-tokens.sh`: on a small fixture frontend (a CSS file with custom properties and a Tailwind config if the script reads one; read the script for what it scans), run the HTML and `--format json` modes. Assert exit 0, valid JSON, and that a fixture token appears. Bad input: a missing directory exits non-zero.
- In both suites: every `"${CLAUDE_SKILL_DIR}/scripts/..."` path in the SKILL.md files exists and is executable (use the extractor `context` uses, and fail if zero are found). `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}` never appear in SKILL.md prose (copy `context`'s guard). Each skill's `validate-skill.sh` is byte-identical to the root copy, and a missing root copy fails the run.
- `ui-design` only: `figma` dispatches `ui-design:figma-ux-expert` and does not mention `~/.claude/agents/`. The agent file's `name:` is `figma-ux-expert`.
- Prove the suites can fail: in a scratch copy (never the real tree), break one thing per kind and confirm each turns the suite red. Break a script path, the agent dispatch line, a prose token and a script's exit code. Put the results in your report.
- CI jobs `dev-flow-tests` and `ui-design-tests` (ubuntu bash 5 and macos bash 3.2, like `context-tests`).
- Commit.

### Task 5: Marketplace, catalogue, changelogs, in-repo callers

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, the in-repo caller rows below.

- Add `dev-flow` and `ui-design` entries (sources `./plugins/dev-flow` and `./plugins/ui-design`, version 1.0.0). Prefix the `figma-ui-designer` entry's description with `Deprecated: use the ui-design plugin (ui-design:figma).` `worktree` and `changelog-keeper` have no entries.
- README catalogue: add the two rows. Mark the old `figma-ui-designer` plugin row, and the bare `worktree`, `changelog-keeper` and `figma-ui-designer` skill rows, as deprecated, pointing at the new names. Change their `cp -r` install lines to say they are deprecated, as #179 did for context.
- In-repo callers (from the inventory):
  - `plugins/spec/skills/create/SKILL.md:319,325,327,496` and `plugins/spec/README.md:17`: `figma-ui-designer` / `/figma-ui-designer` → `ui-design:figma` / `/ui-design:figma`. Bump `spec` 1.0.2 → 1.0.3 (plugin.json, marketplace entry, README row, plugin and skill CHANGELOG).
  - `plugins/context/skills/shield/SKILL.md:200,414`: `figma-ui-designer` → `ui-design:figma`. Bump `context` 1.0.0 → 1.0.1 the same way.
  - `plugins/github-board/skills/prune-branches/SKILL.md:90`: the worktree skill → `dev-flow:worktree`. Bump `github-board` 1.0.0 → 1.0.1 the same way.
  - Leave alone: the deprecated `spec-creator/`, `plugins/spec-creator/`, `context-shield/` and `plugins/context-shield/` copies (removed in #167); the `ALL_REPOS` list in both `apply-branch-protection.sh` copies (GitHub repo names, which stay until #157 archives them); the `changelog-keeper/` usage example inside the vendored `validate-skill.sh` copies (they must stay byte-identical to the root copy); `docs/` plans and specs, and CHANGELOG history.
- CHANGELOG entries go under `[Unreleased]`, inside the existing blocks. The root entry names #165 and #164.
- Run `scripts/validate-plugin.sh` over every plugin and every `scripts/test-*.sh`. Run `python3 scripts/check-skill-commands.py plugins/spec plugins/review plugins/skill-kit plugins/context plugins/dev-flow plugins/ui-design`, both new `run-tests.sh` files, `bash plugins/context/tests/run-tests.sh`, `python3 -m pytest plugins/github-board/tests -q` and `./scripts/commit-preflight.sh`.
- Commit.

### Task 6 (orchestrator, after merge): live cut-over

1. `claude plugin install dev-flow@claude-code-skills` and `ui-design@claude-code-skills`; `codex plugin add` for both.
2. Diff each loose copy against the plugin, and carry over anything only in a loose copy.
3. Move the callers outside the repo (inventory rows).
4. Remove the loose copies with backups: `~/.claude/skills/{worktree,changelog-keeper,figma-ui-designer}`, the `~/.agents/skills/` copies, `~/.claude/agents/figma-ux-expert.md`, and `~/.codex/agents/figma-ux-expert.toml` if the Codex plugin provides the agent.
5. Plain-language dogfood after removal, per spec step 5.
