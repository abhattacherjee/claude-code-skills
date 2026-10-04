# Changelog

All notable changes to the **context** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#163, #176). It merges the `context-shield` plugin and the bare `conversation-search` skill. Two skills under short names: `shield` (was `context-shield`) and `search` (was `conversation-search`). Invoke them as `/context:shield` and `/context:search`. The old names still match as trigger phrases.
- Two agents ship with the plugin: `content-distiller` (from `context-shield`) and `conversation-summarizer`. The summarizer was only in `~/.claude/agents/` and was not in any repo until now. The skills start them as `context:content-distiller` and `context:conversation-summarizer`.
- Smoke tests for the scripts, in `tests/run-tests.sh`, and a CI job (`context-tests`, bash 5 and bash 3.2) that runs them. They run each script from a temp project directory with `HOME` on a temp dir, check that both skills start their agents as `context:<agent>` and never name `~/.claude/agents`, and check that `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` appear only inside fenced code blocks.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<OUTPUT_DIR>` for the run directory. The old text used `$SCRIPTS` and `SCRIPT=~/.claude/skills/...`, which only worked from a loose copy.
- `shield` and `search` no longer point at `~/.claude/agents/`. The agent files are part of the plugin.
- `search/scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`. The old copy was older.

### Fixed

- `search`: `search --deep` with no match, and a bare `--no-color`, stopped with `unbound variable` on bash 3.2 (the macOS default). They now exit 0 with the normal output.
- `search`: `--deep` passed the topic to `grep` as a regular expression, so `zebr.corn` matched `zebracorn`. It now matches the text literally.
- `search`: `--topic`, `--branch`, `--project`, `--after` and `--before` were pasted into a jq program with only `"` escaped. A backslash in the value (`C:\temp`) made jq fail with a syntax error, and `\(...)` ran as jq code. The value is now escaped before it goes in.
- `search`: `--before <date>` kept a conversation created exactly at that midnight, so a one-day range could include the next day's first second. It now stops before it.
- `search`: the "last Tuesday" example gave `--after 2025-02-17 --before 2025-02-18`, which is a Monday. It now gives 2025-02-18 and 2025-02-19.
- `search`: the `--project` examples used a real project name; they say `my-app`.

### Deprecated

- The `context-shield` plugin, and the bare `context-shield` and `conversation-search` skills. They stay in the repo until #167. Install `context`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/shield/CHANGELOG.md` and `skills/search/CHANGELOG.md`.
