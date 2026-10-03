# statusline plugin Implementation Plan

> For agentic workers: one implementation pass, TDD per task, commit per task. Nobody reviews between tasks; the whole branch is reviewed once afterwards.

**Goal:** Replace the `context-bar`, `custom-statusline` and `statusline-creator` plugins with one `statusline` plugin (1.0.0) whose installers never destroy a statusline script they did not write.

**Issue:** #158 (epic #156). **Spec:** `docs/superpowers/specs/2026-10-03-plugin-consolidation-design.md`.

## Global constraints

- Plugin name `statusline`, version `1.0.0`. Skills: `install`, `create`, `context-bar`.
- Every SKILL.md command spells the full `"${CLAUDE_SKILL_DIR}/scripts/..."` path in each fenced block. Never set a shell variable in one block and use it in another (the Bash tool keeps no state).
- `install` ships custom-statusline's current 3-tier `references/statusline-command.sh` unchanged in behaviour (user decision 2026-10-03).
- No personal values in published files: no `/Users/abhishek`, no repo names such as `tiny-vacation-agent`.
- bash scripts run on macOS bash 3.2 and Linux bash 5. Python is 3.9+, standard library only.
- The three old plugin directories stay unchanged in this PR. Only their marketplace entries change (Task 4).

## Review focus

1. A `~/.claude/statusline-command.sh` the plugin did not write (the user's own 49 KB script) must survive `install` and `create --install` untouched unless `--force` is passed, and is always backed up first when replaced.
2. `~/.claude/settings.json` that is missing, empty, invalid JSON or has no `statusLine` key: the installer must never truncate or corrupt it; on invalid JSON it exits non-zero and leaves the file byte-identical.
3. A write that fails midway (disk full, permission denied) must leave the old script in place: write to a temp file in the same directory, then `mv`.
4. `context-bar` run from any project directory must find that project's transcript dir, including paths with spaces and dots.
5. Exit codes: refusal is exit 3, bad input exit 2, success 0. No path exits 0 after a refused or failed write.

---

### Task 1: Scaffold the plugin and move the three skills

**Files:** create `plugins/statusline/` with `.claude-plugin/plugin.json`, `README.md`, `CHANGELOG.md`, `LICENSE` (copy from another plugin), `skills/install/`, `skills/create/`, `skills/context-bar/`.

- Copy `plugins/custom-statusline/skills/install-statusline/` → `skills/install/`, `plugins/statusline-creator/skills/statusline-creator/` → `skills/create/`, `plugins/context-bar/skills/context-bar/` → `skills/context-bar/`.
- Set each SKILL.md `name:` to the new name; reset version metadata to 1.0.0 in the plugin's own terms; rewrite descriptions to mention the old names so the model still matches them ("…(was install-statusline / custom-statusline)").
- Replace every `~/.claude/skills/<old>/…` path and every repeated cross-block variable with `"${CLAUDE_SKILL_DIR}/…"`.
- Drop context-bar's own small `statusline-command.sh` variant; `create` already offers a context-bar item. Point the context-bar SKILL.md at `/statusline:create` for a statusline.
- `create`'s SKILL.md line that calls context-bar "a subset of this skill": update to the new names.
- Run `scripts/validate-plugin.sh plugins/statusline` and `scripts/validate-skill.sh` on each skill until both pass.
- Commit.

### Task 2: Shared write guard

**Files:** create `plugins/statusline/lib/write-statusline.sh`; modify `skills/install/scripts/install.sh` and `skills/create/scripts/generate-statusline.sh` to use it; tests under `plugins/statusline/tests/`.

Contract (`write_statusline <source-file> <target> <force:0|1>`):
- Every script the plugin writes carries the marker line `# managed-by: statusline-plugin` as line 2 (after the shebang).
- Target absent → write it (temp file in the target's directory, then `mv`), exit 0.
- Target present with the marker → copy to `<target>.bak-<UTC timestamp>`, then write, exit 0.
- Target present without the marker → force=0: print what it found and how to proceed (`--force`), leave the file untouched, exit 3. force=1: back up, then write, exit 0.
- Backup or write failure → exit 1, target unchanged.

Settings update (both installers): keep the existing jq approach but make it safe. Missing settings.json → create `{}` first. Invalid JSON → exit 2, file byte-identical. Write via temp file + `mv`; back up settings.json to `settings.json.bak-<timestamp>` before changing it.

Tests (fresh `HOME` in a temp dir each; never touch the real `~/.claude`): one per contract line above, plus the five Review-focus inputs. Prove each guard by mutating it away in a scratch copy and watching its test fail. Add a CI job `statusline-tests` to `.github/workflows/validate-skill.yml` modelled on `github-board-tests` (run on ubuntu; the bash 3.2 cases run where bash 3.2 exists and skip with a reason elsewhere).

Commit.

### Task 3: context-bar finds the current project

**Files:** `skills/context-bar/scripts/context-bar.sh` (+ test).

- Replace the hardcoded `PROJ_DIR=…-tiny-vacation-agent` with a value derived from `$PWD` the way Claude Code names `~/.claude/projects/<dir>`: read how the transcript dir is named from a real example under `~/.claude/projects` (e.g. `/Users/x/dev/a.b c` → check the real mapping for `/`, `.`, space) rather than guessing; encode the rule and test it with those characters.
- No matching dir → say so and exit 1, never print a fake bar.
- Commit.

### Task 4: Marketplace, catalogue, changelogs

**Files:** `.claude-plugin/marketplace.json`, root `README.md`, root `CHANGELOG.md`, `plugins/statusline/CHANGELOG.md`.

- Add a `statusline` entry (source `./plugins/statusline`, version 1.0.0).
- Prefix the three old entries' descriptions with `Deprecated: use the statusline plugin (statusline:install / statusline:create / statusline:context-bar).` Keep their sources unchanged; they are removed in the next release.
- README catalogue: add the `statusline` row; mark the three old rows deprecated.
- CHANGELOG entries under `[Unreleased]`, inside the existing block.
- Run `scripts/validate-plugin.sh` over all plugins, the repo's test scripts (`ls scripts/test-*.sh`), and `./scripts/commit-preflight.sh`.
- Commit.

### Task 5 (orchestrator, after merge): live cut-over

Not part of the implementation pass. After the PR merges: install `statusline@claude-code-skills`, confirm `~/.claude/statusline-command.sh` is byte-identical before and after, diff the loose `~/.claude/skills/{context-bar,custom-statusline}` against the plugin, then remove them. Leave the Codex copies in `~/.agents/skills/` for codex-config#13.
