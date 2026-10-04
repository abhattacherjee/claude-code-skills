# context plugin Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Merge `context-shield` and the bare `conversation-search` into one `context` plugin (1.0.0) with skills `shield` and `search` and agents `content-distiller` and `conversation-summarizer`. Make every command runnable as written, dispatch agents by plugin agent type, and update the consolidation runbook's step 5 (#176).

**Issues:** #163 and #176 (epic #156). **Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`. **Caller inventory:** the orchestrator's scratchpad copy; its in-repo rows are listed in Task 4. **Model:** `plugins/skill-kit/` (PR #174) and `plugins/spec/` (PR #173).

## Name map

| Old | New | Copy from |
|---|---|---|
| plugin + skill `context-shield` (1.3.2) | skill `context:shield` | `context-shield/` (bare, the source; `plugins/context-shield/` matches it byte for byte since 1.3.2) |
| skill `conversation-search` (1.1.0, bare only, no plugin) | skill `context:search` | `conversation-search/` |
| agent `content-distiller` | agent `context:content-distiller` | `context-shield/agents/content-distiller.md` |
| agent `conversation-summarizer` | agent `context:conversation-summarizer` | `~/.claude/agents/conversation-summarizer.md` — the ONLY copy; it is not in the repo. Read it, copy it in, and read the copy as if you wrote it (it is content you publish). |

The in-repo copies are newer than or equal to every loose copy (checked by the inventory). Copy from the repo, except the summarizer.

## Global constraints

