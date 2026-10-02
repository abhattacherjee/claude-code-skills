# github-board

GitHub workflow skills in one install: create a board from a template, triage issues, plan milestones, plan the week, move cards, promote shipped work to Done, and prune stale branches.

| Skill | Was | What it does |
|---|---|---|
| `create-board` | `create-gh-board` | Copies a template ProjectV2 board onto a repo and verifies it |
| `triage-issues` | `github-issue-triage` | Audits, updates and closes open issues |
| `plan-milestones` | `github-milestone-planning` | Keeps milestones small and themed |
| `plan-week` | `weekly-focus` | Answers "what do I work on next" from a cross-repo board |
| `move-card` | `github-board-move` | Moves a card to any Status column |
| `promote-shipped` | `github-release-board-promote` | Moves shipped cards to Done after a release |
| `prune-branches` | `git-branch-cleanup` | Finds and deletes stale branches |

Agents (dispatched by `create-board` only): `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier`.
