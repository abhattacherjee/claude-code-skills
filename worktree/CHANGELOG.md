# Changelog

All notable changes to this project will be documented in this file.

## [1.0.1] - 2026-10-03

### Added

- Note on Python virtualenvs: a new worktree has no `.venv`, so run the project's own venv setup script, and check that imports resolve inside the worktree (`python -c "import <pkg>; print(<pkg>.__file__)"`). Carried over from the live copy ahead of archiving the standalone repo (#157).

## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch.
- **scripts/** — automation scripts:  - `setup-worktree.sh`
