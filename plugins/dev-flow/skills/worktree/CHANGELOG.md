# Changelog

All notable changes to the **worktree** skill (was `worktree`, a bare skill) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `dev-flow` plugin as `dev-flow:worktree` (#165). Same workflow as `worktree` 1.0.1; the script fixes are under Fixed. `/worktree` still matches as a trigger phrase.
- Every command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh"`, with `<BRANCH>` and `<NEW_BRANCH>` for the names. The old text called `~/.claude/skills/worktree/scripts/setup-worktree.sh`, which only worked from a loose copy (#165).
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.
- The "See Also" link to the standalone `worktree` repo is gone. That repo is being archived (#157).

### Fixed

- `setup-worktree.sh`: `remove` always passed `--force` to git, so it deleted uncommitted and untracked work. Git now refuses a dirty worktree, the script prints git's message and exits non-zero, and `remove --force` is the explicit way to discard that work. Git still deletes git-ignored files (`.env`, local config) without a word, so without `--force` the script now refuses (exit 1) a worktree that has ignored files outside `node_modules/`, lists up to 10 and says how many more.
- Worktrees were found by directory name, so `feature/x/y` and `feature/x-y` shared `repo--x-y`: `create feature/x-y` said it existed, and `remove feature/x-y` removed the other branch's worktree. They are now found by branch (`git worktree list --porcelain`). `create` exits 1 when the directory is another branch's worktree or a plain directory, and `remove` exits 1 when the branch has no worktree.
- `create --new` always branched from `origin/develop`, so it failed in a repo with no `develop` or no `origin`, and a failed fetch was hidden. The base is now `origin/develop`, else `develop`, else the branch `origin/HEAD` names, else `main`, else an error. A failed fetch prints a warning. The new branch is made with `--no-track`, so it does not track `origin/develop`.
- The printed `cd ... && claude`, `code ...` and `remove` lines were not quoted, so a path with a space broke when pasted. They are quoted with `printf %q`. The `remove` and `install` lines named the script by its bare name, which is not on `PATH`, so pasting them gave `command not found`. They now read `cd <repo> && <absolute script path> remove|install <branch>`, so they work when pasted from any directory.
- `npm install` ran only in three hard-coded directories from one project (`backend`, `frontend`, `mcp-events-server`), and a failed install still counted as installed and the worktree as ready. It now runs in the worktree root and in each immediate subdirectory that has a `package.json` and no `node_modules`. It counts only successes, names the failures and exits 1, after printing the `cd` line.

## History before 1.0.0 (as `worktree`)

### worktree 1.0.1 - 2026-10-03

- Note on Python virtualenvs: a new worktree has no `.venv`, so run the project's own venv setup script, and check that imports resolve inside the worktree (`python -c "import <pkg>; print(<pkg>.__file__)"`). Carried over from the live copy ahead of archiving the standalone repo (#157).

### worktree 1.0.0 - 2026-02-24

Initial public release.

- **SKILL.md** — creates isolated git worktrees for parallel Claude Code sessions, each on its own branch.
- **scripts/setup-worktree.sh** — `list`, `create`, `create --new`, `remove` and `install` commands.
