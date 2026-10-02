---
name: promote-shipped
description: "Moves GitHub Projects (v2) board items to Done after a release or hotfix merges to main. Use when: (1) a release branch finished via Git Flow and the GitHub Release is published, (2) a hotfix shipped to main + back-merged to develop, (3) /finalize-release just completed, (4) the project board has closed issues sitting in 'Dev Complete', 'In Review', 'Done in develop', etc. whose linked PRs merged, (5) 'release board promote' or /github-release-board-promote (the old name of this skill). Discovers all Projects V2 boards linked to the repo, asks the user which board when multiple, validates each candidate (closed issue + merged PR + status != Done), shows a dry-run preview, then applies updateProjectV2ItemFieldValue. No-op when the repo has no boards. Covers: GraphQL projectsV2 discovery, status-field auto-detect, closedByPullRequestsReferences."
metadata:
  version: 2.0.0
---

# GitHub Release Board Promote

## Problem

After a release or hotfix merges to main and the GitHub Release is published, the
items that just shipped are still parked in non-terminal columns on the project
board (`Dev Complete`, `In Review`, `Done in develop`, etc.). The signal that they
belong in Done — issue closed AND a linked PR is merged — is already on GitHub. The
skill reads it and promotes them in one pass.

## Quick Check

```bash
# 1. Discover boards for a repo (returns 0/1/N boards as JSON)
./scripts/discover-boards.sh <owner> <repo> --json

# 2. Inventory items + status field (use board ID from step 1)
./scripts/inventory-board.sh --board-id <PVT_xxx> > /tmp/release-board-inv.json

# 3. Filter to promotable candidates (closed issue + merged PR + status != Done)
./scripts/find-promotable.sh /tmp/release-board-inv.json > /tmp/release-board-cand.json

# 4. Preview, then apply
./scripts/apply-promotions.sh /tmp/release-board-cand.json --dry-run
./scripts/apply-promotions.sh /tmp/release-board-cand.json --apply
```

## Pre-flight

The skill requires `gh` CLI scopes `read:project` (read board state) and `project`
(mutate item field values). If they're missing, every script bails with a clear
message. Refresh once per machine:

```bash
gh auth refresh -s read:project,project
```

## Progress Tracking (MANDATORY)

Generate the task checklist before starting:

```bash
./scripts/task-manifest.sh full-run
```

| # | subject | activeForm |
|---|---------|------------|
| 1 | Discover project boards | Discovering project boards |
| 2 | Inventory selected board | Inventorying board |
| 3 | Find promotable candidates | Filtering promotable candidates |
| 4 | Preview changes | Previewing changes |
| 5 | Confirm and apply | Applying promotions |
| 6 | Summary report | Generating summary |

**Update rules:**
- Mark each task `in_progress` (TaskUpdate) immediately before starting it.
- Mark `completed` after success.
- If the user picks "no, don't apply" at the confirmation gate, mark task 5 `deleted`
  and skip task 6. Don't fake-complete task 5 — the work didn't happen.
- On any auth or API failure, keep the failing task `in_progress` and surface the
  error.

## Workflow

### Phase 1 — Discover boards

```bash
./scripts/discover-boards.sh <owner> <repo> --json > /tmp/release-board-list.json
COUNT=$(jq '.boards | length' /tmp/release-board-list.json)
```

- `COUNT == 0` → exit cleanly with "no boards linked to this repo, nothing to
  promote". Mark all remaining tasks `deleted`. This is a valid steady state.
- `COUNT == 1` → use that board. Skip board-selection prompt.
- `COUNT > 1` → call `AskUserQuestion` with one option per board (label = title,
  description = `#<number> · <url>`). The user picks.

### Phase 2 — Inventory

```bash
BOARD_ID=$(jq -r '.boards[<picked-index>].id' /tmp/release-board-list.json)
./scripts/inventory-board.sh --board-id "$BOARD_ID" > /tmp/release-board-inv.json
./scripts/inventory-board.sh --board-id "$BOARD_ID" --human   # also show summary
```

The script auto-detects the Status field (single-select with a `done|released|shipped`
option). If it can't find one, it bails with exit 5 — surface the error and stop.

### Phase 3 — Find promotable

```bash
./scripts/find-promotable.sh /tmp/release-board-inv.json --human
./scripts/find-promotable.sh /tmp/release-board-inv.json > /tmp/release-board-cand.json
```

Every candidate (status set, not already Done, closed Issue or merged PR) is assigned
exactly one `promoteClass`. Three promote, four hold:

