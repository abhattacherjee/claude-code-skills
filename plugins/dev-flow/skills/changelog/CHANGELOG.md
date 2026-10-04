# Changelog

All notable changes to the **changelog** skill (was `changelog-keeper`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `dev-flow` plugin as `dev-flow:changelog` (#165). Same workflow and script as `changelog-keeper` 1.1.1. The old name still matches as a trigger phrase.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/update-changelog.sh"`, with `<REPO_DIR>` for another repo. The old text set `SCRIPT=~/.claude/skills/changelog-keeper/...` in one block and read `$SCRIPT` in others, which only worked from a loose copy (#165).
- The newline-pitfall example sets `EXISTING` and `NEW_ENTRY`, so the block runs on its own.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

## History before 1.0.0 (as `changelog-keeper`)

### changelog-keeper 1.1.1 - 2026-02-24

- **Bash Newline Pitfall** — corrected the fix: `printf '%s\n\n'` inside `$()` also loses trailing newlines. The real fix is adding blank lines at the concatenation point, not in the variable assignment.

### changelog-keeper 1.1.0 - 2026-02-24

- **Multi-Script CHANGELOG Coordination** section — patterns for when multiple scripts (sync + release) modify the same CHANGELOG:
  - Format-aware detection to prevent sync entries from clobbering release entries
  - Bash newline pitfall with `printf` fix
  - Semver tag filtering (`git tag -l 'v[0-9]*'` vs `git describe --tags`)

### changelog-keeper 1.0.0 - 2026-02-24

Initial public release.

- **SKILL.md** — keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/update-changelog.sh** — the generator.
