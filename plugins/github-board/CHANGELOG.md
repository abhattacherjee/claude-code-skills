# Changelog

All notable changes to the **github-board** plugin are documented here.

## [1.0.1] - 2026-10-04

### Changed

- `prune-branches` See Also names `dev-flow:worktree` (was the bare `worktree` skill), after the skill moved into the `dev-flow` plugin (#165). `prune-branches` is at 2.0.1.
- `test_marketplace_lists_the_plugin` checks that the marketplace and `plugin.json` versions agree. It compared both with the literal `1.0.0`, so every version bump failed it.

## [1.0.0] - 2026-10-02

### Added

- First release (#146). Seven skills under short names: `create-board` (was `create-gh-board`), `triage-issues` (was `github-issue-triage`), `plan-milestones` (was `github-milestone-planning`), `plan-week` (was `weekly-focus`), `move-card` (was `github-board-move`), `promote-shipped` (was `github-release-board-promote`) and `prune-branches` (was `git-branch-cleanup`). Four agents for `create-board`: `template-inspector`, `board-creator`, `workflow-syncer`, `board-verifier` (were `gh-board-*`).
- Per-user config at `${XDG_CONFIG_HOME:-~/.config}/github-board/config.json` (`plan_week`, `create_board`, optional `prune_branches.tracking_issue_authors`). A command whose section is missing exits 4 and names the init to run; a dangling config symlink exits 2.
- 7-day metadata cache at `${XDG_CACHE_HOME:-~/.cache}/github-board/`. Keys are tuples hashed into the file name; each entry stores its tuple and a mismatch is a miss.
- `plan-week` launchd jobs run from a copy in `~/.local/share/github-board/<version>/` reached through the link `current`, never from the plugin cache, so plugin upgrades cannot break them.

### Changed

- README: the Phase 3 rollback through the bare `weekly-focus` installer works only before Phase 4; after that, re-run the plugin's `install-launchd.sh`. Phase 4 now says to move the callers of the old names first (#147).

### Security

- `promote-shipped` credits only pull requests from the issue's own repository; a foreign PR that claims an issue, merged or not, holds it (`hold-foreign-pr`).
- `promote-shipped` credits every closing form GitHub accepts (`Fixes: #N`, the issue's own URL), so a develop-only merge is held as `hold-unreleased`, and an unmerged closing PR holds the issue as `hold-unmerged-pr`; neither falls through to `nopr`.
- `prune-branches` never deletes a temp branch when its open-PR lookup fails: the branch is reported as `UNKNOWN` and the script exits 3.
- `prune-branches` closes a Dependabot PR only for an issue that names it exactly (`PR #<n>` or its URL) and was written by the repo owner or an allowlisted login.
- `prune-branches` treats a Dependabot PR as superseded only by a newer PR for the exact same package name; `socket.io` no longer supersedes `socket-io`, and `foo` never matches `foo-bar` or `@scope/foo`, and numeric-looking names (X-010) such as `1e2` and `100`, or `1.0` and `1`, stay distinct.
