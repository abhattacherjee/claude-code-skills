# Changelog

All notable changes to the **worktree** skill (was `worktree`, a bare skill) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `dev-flow` plugin as `dev-flow:worktree` (#165). Same workflow and script as `worktree` 1.0.1. `/worktree` still matches as a trigger phrase.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh"`, with `<BRANCH>` and `<NEW_BRANCH>` for the names. The old text called `~/.claude/skills/worktree/scripts/setup-worktree.sh`, which only worked from a loose copy (#165).
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.
- The "See Also" link to the standalone `worktree` repo is gone. That repo is being archived (#157).

## History before 1.0.0 (as `worktree`)

### worktree 1.0.1 - 2026-10-03

- Note on Python virtualenvs: a new worktree has no `.venv`, so run the project's own venv setup script, and check that imports resolve inside the worktree (`python -c "import <pkg>; print(<pkg>.__file__)"`). Carried over from the live copy ahead of archiving the standalone repo (#157).

### worktree 1.0.0 - 2026-02-24

Initial public release.

- **SKILL.md** — creates isolated git worktrees for parallel Claude Code sessions, each on its own branch.
- **scripts/setup-worktree.sh** — `list`, `create`, `create --new`, `remove` and `install` commands.
