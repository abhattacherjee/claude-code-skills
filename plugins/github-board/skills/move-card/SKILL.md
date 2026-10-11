---
name: move-card
description: "Moves a GitHub issue or PR's Project (v2) board card to a target Status column via a deterministic script (scripts/board-move.sh). Use when: (1) moving an issue to 'In Progress' when work starts, (2) moving a card to 'Development Complete'/'In Review'/'Done in develop' when its PR merges, (3) any mid-lifecycle Project v2 status change that promote-shipped (release->Done only) does not cover, (4) listing a board's available Status columns, (5) 'board move' or /github-board-move (the old name of this skill). Covers: projectsV2 board discovery, Status field/option lookup, updateProjectV2ItemFieldValue, fuzzy column matching, --add for items not yet on the board, project auth-scope checks."
metadata:
  version: 2.1.0
---

# GitHub Board Move

## Problem
Moving a Project (v2) card between Status columns mid-lifecycle (e.g. -> **In Progress** at work start, -> **Development Complete** when a PR merges) has no dedicated tool: `promote-shipped` only does release -> **Done**, and `create-board` only builds boards. Otherwise the move means hand-writing `updateProjectV2ItemFieldValue` GraphQL each time.

## Quick Check
```bash
# List the board's Status columns (names vary per board)
"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --list-status --repo OWNER/REPO

# Move a card (fuzzy column match, case-insensitive)
"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --issue 28 --to "In Progress"
"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --pr 31 --to "Development Complete"

# Preview without applying; add the card if it isn't on the board yet
"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --issue 9 --to done --dry-run
"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --issue 9 --to "Up Next" --add

"${CLAUDE_SKILL_DIR}/scripts/board-move.sh" --help
```
Defaults to the current repo and its single linked board; pass `--repo` / `--project <number>` to disambiguate.

## When to use this vs other board skills
| Need | Skill |
|------|-------|
| Move a card to any Status mid-lifecycle (In Progress, Dev Complete, In Review...) | **this skill** |
| Promote shipped issues to **Done** after a release (validated, main-reachability guarded) | `promote-shipped` |
| Create or replicate a board | `create-board` |

This is the tooling for steps 3 (-> In Progress) and 6 (-> post-merge column) of the standing GitHub project workflow.

## Key facts
- **Status column names are board-specific** — there is no canonical set. Run `--list-status` first. `--to` matches case-insensitively (exact, then unique substring); ambiguous or no match errors and prints the options.
- **Auth scope:** discovery / `--list-status` / `--dry-run` need `read:project`; applying a move needs `project`. The script exits `3` with a `gh auth refresh -s project` hint if the write scope is missing.
- **Projects v2 only** (GraphQL `projectsV2`). Classic (REST) projects are not supported.
- **The option id is a plain string** — passed to the mutation via `gh api -f oid=` (not `-F`); a typed `-F` errors.
- **The item must be on the board.** If the issue/PR is not a card yet, pass `--add` (runs `addProjectV2ItemById`); otherwise the script errors with that hint.
- **Post-merge moves set the milestone.** Moving an `--issue` to a post-merge column also sets its milestone to the next-release one, and prints `milestone: <current|none> -> <title>` or `milestone: unchanged (<title>)`. `--dry-run` prints `would set milestone: …` and writes nothing. A post-merge column is one whose resolved name is "Development Complete", "Dev Complete" or "Done in develop" (any case). `move_card.post_merge_columns` in the github-board config replaces those names, and an empty list turns this off. `--pr` moves and other columns never touch the milestone.
- **The next-release milestone** is `milestones.next_release["owner/repo"]` in `~/.config/github-board/config.json` when set. Otherwise it is the open milestone with the lowest version (`vX.Y` or `vX.Y.Z`), sorted by version, not milestone number, above the newest version tag (`gh api repos/O/R/tags`), and a note names the pick. A milestone at or below that tag has shipped, even if it was left open. A configured title that is missing, closed, or at or below that tag, no candidate, an unreadable milestone list, or a failed write prints a warning and sets nothing. The card moves first, and the exit code stays the move's.
- Idempotent — re-running for the same option is a no-op.
- **Lookups are cached** for 7 days under `~/.cache/github-board/` (board list and Status options). A failed move, or a `--to` column missing from the cached options, triggers one automatic refetch; `--no-cache` skips the cache (use it right after linking a second board to the repo).

## See Also
- `promote-shipped` — release -> Done promotion (validated; main-reachability guarded)
- `create-board` — board creation / replication
- `triage-issues` — issue audit, labeling, prioritization
