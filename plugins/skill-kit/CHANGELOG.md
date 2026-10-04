# Changelog

All notable changes to the **skill-kit** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#161). It merges the `skill-authoring` plugin, the `skill-publishing` plugin and the bare `claudeception` skill. Three skills under short names: `author` (was `skill-authoring`), `publish` (was `skill-publishing`) and `extract` (was `claudeception`). Invoke them as `/skill-kit:author`, `/skill-kit:publish` and `/skill-kit:extract`. The old names still match as trigger phrases.
- `plugins/skill-kit/skills/publish/` is now the only source of the publishing scripts in the repo, so `scripts/test-sync-hygiene.sh` tests the shipped files and no longer compares them with a copy outside the repo (#105).
- Smoke tests for the scripts, in `tests/`, and a CI job (`skill-kit-tests`) that runs them.

### Changed

- Every script command in the three `SKILL.md` files runs as written from your project directory: `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`, with `<NAME>` placeholders for values known only at run time. The old `publish` text used `$SCRIPTS`, `$MONOREPO_DIR` and `~/.claude/skills/skill-publishing/scripts/`, which only worked from a loose copy.
- Each skill's `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`. The `skill-authoring` and `claudeception` copies were older.
- `claudeception-activator.sh` tells Claude to use `Skill(skill-kit:extract)`. It is still opt-in: the plugin does not register it as a hook.

### Deprecated

- The `skill-authoring` and `skill-publishing` plugins, and the bare `claudeception` and `skill-authoring` skills. They stay in the repo until #167. Install `skill-kit`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/author/CHANGELOG.md`, `skills/publish/CHANGELOG.md` and `skills/extract/CHANGELOG.md`.