| `promoteClass` | Condition | Comment posted |
|---|---|---|
| `merged` | ≥1 merged PR whose `mergeCommit.oid` is reachable from `main` | 🚀 Released in `<tag>` |
| `wontfix` | `stateReason=NOT_PLANNED`, no merged PR | no-merged-PR note |
| `nopr` | `COMPLETED`, **zero** linked PRs of any kind | no-merged-PR note |
| `hold-unreleased` | has a merged PR, none reachable from `main` | — |
| `hold-unmerged-pr` | `COMPLETED`, linked PRs exist but none merged | — |
| `hold-no-fallback` | `--no-fallback-discovery` passed, so no evidence to reason from | — |
| `hold-other` | non-Issue content with no merged PR | — |

`hold-unreleased` is the critical guard: a PR merged to develop only is *not* yet
released. The skill leaves those in "Dev Complete" until a release ships develop →
main. Use `--base BRANCH` to override the default branch, or `--skip-main-check` for
the looser legacy filter (rarely correct; it cannot reach the no-PR classes at all).

> **Squash-release repos: run BOTH passes and union the results.** When the release
> branch is *squash*-merged to `main`, the squash commit shares no ancestry with the
> PR merge commits on `develop`, so the reachability check reports `inMain=no` for
> work that genuinely shipped. `--skip-main-check` is then **required** to reach the
> `merged` class — but it **cannot reach `nopr`/`wontfix` at all**, so running it
> alone silently strands administrative and findings-only closures. Neither pass
> reports the gap: each succeeds on its own subset.
>
> ```bash
> ./scripts/find-promotable.sh inv.json > /tmp/cand-default.json                   # reaches nopr + wontfix
> ./scripts/find-promotable.sh inv.json --skip-main-check > /tmp/cand-merged.json  # reaches merged
> ```
>
> Apply both candidate sets, then check the arithmetic: the promoted total should
> drain the source column to zero, minus genuinely-held items (open epics, unmerged
> PRs). Observed on one release: 33 `merged` + 3 `nopr` = 36, exactly the column
> size. Running only `--skip-main-check` promoted the 33 and left three `nopr`
> issues sitting in the column — caught only because a human noticed one of them
> still on the board.
>
> **With the ancestry net off, verify the `merged` set yourself.** For each
> candidate, assert its merge commit is contained in the branch head that actually
> shipped:
>
> ```bash
> git merge-base --is-ancestor <mergeCommitOid> <released-develop-sha>
> ```
>
> That is the check the bypassed guard *should* have performed — run against the
> branch that really shipped, rather than against the squashed `main` where the
> ancestry no longer exists.

**Why `nopr` requires zero linked PRs, not zero merged ones.** An issue closed as
completed whose PR is still open is stalled work, and promoting it would hide that.
An issue with no linked PR whatsoever is a different animal: an administrative or
findings-only closure, where the deliverable was filed issues, a local action, or
supersession. `inventory-board.sh` fetches
`closedByPullRequestsReferences(includeClosedPrs: true)` precisely so the two can be
told apart without an extra API round-trip.

Order is load-bearing: `merged` is tested first and `hold-unreleased` before
`wontfix`, so an issue with a merged-but-unreleased PR is never promoted early no
matter what its `stateReason` says.

> **Git-Flow fallback (default ON).** When a closed issue has no formal merged-PR
> link (`closedByPullRequestsReferences` is empty — the normal case when its PR
> merged to `develop`, since GitHub only records the closing link on default-branch
> merges), `find-promotable.sh` discovers the closing PR from the issue timeline. A
> cross-referenced PR is accepted only if its body contains a closing keyword for
> that exact issue (`Closes/Fixes/Resolves #N`); connected/closer links are accepted
> directly. Every discovered PR still passes the same main-reachability guard, so the
> fallback can only add genuinely-shipped items — it never promotes unreleased work.
> Pass `--no-fallback-discovery` to restrict to formal links only.

If the candidate count is 0, exit cleanly — board is in sync with main.

### Phase 4 — Preview

```bash
./scripts/apply-promotions.sh /tmp/release-board-cand.json --dry-run
```

Always run dry-run first. The preview shows per-item: current → Done transition
AND the resolved release tag that will appear in the issue comment. If a candidate
has no release containing its merge commit (rare — usually means the user ran the
skill before the release shipped), the preview surfaces it as "(no release contains
<sha>)" so they can abort or wait.

### Phase 5 — Confirm and apply

Use `AskUserQuestion` with options:
1. **Apply all N promotions** (Recommended) — proceeds with `--apply`.
2. **Cancel** — bail out without writing.

