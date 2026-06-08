---
name: github-board-move
description: "Moves a GitHub issue or PR's Project (v2) board card to a target Status column via a deterministic script (scripts/board-move.sh). Use when: (1) moving an issue to 'In Progress' when work starts, (2) moving a card to 'Development Complete'/'In Review'/'Done in develop' when its PR merges, (3) any mid-lifecycle Project v2 status change that github-release-board-promote (release->Done only) does not cover, (4) listing a board's available Status columns. Covers: projectsV2 board discovery, Status field/option lookup, updateProjectV2ItemFieldValue, fuzzy column matching, --add for items not yet on the board, project auth-scope checks."
metadata:
  version: 1.0.0
---

# GitHub Board Move

## Problem
Moving a Project (v2) card between Status columns mid-lifecycle (e.g. -> **In Progress** at work start, -> **Development Complete** when a PR merges) has no dedicated tool: `github-release-board-promote` only does release -> **Done**, and `create-gh-board` only builds boards. Otherwise the move means hand-writing `updateProjectV2ItemFieldValue` GraphQL each time.

## Quick Check
```bash
# List the board's Status columns (names vary per board)
./scripts/board-move.sh --list-status --repo OWNER/REPO

# Move a card (fuzzy column match, case-insensitive)
./scripts/board-move.sh --issue 28 --to "In Progress"
./scripts/board-move.sh --pr 31 --to "Development Complete"

# Preview without applying; add the card if it isn't on the board yet
./scripts/board-move.sh --issue 9 --to done --dry-run
./scripts/board-move.sh --issue 9 --to "Up Next" --add

./scripts/board-move.sh --help
```
Defaults to the current repo and its single linked board; pass `--repo` / `--project <number>` to disambiguate.

## When to use this vs other board skills
| Need | Skill |
|------|-------|
| Move a card to any Status mid-lifecycle (In Progress, Dev Complete, In Review...) | **this skill** |
| Promote shipped issues to **Done** after a release (validated, main-reachability guarded) | `github-release-board-promote` |
| Create or replicate a board | `create-gh-board` |

This is the tooling for steps 3 (-> In Progress) and 6 (-> post-merge column) of the standing GitHub project workflow.

## Key facts
- **Status column names are board-specific** — there is no canonical set. Run `--list-status` first. `--to` matches case-insensitively (exact, then unique substring); ambiguous or no match errors and prints the options.
- **Auth scope:** discovery / `--list-status` / `--dry-run` need `read:project`; applying a move needs `project`. The script exits `3` with a `gh auth refresh -s project` hint if the write scope is missing.
- **Projects v2 only** (GraphQL `projectsV2`). Classic (REST) projects are not supported.
- **The option id is a plain string** — passed to the mutation via `gh api -f oid=` (not `-F`); a typed `-F` errors.
- **The item must be on the board.** If the issue/PR is not a card yet, pass `--add` (runs `addProjectV2ItemById`); otherwise the script errors with that hint.
- Idempotent — re-running for the same option is a no-op.

## See Also
- `github-release-board-promote` — release -> Done promotion (validated; main-reachability guarded)
- `create-gh-board` — board creation / replication
- `github-issue-triage` — issue audit, labeling, prioritization
