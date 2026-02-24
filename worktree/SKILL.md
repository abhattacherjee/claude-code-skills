---
name: worktree
description: "Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch. Use when: (1) /worktree command, (2) user wants to work on multiple branches simultaneously, (3) user has multiple Claude Code sessions conflicting on the same branch, (4) user asks to set up parallel development."
metadata:
  version: 1.0.0
---

# Git Worktree for Parallel Sessions

## Problem

Multiple Claude Code sessions sharing one working directory fight over the same branch. Git worktrees give each session its own directory and branch while sharing the same repo.

## Quick Reference

```bash
# From the repo root:
~/.claude/skills/worktree/scripts/setup-worktree.sh list                                  # Show worktrees + branches
~/.claude/skills/worktree/scripts/setup-worktree.sh create feature/story-10.11             # Existing branch
~/.claude/skills/worktree/scripts/setup-worktree.sh create --new story-10.12-new-feature   # New branch from develop
~/.claude/skills/worktree/scripts/setup-worktree.sh remove feature/story-10.11             # Clean up
~/.claude/skills/worktree/scripts/setup-worktree.sh --help                                 # Full usage
```

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
- Creating the worktree directory as a sibling (e.g., `../repo-name--branch-suffix/`)
- Fetching from remote if needed
- Running `npm install` in backend/frontend/mcp-events-server if node_modules is missing

### Step 4: Tell the user what to do next
The script outputs the exact `cd` + `claude` command. Relay this clearly.

## Naming Convention

Worktree directories are created as siblings of the repo root:
```
parent-dir/
  repo-name/                          # Main working directory
  repo-name--story-10.11-view/        # Worktree for feature/story-10.11-view
  repo-name--story-10.12-new/         # Worktree for feature/story-10.12-new
```

## Notes

- Each worktree has its own `node_modules` — the script installs them automatically
- A branch checked out in one worktree CANNOT be checked out in another (git enforces this)
- Worktrees share the same `.git` history — commits are visible across all worktrees
- Use `git worktree remove` (or the script's `remove` command) to clean up when done

## See Also

- **GitHub**: https://github.com/abhattacherjee/worktree — install instructions, changelog, license
