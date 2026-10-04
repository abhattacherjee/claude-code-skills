# Changelog

All notable changes to the **ui-design** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#164). It takes over the `figma-ui-designer` plugin (3.2.2) and the bare `figma-ui-designer` skill. One skill under a short name: `figma` (was `figma-ui-designer`). Invoke it as `/ui-design:figma`. The old name still matches as a trigger phrase.
- The `figma-ux-expert` agent ships with the plugin. The skill starts it as `ui-design:figma-ux-expert`.
- Smoke tests for the token script and the agent wiring, in `tests/run-tests.sh`, and a CI job (`ui-design-tests`, bash 5 and bash 3.2) that runs them. They run the script from a temp project directory with `HOME` on a temp dir and a clean environment, in a plugin copy under a path with a space. They check that `figma` starts `ui-design:figma-ux-expert` and never names `~/.claude/agents`, that the agent keeps the bare name, and that `${CLAUDE_SKILL_DIR}` appears only inside fenced code blocks.

### Changed

- The skill starts the agent as `ui-design:figma-ux-expert`. The old text started a general-purpose agent and told it to read `~/.claude/agents/figma-ux-expert.md`. That file is not part of any install.
- The script command is written to work from your project directory (checked statically by `check-skill-commands.py`, which now covers this plugin in CI): `"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh"`. The old text used `./scripts/extract-design-tokens.sh`, which only worked from the skill directory.

### Fixed

- `figma`: `extract-design-tokens.sh` stopped with `unbound variable` (exit 1) for a project with no CSS file in its usual places, in every format.
- `--format json` built the JSON by hand: a quote or backslash in the project path broke it, and a missing file showed as the text `null`. `jq` builds it now, and a missing file is a real `null`. The old fallback printed `""` when `jq` was missing; the script now exits 1 and says it needs `jq`.
- `--format` with no value stopped with `unbound variable`. It exits 2 with a message.

### Deprecated

- The `figma-ui-designer` plugin and the bare `figma-ui-designer` skill. They stay in the repo until #167. Install `ui-design`, then remove the old ones, so the old name cannot win a plain-language request.

### History

Per-skill history before the move is in `skills/figma/CHANGELOG.md`.
