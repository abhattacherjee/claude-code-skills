# Changelog

All notable changes to the **github-board** plugin are documented here.

## [1.2.2] - 2026-10-09

### Changed

- `triage-issues` 2.0.1: Phase 2 links `references/verification-patterns.md` (it was never linked) in place of the shorter inline table; cut the batch-label loop and two `gh` basics from Notes (#210).
- `create-board` 3.0.1: cut the Sub-Agent Registry, which repeated the phase table (#210).
- `plan-milestones` 2.2.1: cut the key rule that repeated "Always pass `--unassigned`" (#210).
- `promote-shipped` 2.1.3: `references/projects-v2-graphql-snippets.md` starts with a Contents list (#210).

## [1.2.1] - 2026-10-08

### Fixed

- `promote-shipped` 2.1.2: `find-promotable.sh` matches issue URLs on `$GH_HOST` (else github.com), dots escaped, like `release-reconcile.sh` (#208).
- `tests/test_jq_regex_re2.py` flags the forms Go RE2 rejects and local jq (Oniguruma) accepts, and nothing else (#208).
  - Look-around `(?<=`, `(?<!`, `(?=`, `(?!`; atomic `(?>`; absent `(?~`.
  - Backreferences and calls: `\1` to `\9`, `\k<n>`, `\k'n'`, `\g<n>`, `\g<1>`.
  - Possessive quantifiers `*+`, `++`, `?+`, `}+`. A plain `a+` or `[0-9]+` passes.
  - A named capture `(?<name>...)` or `(?P<name>...)` is valid Go RE2 and passes.
- `find-promotable.sh` checks `repo`, `num` and `GH_HOST` with `[[ =~ ]]` on the whole value. `grep -Eq` passed a multi-line value if any one line fit. A refused value still reports FAILED, so the card is held as `hold-discovery-failed`, never promoted as `nopr` (#208).

## [1.2.0] - 2026-10-07

### Added

- `lib/config.py next-release-milestone --repo O/R` (`gb_next_release`) prints `<number>\t<title>` of the milestone that merged work belongs to (#204).
  - It is `milestones.next_release["O/R"]` from the config when that is set.
  - Otherwise it is the open milestone with the lowest version (`vX.Y` or `vX.Y.Z`), sorted by version, not milestone number, and a note names the pick.
  - It skips any milestone at or below the newest version tag, so a shipped milestone left open is never picked. The tags come from `gh api repos/O/R/tags --paginate`, or from `--after-tag TAG` (`""` means no tags).
  - A configured title that is missing, closed, or at or below the newest tag warns and prints nothing. So do two titles with the same version, and no candidate at all. The exit code is 0.
- `lib/config.py milestone-for-tag --repo O/R --tag TAG` (`gb_milestone_for_tag`) maps a release tag to its milestone with the #203 rules, or prints `skip\t<reason>` (#204).
- Both commands read `gh api repos/O/R/milestones?state=all&per_page=100 --paginate` and take `--cache FILE`. A milestone or tag list that fails, is empty, or is not a list exits 2 (#204).
- Config: optional `milestones.next_release` (a map of `"owner/repo"` to a milestone title) and `move_card.post_merge_columns` (a list of column names) (#204).
  - The validator refuses a `next_release` that is not a map, a key that is not `owner/repo` or has a `.` or `..` part, an empty title, and one repo listed twice in different case.
  - It refuses a `post_merge_columns` that is not a list of non-empty strings.
- `move-card` 2.1.0: an `--issue` moved to a post-merge column also gets the next-release milestone (#204).
  - Post-merge columns are "Development Complete", "Dev Complete" and "Done in develop" (any case), or `move_card.post_merge_columns`, which replaces them.
  - The card moves first. A milestone problem warns and keeps the exit code.
  - `--pr` moves and other columns make no milestone call.
- `plan-milestones` 2.2.0: step 0, `scripts/release-reconcile.sh --repo O/R [--json FILE] [--no-fetch]` (#204).
  - It refuses (exit 2) a checkout of another repo, a host other than github.com (`$GH_HOST` when set), and a shallow clone. Then it runs `git fetch --tags origin`.
  - It checks each closed issue that a merged PR into `develop` or the default branch names against the first release tag containing the merge commit. After the last tag, the target is the next-release milestone. The earliest release wins. Tags are ordered by version, with the leading `v` optional.
  - A merge commit that no tag contains but that is older than the newest release tag (`vX.Y.0` or `vX.Y`; a squashed release) gets a `NOTE` and no move. It applies only when the release tag's commit is not a merge (a squashed or direct-commit release). Hotfix tags (`vX.Y.Z`, Z > 0) are ignored for this date test. Known false NOTE: develop work merged during a squashed release's window; it fails safe, with no write.
  - Closing keywords are whole words ("Encloses #10" does not count). An issue URL counts only on the validated host: github.com, or `$GH_HOST`.
  - It flags a closed issue whose linked PRs never merged while a merged PR, or a commit on develop or the default branch, names it. The line names the branch.
  - It ends with `release check: N issues checked, M mismatches, K flagged`. "Checked" counts compared milestones; issues that only a commit names are counted apart.
  - `--json` writes `closed_moves` for `apply-plan.sh`. An old file is deleted at the start of every run.
  - Exit 1, with no JSON, when the result is incomplete: git, gh or jq is missing, the fetch fails, a merged-PR list fails, is empty or hits the 1000-PR limit, a merged PR has no merge commit, the milestone list fails, an issue cannot be read, or a merge commit is not in the clone.
  - `task-manifest.sh` lists step 0 first in `refocus` (7 tasks) and `audit-only` (4 tasks).

### Changed

- `promote-shipped` 2.1.1: `apply-promotions.sh` maps tags through the shared `milestone-for-tag`, not its own copy of the rules. The three skip warnings changed wording (#204).

### Fixed

- `find-promotable.sh` no longer reads a closing keyword inside a longer word ("Encloses #42") (#204).

## [1.1.0] - 2026-10-07

### Added

- `plan-milestones` 2.1.0: `apply-plan.sh` accepts `closed_moves: [{issue, to}]`, which set the milestone of a closed issue with no rationale and no comment. Each `closed_moves` issue's state is read before any write; an open issue, or one whose state cannot be read, is refused (#203).
- `promote-shipped` 2.1.0: `apply-promotions.sh` sets the release milestone of each promoted `merged` item. It maps the release tag (auto-detected, or `--release-tag`) to the milestone titled with the exact `vX.Y.Z`, else `vX.Y`, with the leading `v` optional. The dry run shows `would set milestone: <current|none> -> <target> (<tag>)`, or `milestone: skipped — <reason>` when no milestone matches, two match, or the tag is not a version; each skip also prints a warning and changes nothing. A `Milestones:` summary line appears when at least one item is `merged`. `nopr` and `wontfix` items keep their milestone (#203).

### Changed

- `apply-plan.sh` and `apply-promotions.sh` write milestones with `gh api -X PATCH repos/O/R/issues/N -F milestone=<number> --jq .milestone.number`. Unlike `gh issue edit --milestone`, this can assign a closed milestone. A reply that names another milestone counts as a failed write, and on an HTTP error the response body (a 422's `errors[]`) is printed with gh's error (#203).
- `apply-plan.sh` prints gh's error when a write fails, runs the rest of the plan, and exits 1 with `completed with N failure(s): #11 #12`. It used to send gh's error to `/dev/null` (#203).
- `apply-plan.sh` checks the whole plan before any write and exits 1 on: a `moves`, `closed_moves`, `create_milestones` or `keep` that is not a list, or an entry that is not an object (this used to crash jq with exit 5); a repo that is not `OWNER/REPO` or has a `.` or `..` part; an issue that is not a positive integer; a `create_milestones` entry without a non-empty string title; an issue listed more than once; a target title that two milestones share; and an empty milestone-list reply (#203).
- `apply-plan.sh` dry run marks a `create_milestones` title that already exists `EXISTS (<state>), will not create`, as `--apply` does (#203).
- `apply-promotions.sh --no-release-comment` still looks up the release, to set the milestone. A failed milestone write or milestone list is reported and counted, and never undoes the board move or changes the exit code. Its `ACTION NEEDED` text says to re-run against the same candidates file with `--apply --no-release-comment` (#203).
- `apply-promotions.sh` refuses a milestone write for a candidate repo with a `.` or `..` part (#203).
- `inventory-board.sh` fetches `milestone { number title state }` for issues and pull requests, and `find-promotable.sh` passes it through in each candidate (#203).
- `plan-milestones` `references/triage-criteria.md` no longer says a closed issue in the wrong milestone is harmless: it belongs in the milestone of the release that shipped it, fixed with `closed_moves` (#203).

### Fixed

- `apply-plan.sh` posted a rationale with a newline or a tab as the two characters `\n` or `\t`. The comment now keeps them (#203).
- `apply-plan.sh --plan` or `--repo` with no value exited 1 with no message. It now says which flag needs a value and exits 2, the documented usage code (#203).
- `apply-plan.sh` captured a milestone-create reply together with gh's stderr, so a warning on stderr crashed the run after the first create (exit 2). stderr is now read apart, the whole reply must be a number, and a failed create is printed, counted, and the run goes on (#203).

### Internal

- The two forced-tag test groups in `test_apply_promotions_reconcile.py` run with a `gh` stub that fails every call. The new milestone lookup would otherwise have called the real `gh` (#203).
- The `apply-plan.sh` test stubs list closed milestones only with `state=all`, and pages after the first only with `--paginate`, so dropping either flag fails a test (#203).

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