The user can also type a custom answer ("apply but skip #X") — handle by mutating
the candidate JSON before calling `--apply`.

```bash
./scripts/apply-promotions.sh /tmp/release-board-cand.json --apply
```

For each candidate the apply phase performs two writes:
1. **Status mutation** — `updateProjectV2ItemFieldValue` to Done (primary).
2. **Release comment** — posts `🚀 Released in [v1.6.2](url) (published 2026-04-22).
   Moved to Done on the project board.` to the linked issue/PR (best-effort; a
   comment failure does NOT mark the promotion as failed — the board move is the
   primary side-effect).

The release lookup walks `gh api /repos/{owner}/{repo}/releases` oldest-first and
picks the **smallest** release whose tag contains the PR's merge commit. Per-repo
release listing and per-(repo,sha) result are cached for the run.

Override flags:
- `--release-tag <tag>` — skip auto-detect, use this tag for every comment.
  Useful when the auto-detect picks the wrong release (e.g. you ran the skill
  late and items were already in older releases).
- `--no-release-comment` — skip commenting entirely. Just do the board move.

### Phase 6 — Summary

Print: project title, items moved (count + #s), items skipped (count + reasons), and
a one-line "verify in browser" link to the board URL. Use the emoji-prefixed list
format the user prefers (per `feedback_list_over_table_status` memory) — never a
markdown table.

## Edge cases the scripts handle

- **No board on repo** — `discover-boards.sh` returns `{boards: []}`, skill no-ops.
- **No Status field on board** — `inventory-board.sh` exits 5 with a clear error.
- **No "Done"-like option** — same error path.
- **Item is a DraftIssue** — filtered out by `find-promotable.sh` (only Issue or PR).
- **Issue closed but no linked PR at all** — promoted, with an explanatory comment.
  `stateReason=NOT_PLANNED` → `wontfix`; `COMPLETED` with zero linked PRs → `nopr`.
  Before v1.4.0 these were filtered out, which parked them in a non-terminal column
  permanently: a wontfix can never acquire a merged PR, so the merge rule could
  never fire, and the card blocked its column from draining on every later release.
- **Issue closed as COMPLETED with linked PRs that haven't merged** — held back.
  This is the genuine stall, and it is why `nopr` requires *zero* linked PRs rather
  than merely zero *merged* ones.
- **PR merged to develop but not yet released to main** — filtered out by the
  Stage 2 ancestry check. The script reports them in the "Held back" section so
  you can see what's queued for the next release.
- **Hotfix merged directly to main** — its merge commit is trivially in main, so
  ancestry check passes; promoted on the next run.
- **Squashed merge commits** — GitHub's `compare` API works on the squashed merge
  commit's SHA (`pullRequest.mergeCommit.oid`), so squash, merge-commit, and
  rebase strategies all work the same.
- **Squash-merged *release branches* (double-squash Git Flow)** — different from the
  above, and not handled automatically. Squashing `release/* → main` produces a
  single commit that is not a descendant of the PR merge commits on `develop`, so
  every genuinely-shipped item classifies `hold-unreleased`. This is a false
  negative, not a real "not shipped". See the Phase 3 note on running both passes
  and unioning them.
- **Repo with non-`main` default branch** — pass `--base develop` (or whatever
  your release target is) to `find-promotable.sh`.

## Anti-patterns

- **Skipping the dry-run preview** — write mutations are reversible (re-run with the
  prior option ID), but a surprised user is worse than a 5-second preview.
- **Hardcoding a board number** — boards get archived, replaced, renumbered. Always
  discover first.
- **Promoting items where the linked PR isn't merged yet** — the filter prevents
  this. Don't relax it; an in-flight PR landing on a release is the symptom of a
  Git Flow violation, not a board-sync problem.
- **Running this before the release/hotfix is actually merged to main** — the issue
  is closed at PR-merge-to-develop time, but the skill's *trigger* is the release
  shipping. Calling it earlier promotes items that aren't yet in production.
- **Treating one filter pass as the complete set** — in a squash-release repo,
  `--skip-main-check` reaches only the `merged` class and the default pass reaches
  only `nopr`/`wontfix`. Each reports success on its own subset, so neither surfaces
  what the other missed. Union both, and reconcile the total against the source
  column's size before declaring the board drained.

## See Also

- `release-management` — the surrounding release/hotfix workflow. This skill is the
  optional last step after `/finalize-release`.
- `triage-issues` — different goal (audit + label open issues), but shares the
  closed-issue-with-merged-PR primitive.
- `references/projects-v2-graphql-snippets.md` — raw GraphQL queries for debugging
  outside the scripts.
