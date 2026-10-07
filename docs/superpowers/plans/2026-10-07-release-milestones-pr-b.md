# Release milestones, PR B (#204) Implementation Plan

> **For agentic workers:** one implementation pass (ship Phase 4 default). Follow TDD per task and commit per task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Set the next-release milestone when an issue's card moves to a post-merge column, and make plan-milestones check every closed issue's milestone against the release that shipped it.

**Architecture:** One shared Python helper in `lib/config.py` owns milestone resolution: the next-release milestone, and tag to milestone. `board-move.sh` calls it when the target column is post-merge. A new `release-reconcile.sh` uses `git tag --contains` and the same helper, and emits `closed_moves` JSON for `apply-plan.sh` (PR A, #205).

**Tech Stack:** Python 3.9+ standard library (lib/config.py), bash 3.2-safe shell, jq, gh, git; pytest with stubbed `gh` and real temporary git repos.

**Spec:** `docs/superpowers/specs/2026-10-07-milestone-release-sync-design.md` ("Decisions" and "PR B"). Acceptance criteria: issue #204.

## Global Constraints

- Bash 3.2 safe. Python 3.9 compatible (CI uses 3.9 for docs-drift; the github-board job uses the runner's python3).
- No test touches GitHub. Every `gh` call is stubbed. Git tests build a throwaway repo under `tmp_path`, with tags and merge commits. Never the real checkout.
- Milestone writes use REST by number: `gh api -X PATCH repos/O/R/issues/N -F milestone=<n> --jq .milestone.number`, and the reply is checked. This is the same pattern as apply-plan.sh and apply-promotions.sh after #205; read them first.
- Exact-title rules match PR A: a tag maps to an exact `vX.Y.Z` title, then `vX.Y`, with the leading `v` optional; two matches is ambiguous and changes nothing. The next-release fallback sorts open milestones by **version**, not number. In this repo v4.2 is #9 and v4.1 is #13, and v4.1 must win.
- Fix the class: once the shared helper exists, `apply-promotions.sh`'s `milestone_for_tag` should call it rather than keep a second copy, **if** every PR A test in `tests/test_apply_promotions_milestone.py` still passes unchanged. If that migration would need test edits, leave apply-promotions alone and say why.
- Run every job in `.github/workflows/validate-skill.yml` locally before pushing, plus `./scripts/commit-preflight.sh`. Stage files by name.
- Commit trailer: `Co-Authored-By: <the model you are> <noreply@anthropic.com>`.

## Review Focus

1. Several open milestones that are not versions (`Backlog`, `Someday`) mixed with `v4.1`, `v4.10` and `v4.2`. The pick is v4.1. `v4.10` sorts after `v4.2`. Non-version titles are never picked.
2. A config entry naming a milestone that does not exist, or is closed. Warn and fall back? No: an explicit choice that is wrong must be an error the user sees. Print a warning and set nothing.
3. move-card on a `--pr` card, or to a column that is not post-merge: no milestone call at all.
4. Reconcile on a repo whose tags are not fetched locally, a shallow clone, and a checkout of a different repo than `--repo`.
5. An issue named by two merged PRs, one inside v4.0.0 and one after it: the earliest release wins (it shipped there first). Say so in the output.

---

### Task 1: Shared milestone helper

**Files:**
- Modify: `plugins/github-board/lib/config.py` (new functions, a CLI subcommand next to `get`, and an optional `milestones` section validator)
- Modify: `plugins/github-board/lib/config.sh` (thin `gb_next_release` and `gb_milestone_for_tag` wrappers)
- Test: new `plugins/github-board/tests/test_milestone_helper.py`

**Interfaces:**
- `config.py next-release-milestone --repo O/R`: prints `<number>\t<title>` and exits 0. With no candidate it prints nothing, warns on stderr, and exits 0. If the milestone list cannot be read, it exits 2 with the reason on stderr. Config: `{"milestones": {"next_release": {"O/R": "v4.1"}}}`. A configured title that does not exist or is closed prints a warning, prints nothing on stdout, and exits 0.
- `config.py milestone-for-tag --repo O/R --tag vX.Y.Z`: prints `<number>\t<title>`, or `skip\t<reason>`. Exits 2 when the list cannot be read. Same rules as PR A's `milestone_for_tag` in apply-promotions.sh.
- Both read milestones with `gh api repos/O/R/milestones?state=all&per_page=100 --paginate`. They treat empty output or a non-array page as a failure (exit 2), never as an empty list.
- The fallback warning names what it picked: `next-release milestone: v4.1 (lowest open version; set milestones.next_release to choose)`.

- [ ] **Step 1: Failing tests** with a stubbed gh, covering:
  - the config wins;
  - a config title that is missing or closed warns and prints nothing;
  - the lowest open version wins over the lowest number;
  - `v4.10` versus `v4.2`;
  - non-version titles are ignored;
  - no candidate warns and prints nothing;
  - the list fails, or is empty, or page 2 holds the answer: exit 2, or the right pick;
  - each tag-mapping case from PR A's tests;
  - the config validator refuses a non-map `next_release` and a repo key not shaped `O/R`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; they pass.** Then try moving `apply-promotions.sh`'s `milestone_for_tag` onto `gb_milestone_for_tag`, and run `tests/test_apply_promotions_milestone.py` unchanged. Keep the change only if it is green.
- [ ] **Step 5: Mutation check** of each rule; report the table.
- [ ] **Step 6: Commit.** `github-board: shared next-release and tag-to-milestone helper (#204)`

### Task 2: move-card sets the next-release milestone on post-merge columns

**Files:**
- Modify: `plugins/github-board/skills/move-card/scripts/board-move.sh` (after the column is resolved, about :168-181; a dry-run print, about :213-216; and after the move, about :218-223)
- Modify: `plugins/github-board/skills/move-card/SKILL.md` and its CHANGELOG
- Test: new `plugins/github-board/tests/test_board_move_milestone.py`. Reuse `gbtest.install_fake_gh` and the `move_routes()` pattern in `tests/test_board_cache.py:108-121`.

**Interfaces:**
- A post-merge column has a resolved name matching (any case) "development complete", "dev complete" or "done in develop", or one of the names in `move_card.post_merge_columns` from config. The config list replaces the built-in list when it is set.
- Only `--issue` moves set a milestone. `--pr` and non-post-merge columns make no milestone call.
- Output: `milestone: <current|none> -> <title>`, or `milestone: unchanged (<title>)`, or a warning line. `--dry-run` prints `would set milestone: …` and writes nothing.
- A milestone failure or a missing candidate warns. The exit code stays the move's. The move happens first, so a milestone problem never blocks the card.
- The current milestone comes from the item lookup at about :183-190. Add `milestone{number title}` to that query rather than adding a call.

- [ ] **Step 1: Failing tests:**
  - a post-merge move sets the milestone (PATCH with the right number);
  - already in the right milestone gives no PATCH;
  - `--dry-run` shows the change and makes no PATCH;
  - no candidate warns, the card still moves, exit 0;
  - a failed PATCH or a wrong reply number warns, exit 0;
  - `--pr` makes no call;
  - a non-post-merge column makes no call;
  - a config list overrides the built-in names;
  - a substring-resolved column ("dev complete" resolving to "Development Complete") counts.
- [ ] **Steps 2-5:** watch them fail, implement, watch them pass, run the mutation check.
- [ ] **Step 6: Commit.** `move-card: set the next-release milestone on post-merge columns (#204)`

### Task 3: plan-milestones step 0, release reconciliation

**Files:**
- Create: `plugins/github-board/skills/plan-milestones/scripts/release-reconcile.sh`
- Modify: `plugins/github-board/skills/plan-milestones/SKILL.md` (step 0 before step 1, and the task table), `scripts/task-manifest.sh` (add the step-0 task to `refocus` and `audit-only`)
- Test: new `plugins/github-board/tests/test_release_reconcile.py`. It builds a real git repo in `tmp_path`: develop and main branches, squash commits on develop, a release merge commit on main tagged `v0.5.0`, and squash commits after the tag. The remote `origin` is a bare repo in `tmp_path`, so `git fetch --tags origin` works offline. gh is stubbed for merged PRs (number, body, mergeCommit.oid, baseRefName), issues (number, state, stateReason, milestone) and milestones.

**Interfaces:**
- `release-reconcile.sh --repo O/R [--json FILE] [--no-fetch]`.
  - It refuses (exit 2) when `git remote get-url origin` does not name `O/R` (https or ssh form).
  - It runs `git fetch --tags origin` unless `--no-fetch` is given. A failed fetch exits 1.
  - It warns when the repo is a shallow clone.
- PRs come from `gh pr list --state merged --base <b> --limit 1000 --json number,body,mergeCommit,baseRefName`, for `develop` and the default branch. Closing keywords use the same regex as find-promotable.sh's fallback. Copy it exactly, and point a comment at the source.
- Per issue named by a merged PR:
  - The first containing tag is `git tag --contains <sha> --sort=v:refname`, keeping the first tag shaped like a version.
  - Inside a tag, the target is `milestone-for-tag`. After the last tag, the target is `next-release-milestone`.
  - When several PRs name the issue, the earliest release wins.
  - Only issues that are closed with `stateReason` `COMPLETED` (or null) are checked.
  - The step-5 flag: a closed issue whose `closedByPullRequestsReferences` lists only unmerged PRs, while a merged PR's body names it.
- Output always ends with a summary line: `release check: N issues checked, M mismatches, K flagged`. Each mismatch line gives the issue, PR, commit, tag (or "after <last tag>"), and the current and target milestone. `--json FILE` writes `{"repo":…, "closed_moves":[{issue,to}]}` for apply-plan.sh.
- Exit codes: 0 when it ran (with or without mismatches), 1 when a read failed, 2 for usage or wrong repo.

- [ ] **Step 1: Failing tests:**
  - the 2026-10-04 shape, with exactly these mismatches: 6 merged after the tag but in the closed release milestone go to next-release; 1 merged after the tag in a later themed milestone goes to next-release; 1 with no milestone goes to next-release; 1 merged inside the tag but in a later milestone goes to the tag's milestone;
  - the clean run line;
  - the wrong-repo refusal;
  - a failed fetch;
  - shallow-clone warning;
  - the step-5 flag;
  - an issue with two PRs, earliest wins;
  - `--json` output that `apply-plan.sh --plan` dry-runs clean;
  - not-planned issues are skipped.
- [ ] **Steps 2-5:** watch them fail, implement, watch them pass, run the mutation check.
- [ ] **Step 6:** SKILL.md step 0 says to run the script on every invocation, show its summary even when clean, and fold `closed_moves` into the plan before any theme work. Add the task-manifest entry.
- [ ] **Step 7: Commit.** `plan-milestones: step 0 release reconciliation (#204)`

### Task 4: Versions, CHANGELOGs, docs

- github-board 1.1.0 -> 1.2.0. Bump the skill versions that tests pin (move-card, plan-milestones, and promote-shipped if Task 1 migrated it). Write the CHANGELOG entries (plugin, skills, root `[Unreleased]`), counting every number from the diff. Run `catalogue.py`, then `check-docs.sh`, every CI job and preflight.
- [ ] **Commit.** `github-board 1.2.0: next-release milestone and release check (#204)`
