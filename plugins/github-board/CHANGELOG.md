# Changelog

All notable changes to the **github-board** plugin are documented here.

## [1.0.0] - 2026-10-02

### Added

- First release (#146). Seven skills under short names: `create-board` (was `create-gh-board`), `triage-issues` (was `github-issue-triage`), `plan-milestones` (was `github-milestone-planning`), `plan-week` (was `weekly-focus`), `move-card` (was `github-board-move`), `promote-shipped` (was `github-release-board-promote`) and `prune-branches` (was `git-branch-cleanup`). Four agents for `create-board`: `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier` (were `gh-board-*`).
- Per-user config at `${XDG_CONFIG_HOME:-~/.config}/github-board/config.json` (`plan_week`, `create_board`, optional `prune_branches.tracking_issue_authors`). A command whose section is missing exits 4 and names the init to run; a dangling config symlink exits 2.
- 7-day metadata cache at `${XDG_CACHE_HOME:-~/.cache}/github-board/`. Keys are tuples hashed into the file name; each entry stores its tuple and a mismatch is a miss.
- `plan-week` launchd jobs run from a copy in `~/.local/share/github-board/<version>/` reached through the link `current`, never from the plugin cache, so plugin upgrades cannot break them.

### Security

- `promote-shipped` credits only pull requests from the issue's own repository; a foreign PR that claims an issue holds it (`hold-foreign-pr`).
- `promote-shipped` credits every closing form GitHub accepts (`Fixes: #N`, the issue's own URL), so a develop-only merge is held as `hold-unreleased`, and an unmerged closing PR holds the issue as `hold-unmerged-pr`; neither falls through to `nopr`.
- `prune-branches` never deletes a temp branch when its open-PR lookup fails: the branch is reported as `UNKNOWN` and the script exits 3.
- `prune-branches` closes a Dependabot PR only for an issue that names it exactly (`PR #<n>` or its URL) and was written by the repo owner or an allowlisted login.
