# Changelog

All notable changes to the **github-board** plugin are documented here.

## [1.1.0] - 2026-10-07

### Added

- `plan-milestones` 2.1.0: `apply-plan.sh` accepts `closed_moves: [{issue, to}]`, which set the milestone of a closed issue with no rationale and no comment (#203).
- `promote-shipped` 2.1.0: `apply-promotions.sh` sets the release milestone of each promoted `merged` item. It maps the release tag (auto-detected, or `--release-tag`) to the milestone titled with the exact `vX.Y.Z`, else `vX.Y`, with the leading `v` optional. The dry run shows `would set milestone: <current|none> -> <target> (<tag>)`, and the summary gets a `Milestones:` line. `nopr` and `wontfix` items keep their milestone. No match, or two matches, prints a warning and changes nothing (#203).

### Changed

- `apply-plan.sh` and `apply-promotions.sh` write milestones with `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`, so a closed milestone works. `gh issue edit --milestone` cannot assign one (#203).
- `apply-plan.sh` prints gh's error when a milestone write fails, runs the rest of the plan, and exits 1. It used to send gh's error to `/dev/null`. It refuses, before any write, a target title that two milestones share, an issue that is not a positive integer, a repo that is not `OWNER/REPO`, and an issue listed more than once (#203).
- `apply-promotions.sh --no-release-comment` still looks up the release, to set the milestone. A failed milestone write or milestone list is reported and counted, and never undoes the board move or changes the exit code (#203).
- `inventory-board.sh` fetches `milestone { number title state }` for issues and pull requests, and `find-promotable.sh` passes it through in each candidate (#203).

### Fixed

- `apply-plan.sh` posted a rationale with a newline or a tab as the two characters `\n` or `\t`. The comment now keeps them (#203).
- `apply-plan.sh --plan` or `--repo` with no value exited 1 with no message. It now says which flag needs a value and exits 2, the documented usage code (#203).
- The two forced-tag test groups in `test_apply_promotions_reconcile.py` run with a `gh` stub that fails every call. The new milestone lookup would otherwise have called the real `gh` (#203).

## [1.0.2] - 2026-10-06

### Changed

- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).

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
