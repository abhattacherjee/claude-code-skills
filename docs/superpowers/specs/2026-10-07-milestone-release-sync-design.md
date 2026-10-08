# Milestone and release sync (#180)

Issue #180 ships as two PRs: #203 (PR A) and #204 (PR B). Their acceptance criteria live in those issues.

## Problem

One milestone field carries two meanings. Work starts in the milestone of its **theme**. Nothing moves it to the milestone of the **release** that ships it. No step compares the milestone with tag containment, so the drift stays hidden until someone notices. It was cleaned up by hand three times: openclaw on 2026-08-28, and claude-code-config on 2026-09-26 and 2026-10-04.

`gh issue edit --milestone <title>` cannot assign a closed milestone. A REST call with the milestone number can: `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`.

## Decisions (2026-10-07)

- **Two PRs.** PR A fixes milestones where the release is already known: `apply-plan.sh` and `promote-shipped`. PR B adds the next-release helper, move-card and plan-milestones step 0.
- **The next-release milestone** is `milestones.next_release["O/R"]` in `~/.config/github-board/config.json` when set. It is a map keyed by repo, because one config serves every repo (corrected while planning PR B). Otherwise it is the open milestone with the lowest version, `vX.Y` or `vX.Y.Z`. It is sorted by version, not by milestone number: in this repo v4.2 is #9 and v4.1 is #13. With no candidate, the helper warns and returns nothing. No marker goes in the milestone description, because plan-milestones prints the description as the theme.
- **/ship is out of scope.** Its post-merge step uses `~/.claude/skills/ship/scripts/board_move.py` (claude-code-config), not move-card. A claude-code-config issue switches it over once PR B lands.

## PR A: write the release milestone where the release is known

### apply-plan.sh

- Every milestone write goes through REST by number. `EXISTING` keeps `{title, number, state}` for each milestone (all states, paginated), so a closed target resolves to its number.
- The new key is `closed_moves: [{issue, to}]`. It needs no rationale and posts no comment. Its targets go through the same exists check, and the dry run prints them apart from `moves`.
- A failed write prints gh's stderr and the response body, and adds the issue number to a failure list. The run still writes the rest of the plan, then exits 1 with `completed with N failure(s): #11 #12` when that list is not empty. Before #203, stderr went to `/dev/null`.

### promote-shipped

- `inventory-board.sh` fetches `milestone { number title state }` for issues and PRs. `find-promotable.sh` passes it through in each candidate.
- `apply-promotions.sh` maps the release tag it already resolves to a milestone. The tag comes from `find_release_for_commit`, or `--release-tag` when given. It tries an exact `vX.Y.Z` title, then `vX.Y`. The milestone list is fetched once per repo (`state=all`, paginated) and cached in the run's `CACHE_DIR`.
- This applies only to the `merged` class. `wontfix` and `nopr` items have no merge commit and keep their milestone.
- With `--no-release-comment`, the release lookup still runs for the milestone check. It is skipped only when `--release-tag` is given.
- Dry run: one more line per item, `would set milestone: <current|none> -> <target> (<tag>)`, printed only when they differ.
- Apply: after the status move, the REST call. A failed milestone write is reported like a comment failure. The board move stays the main effect and is not undone. The summary gets a `Milestones:` count line.
- Invariants to keep: exactly 3 `gh auth status` call sites, exactly 9 promote classes, and the reconcile tests' `\037` projection. The milestone is read from the candidate JSON by item id, not added as a new projected column.

## PR B: set it on merge, and check it on every plan

### Next-release helper

- `lib/config.py next-release-milestone --repo O/R`, with a thin `gb_next_release` wrapper in `lib/config.sh`. It prints `<number>\t<title>`, or nothing plus a warning on stderr, and exits 0 either way. It never guesses silently: the fallback says which milestone it picked.

### move-card

- `board-move.sh` gets the milestone write for issues moved to a post-merge column. Post-merge columns match "development complete", "dev complete" or "done in develop" (any case), or the list in `move_card.post_merge_columns`. A `--pr` move does not touch milestones.
- `--dry-run` prints the change. With no candidate it warns and still moves the card. A failed milestone write warns, and the exit code stays the move's.

### plan-milestones step 0: release reconciliation

- New `scripts/release-reconcile.sh --repo O/R`. It runs on every invocation and prints its result even when clean.
  1. It checks that the current checkout's `origin` is `O/R`, then runs `git fetch --tags origin`.
  2. It lists merged PRs (base `develop` or the default branch) and reads their closing keywords. This is the same keyword rule as find-promotable's fallback, because GitHub records no closing link for merges to a non-default base.
  3. For each closed issue named by a merged PR, it takes the PR's merge commit and finds the first tag that contains it: `git tag --contains <sha> --sort=v:refname | head -1`. Inside a tag, the issue belongs to that release's milestone, mapped as in PR A, even when that milestone is closed. After the last tag, it belongs to the next-release milestone.
  4. It lists each mismatch with its evidence (issue, PR, commit, tag, current and target milestone), and emits `closed_moves` JSON for `apply-plan.sh`.
  5. It flags a closed issue whose linked PR never merged when a merged PR names it (the claude-code-config#221 case).
- SKILL.md gets step 0, and `task-manifest.sh` gets the new task. (`references/triage-criteria.md` already lost "a closed issue in the wrong milestone is harmless" in PR A, #205, because it contradicted `closed_moves`.)

## Limits

- A squashed `release/* -> main` breaks tag containment. promote-shipped already documents this. Step 0 compares the merge commit's date with the last tag's date. Merged before it: a NOTE, and the milestone stays. Merged after it: the next-release milestone, as usual. One side effect: develop work merged before a hotfix tag on main also gets the NOTE, not a move.
- Step 0 refuses a shallow clone (exit 2): a commit it holds can look as if no tag contains it.
- The next-release fallback skips any milestone whose version is at or below the newest version tag, so a shipped milestone left open is never picked. move-card reads the tags with `gh api repos/O/R/tags`; step 0 passes its local newest tag.
- promote-shipped finds releases through GitHub Releases ordered by publish date, so a tag with no Release is not seen. That is unchanged here.
- CI runs the github-board tests on ubuntu only (bash 5). The scripts stay bash 3.2 safe, and the local runs use 3.2.
