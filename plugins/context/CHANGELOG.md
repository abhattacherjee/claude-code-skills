# Changelog

All notable changes to the **context** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#163, #176). It merges the `context-shield` plugin and the bare `conversation-search` skill. Two skills under short names: `shield` (was `context-shield`) and `search` (was `conversation-search`). Invoke them as `/context:shield` and `/context:search`. The old names still match as trigger phrases.
- Two agents ship with the plugin: `content-distiller` (from `context-shield`) and `conversation-summarizer`. The summarizer was only in `~/.claude/agents/` and was not in any repo until now. The skills start them as `context:content-distiller` and `context:conversation-summarizer`.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<OUTPUT_DIR>` for the run directory. The old text used `$SCRIPTS` and `SCRIPT=~/.claude/skills/...`, which only worked from a loose copy.
- `shield` and `search` no longer point at `~/.claude/agents/`. The agent files are part of the plugin.
- `search/scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`. The old copy was older.

### Deprecated

- The `context-shield` plugin, and the bare `context-shield` and `conversation-search` skills. They stay in the repo until #167. Install `context`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/shield/CHANGELOG.md` and `skills/search/CHANGELOG.md`.
