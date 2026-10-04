# Changelog

All notable changes to the **dev-flow** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#165). It merges the bare `worktree` (1.0.1) and `changelog-keeper` (1.1.1) skills. Two skills under short names: `worktree` (was `worktree`) and `changelog` (was `changelog-keeper`). Invoke them as `/dev-flow:worktree` and `/dev-flow:changelog`. The old names still match as trigger phrases.

### Changed

- Every script command in the two `SKILL.md` files is written to work from your project directory (checked statically by `check-skill-commands.py`, which now covers this plugin in CI): `"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`. The old text used `~/.claude/skills/<skill>/scripts/...` and a `SCRIPT=` variable, which only worked from a loose copy.
- `worktree/scripts/validate-skill.sh` and `changelog/scripts/validate-skill.sh` are copies of the repo-root `scripts/validate-skill.sh`.

### Deprecated

- The bare `worktree` and `changelog-keeper` skills. They stay in the repo until #167. Install `dev-flow`, then remove the old ones, so the old names cannot win a plain-language request.

### History

Per-skill history before the merge is in `skills/worktree/CHANGELOG.md` and `skills/changelog/CHANGELOG.md`.
