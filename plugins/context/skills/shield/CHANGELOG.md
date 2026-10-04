# Changelog

All notable changes to the **shield** skill (was `context-shield`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `context` plugin as `context:shield` (#163). Same workflow as `context-shield` 1.3.2. The old name and `/context-shield` still match as trigger phrases.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`; the skill was also run through headless Claude): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<OUTPUT_DIR>` for the run directory. The old text set `SCRIPTS=~/.claude/skills/context-shield/scripts` and read `$SCRIPTS` in later blocks, which only worked from a loose copy (#163).
- The content-distiller agent now ships in the plugin and is started as `context:content-distiller`. The old text started a general-purpose agent and told it to read `~/.claude/agents/content-distiller.md` (#163).

### Fixed

- `manage-manifest.sh` works on jq 1.6 (an unquoted `label` key and a `$label` variable), `next-batch` adds the manifest `task` to each item, `mark-done` rejects an index outside the manifest (and one with a leading zero such as `08`, which bash and jq read differently, or more than 9 digits; `next-batch --batch-size` follows the same rule), and the new `mark-failed --index N --reason TEXT` records a source that could not be read. Step 3 uses it when the distiller replies `FAILED: <reason>`, and `summaries` lists failed sources apart from the summaries (#163).
- `visualize.sh` no longer stops on bash 3.2 when `--labels` is empty (#163).

## History before 1.0.0 (as `context-shield`)

### context-shield 1.3.2 - 2026-10-04

#### Changed

- The published plugin is rebuilt from this source, so its README matches `SKILL.md` and it now ships this changelog (#105).

### context-shield 1.3.1 - 2026-10-04

#### Changed

- The related-skill pointers say `spec:review` (was `spec-review`), after the three spec skills merged into the `spec` plugin (#160).

### context-shield 1.3.0 - 2026-02-28

#### Added

- **6 new common patterns** — API reference/framework docs, monorepo code audit, dependency upgrade research, large PR review, competitive feature matrix, security advisory review
- **Expanded When to Use table** — added triggers for code audits, dependency research, large PRs, competitive analysis, security advisories
- **Enhanced description** — broader trigger conditions for skill activation across all new use cases

### context-shield 1.2.0 - 2026-02-28

#### Added

- **Auto-detect ralph-loop mode** — automatically determines whether to use direct processing (≤2 batches) or ralph-loop (>2 batches) based on source count and batch size
- **Large Website / Documentation Site pattern** — new common pattern for breaking a single large site into section URLs with auto-ralph activation
- **Enhanced When to Use table** — added auto-ralph signals and large documentation site trigger

#### Fixed

- **Unbound variable with empty arrays** — `manage-manifest.sh` crashed under `set -u` when `local_args` array was empty. Fixed with safe expansion pattern `${array[@]+"${array[@]}"}`

### context-shield 1.1.0 - 2026-02-28

#### Added

- **Manifest-driven batch processing** — `manage-manifest.sh` script for creating, tracking, and collecting content distillation work across batches
- **Visualization system** — `visualize.sh` shows animated progress of agents being dispatched, working, and returning through the context boundary
- **Content-distiller agent** — isolated sub-agent that reads one source (URL, Figma, file, wiki, codebase) and returns a ~500-token distilled summary
- **Ralph-loop integration** — hand off multi-batch processing to `/ralph-loop` for fresh context per iteration
- **Five source types** — `url`, `figma`, `file`, `wiki`, `codebase` with type-specific reading strategies
- **Common patterns** — Figma design analysis, competitor research, GitHub wiki crawl

#### Included

- **1 skill**: `context-shield`
- **1 agent**: `content-distiller`
- **2 scripts**: `manage-manifest.sh`, `visualize.sh`
