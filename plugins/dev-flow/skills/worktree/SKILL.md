---
name: worktree
description: "Was the worktree skill (/worktree still works as a phrase). Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch. Use when: (1) /worktree command, (2) user wants to work on multiple branches simultaneously, (3) user has multiple Claude Code sessions conflicting on the same branch, (4) user asks to set up parallel development."
metadata:
  version: 1.0.0
---

# Git Worktree for Parallel Sessions

## Problem

Multiple Claude Code sessions sharing one working directory fight over the same branch. Git worktrees give each session its own directory and branch while sharing the same repo.

## Quick Reference

```bash
# From the repo you want to work in:
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" list                          # Show worktrees + branches
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" create <BRANCH>               # Existing branch
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" create --new <NEW_BRANCH>     # New branch from origin/develop
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" remove <BRANCH>               # Clean up (git refuses if there is uncommitted work)
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" remove --force <BRANCH>       # Discards uncommitted work
"${CLAUDE_SKILL_DIR}/scripts/setup-worktree.sh" --help                        # Full usage
```

Replace `<BRANCH>` with a branch name such as `feature/story-10.11`, and `<NEW_BRANCH>` with a new name such as `story-10.12-new-feature` (the script adds the `feature/` prefix).

## Workflow

When invoked, follow these steps:

### Step 1: Show current state
Run the `list` command to show existing worktrees and available branches.

### Step 2: Ask the user what they want
Use AskUserQuestion with options based on what `list` returned:
- Create worktree for an existing feature branch
- Create a new feature branch + worktree
- Remove an existing worktree

### Step 3: Execute
Run the appropriate script command. The script handles:
- Creating the worktree directory as a sibling (e.g., `../repo-name--branch-suffix/`). If that directory exists and is not the branch's worktree (another branch's worktree, or a plain directory), it stops with an error.
- For `create --new`: fetching `origin` (a failed fetch prints a warning), then branching from `origin/develop`, else local `develop`, else the branch `origin/HEAD` names, else `main`. The new branch has no upstream; set one on the first push (`git push -u`).
- Running `npm install` in the worktree root and in each immediate subdirectory that has a `package.json` and no `node_modules`. If any install fails, it names them and exits 1, after printing the `cd` line.

`remove` finds the worktree by branch. If the worktree has uncommitted or untracked work, git refuses and the script exits non-zero. Ask the user before running `remove --force`: it discards that work.

### Step 4: Tell the user what to do next
The script outputs the exact `cd` + `claude` command, quoted so it works when pasted even if the path has a space. Relay this clearly.

The script does not set up Python virtualenvs. See Notes below before
dispatching any work in a Python project.

## Naming Convention

Worktree directories are created as siblings of the repo root:
```
parent-dir/
  repo-name/                          # Main working directory
  repo-name--story-10.11-view/        # Worktree for feature/story-10.11-view
  repo-name--story-10.12-new/         # Worktree for feature/story-10.12-new
```

## Notes

- Each worktree has its own `node_modules` — the script installs them automatically (`--no-install` skips it)
- A branch checked out in one worktree CANNOT be checked out in another (git enforces this)
- Worktrees share the same `.git` history — commits are visible across all worktrees
- Use the script's `remove` command (or `git worktree remove`) to clean up when done. Neither removes a worktree with uncommitted work unless forced.
- **Python projects get no virtualenv.** `.venv` is untracked, so a new worktree
  starts without one. Run the project's own venv setup script, if it has one,
  before anything else. If a worktree has no `.venv`, an editable install in the
  parent checkout's venv silently resolves imports to the PARENT's source. A test
  can then look like it runs against the worktree while it imports another tree.
  Check with `python -c "import <pkg>; print(<pkg>.__file__)"` before dispatching
  any work. The path should be inside the worktree, not the main checkout.