- Plugin `context`, version `1.0.0`. Agents live at `plugins/context/agents/<name>.md`; keep each agent's `name:` as the bare name (the plugin prefix is added by Claude Code, as with `review:bug-hunter`). Each SKILL.md `description` names the old skill ("Was the context-shield skill"). Descriptions stay double-quoted single lines.
- **Agents are dispatched by plugin agent type.** `shield` today launches `subagent_type: "general-purpose"` with a prompt telling it to "follow the instructions in ~/.claude/agents/content-distiller.md"; that file goes away at cut-over. Change it to `subagent_type: "context:content-distiller"` and drop the path instruction (the agent file's body is its instructions). `search` uses `Task(subagent_type="conversation-summarizer")`; change to `"context:conversation-summarizer"`. Fix every other mention of `~/.claude/agents/...` in the two skills.
- **Every command runs as written from the user's project directory, in a fresh shell** (same rules as #160/#161): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`; `<NAME>` placeholders for run-time values; no shell variable read in a block that did not set it; `references/*.md` use `<SCRIPTS_DIR>`. Today: `shield` uses `SCRIPTS=~/.claude/skills/context-shield/scripts` and `$SCRIPTS/...` across blocks (about 20 checker problems); `search` uses `SCRIPT=~/.claude/skills/conversation-search/scripts/search-conversations.sh`.
- **Never write `${CLAUDE_SKILL_DIR}` or `${CLAUDE_PLUGIN_ROOT}` in SKILL.md prose** (outside a fenced command block). Claude Code substitutes them everywhere, so prose would show the skill's own absolute path (PR #174, C-001). Use them only in commands that are meant to run. `run-tests.sh` enforces this (Task 3).
- **One validator.** `search` ships `scripts/validate-skill.sh`; make it a byte-identical copy of the repo-root `scripts/validate-skill.sh`. `shield` has none; do not add one.
- The old `plugins/context-shield/` and bare `context-shield/`, `conversation-search/` stay unchanged (removed in #167).
- bash 3.2 (macOS) and bash 5 (Linux): no `((n++))` under `set -e` (use `n=$((n + 1))`); Python 3.9+, stdlib only. No personal values in published files.
- Commit trailer: `Co-Authored-By: <the model you are> <noreply@anthropic.com>`. Run `./scripts/commit-preflight.sh` before each commit. Stage files by name.

## Review focus

1. Every command in the two SKILL.md files runs as written from a project directory in a fresh shell; `check-skill-commands.py` enforces it in CI.
2. Both skills reach their agents through `context:<agent>`, and nothing still points at `~/.claude/agents/`.
3. The scripts behave the same from their new location (they may resolve files relative to themselves or to `~/.claude/projects`).
4. The runbook's step 5 matches #176's criteria.

---

### Task 1: Scaffold the plugin and move the content

**Files:** create `plugins/context/` with `.claude-plugin/plugin.json` (1.0.0), `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, `agents/content-distiller.md`, `agents/conversation-summarizer.md`, `skills/shield/`, `skills/search/`. Copy the shape of `plugins/skill-kit/`.

- Copy each source in the name map. `shield` gets `SKILL.md`, `CHANGELOG.md`, `scripts/` (not its `agents/` dir: agents live at the plugin root). `search` gets `SKILL.md`, `CHANGELOG.md`, `scripts/`.
- Set each SKILL.md `name:` and version to 1.0.0; fresh 1.0.0 CHANGELOG entries naming the origin (context-shield 1.3.2, conversation-search 1.1.0), old history under "History before 1.0.0".
- Replace old skill and agent names in the moved text with the new ones, except deliberate "was …" notes. Keep `/context-shield` working as a phrase in `shield`'s description ("Was the context-shield skill").
- README: one page with a "Was" column for skills and agents, merged from the old READMEs, keeping every fact. Install only through `/plugin install` / `claude plugin install`. Credit lines and licenses carry over (check `conversation-search/LICENSE` against the plugin LICENSE; if the copyright differs, keep the original as `skills/search/LICENSE`, as skill-kit did for extract).
- Run `scripts/validate-plugin.sh plugins/context` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Runnable commands and agent dispatch

**Files:** the two SKILL.md files; `.github/workflows/validate-skill.yml`.

- Fail first: run `python3 scripts/check-skill-commands.py plugins/context` and record the count.
- Fix both SKILL.md files per Global constraints until it exits 0. Switch agent dispatch to `context:content-distiller` / `context:conversation-summarizer`.
- Check the scripts' usage/help text for `~/.claude/skills/context-shield` or `~/.claude/skills/conversation-search` and fix each.
- CI: add `plugins/context` to the existing `check-skill-commands.py` step.
- Commit.

### Task 3: Tests and CI

**Files:** `plugins/context/tests/run-tests.sh` (new), `.github/workflows/validate-skill.yml`.

- Model it on `plugins/skill-kit/tests/run-tests.sh` (temp project dir, clean env, plugin copy under a path with a space, `HOME` pointed at a temp dir so nothing real is read or written):
  - `shield/scripts/manage-manifest.sh` and `visualize.sh`: run each the way SKILL.md calls it (read their `--help` and the SKILL.md blocks for real arguments): exit 0 and a key output line on a small fixture; one bad-input case each (missing file or unknown command → non-zero with a message).
  - `search/scripts/search-conversations.sh`: build a fixture `~/.claude/projects/<dir>/<session>.jsonl` under the temp HOME with two or three small messages, then run its list/search/show modes as SKILL.md calls them (including `--json`, which feeds the summarizer); assert exit 0, the expected match, and valid JSON. Bad input: no match → the script's documented result; unknown option → non-zero.
  - Every `"${CLAUDE_SKILL_DIR}/scripts/..."` path in both SKILL.md files exists and is executable (extract them with the same extractor skill-kit uses; fail if zero are found).
  - `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}` never appear in SKILL.md prose outside a fenced block (copy skill-kit's guard; it handles fences in blockquotes).
  - Both SKILL.md files dispatch `context:content-distiller` / `context:conversation-summarizer`, and neither mentions `~/.claude/agents/`.
  - `search`'s `validate-skill.sh` is byte-identical to the repo root copy; a missing root copy fails the run.
- Prove the suite can fail: in a scratch copy (never the real tree), break one thing per kind (a script's path, the agent dispatch line, a prose token) and confirm each turns the suite red. Put the results in your report.
- CI job `context-tests` (ubuntu bash 5 and macos bash 3.2, like `skill-kit-tests`).
- Commit.

### Task 4: Marketplace, catalogue, changelogs, in-repo callers, runbook

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, `plugins/context/CHANGELOG.md`, `figma-ui-designer/SKILL.md` and `plugins/figma-ui-designer/skills/figma-ui-designer/SKILL.md` (see-also, keep the two identical), `plugins/spec/README.md` and `plugins/spec/skills/review/SKILL.md` (see-also) with a `spec` patch bump, `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md` (step 5).

- Add a `context` entry (source `./plugins/context`, version 1.0.0). Prefix the `context-shield` entry's description with `Deprecated: use the context plugin (context:shield).` `conversation-search` has no entry.
- README catalogue: add the `context` row; mark the old `context-shield` plugin row and the bare `context-shield` / `conversation-search` skill rows deprecated, pointing at the new names; change their `cp -r` install lines to say they are deprecated (as #174 did for skill-kit).
- figma-ui-designer and spec see-also lines: `context-shield` → `context:shield`. Bump each by a patch with a CHANGELOG line (figma-ui-designer: both copies and their plugin.json/marketplace/README rows; spec: plugin and the `review` skill). Do not touch the deprecated `spec-review`, `plugins/spec-review`, `plugins/obsidian-brain` (#166), `build/` (git-ignored), or skill-kit's publish scripts (#167).
- **#176:** rewrite step 5 of the consolidation spec so it says: (a) before merge, run each new skill by explicit invocation (`claude -p "/<plugin>:<skill> ..." --plugin-dir plugins/<group>`) from a temp project dir and check it runs its bundled scripts from the plugin dir; (b) run the plain-language test only after the loose copies are removed, with each skill's trigger phrases plus one ordinary phrasing; (c) probe any skill that shows `${CLAUDE_SKILL_DIR}` as text, because Claude Code substitutes it in prose too. Keep the step short and in the spec's style.
- CHANGELOG entries under `[Unreleased]`, inside the existing blocks; the root entry names #163 and #176.
- Run `scripts/validate-plugin.sh` over every plugin, every `scripts/test-*.sh`, `python3 scripts/check-skill-commands.py plugins/spec plugins/review plugins/skill-kit plugins/context`, `bash plugins/context/tests/run-tests.sh`, `python3 -m pytest plugins/github-board/tests -q`, and `./scripts/commit-preflight.sh`.
- Commit.

### Task 5 (orchestrator, after merge): live cut-over

1. `claude plugin install context@claude-code-skills`; `codex plugin add context@claude-code-skills`.
2. Diff each loose copy against the plugin (expected: nothing only in a loose copy).
3. Callers outside the repo: obsidian-brain `vault-import` (it runs `~/.claude/skills/conversation-search/scripts/search-conversations.sh` by path: resolve the installed `context` plugin's script at run time, keeping the old path as a fallback), `standup`, `vault-ask`, README; claude-code-config (`global/CLAUDE.md` `/context-shield`, `skills/MANIFEST.md`, `skills/reel-analyze`); codex-config `global/AGENTS.md`; live `~/.claude/CLAUDE.md` (generated from claude-code-config: check how), `~/.codex/AGENTS.md`, see-also lines in `~/.claude/skills` and `~/.agents/skills` (figma-ui-designer, claude-code-jsonl-metadata-stubs, reel-analyze); tiny-vacation-agent permissions and its two skills' see-also lines.
4. Remove the loose copies (`~/.claude/skills/{context-shield,conversation-search}`, `~/.agents/skills/` copies, `~/.claude/agents/{content-distiller,conversation-summarizer}.md`, and the `~/.codex/agents/*.toml` pair if the Codex plugin provides the agents) with backups.
5. Plain-language dogfood after removal, per the new step 5.
