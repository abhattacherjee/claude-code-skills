# Changelog

All notable changes to the **statusline** plugin are documented here.

## [1.0.0] - 2026-10-03

### Added

- First release (#158). Three skills under short names: `install` (was `install-statusline` in the `custom-statusline` plugin), `create` (was `statusline-creator`) and `context-bar`. Every SKILL.md command spells the full `"${CLAUDE_SKILL_DIR}/scripts/..."` path.

### Removed

- `context-bar`'s own `statusline-command.sh`. `/statusline:create` builds the same bar with its `context-bar` item.
