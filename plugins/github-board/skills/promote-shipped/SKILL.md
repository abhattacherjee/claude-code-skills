---
name: promote-shipped
description: "Moves GitHub Projects (v2) board items to Done after a release or hotfix merges to main. Use when: (1) a release branch finished via Git Flow and the GitHub Release is published, (2) a hotfix shipped to main + back-merged to develop, (3) /finish just completed a release or hotfix, (4) the board has closed issues sitting in non-Done columns ('Dev Complete', 'In Review', 'Done in develop') whose linked PRs merged, (5) 'release board promote' or /github-release-board-promote (the old name of this skill). Previews before writing. No-op when the repo has no boards."
metadata:
  version: 2.1.0
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
"${CLAUDE_SKILL_DIR}/scripts/discover-boards.sh" <owner> <repo> --json

# 2. Inventory items + status field (use board ID from step 1)
"${CLAUDE_SKILL_DIR}/scripts/inventory-board.sh" --board-id <PVT_xxx> > /tmp/release-board-inv.json

# 3. Filter to promotable candidates (closed issue + merged PR + status != Done)
"${CLAUDE_SKILL_DIR}/scripts/find-promotable.sh" /tmp/release-board-inv.json > /tmp/release-board-cand.json

# 4. Preview, then apply
"${CLAUDE_SKILL_DIR}/scripts/apply-promotions.sh" /tmp/release-board-cand.json --dry-run
"${CLAUDE_SKILL_DIR}/scripts/apply-promotions.sh" /tmp/release-board-cand.json --apply
```

## Pre-flight

The skill needs two `gh` scopes: `read:project` to read board state, and `project`
to change it. They are checked at different points, and not every outcome stops the
run, so read the three cases below before reaching for a fix.

If you signed in with `gh auth login`, one command grants both:

```bash
gh auth refresh -s read:project,project
```

That command cannot change a personal access token's permissions. If you
authenticate with a PAT or `GH_TOKEN`, see the third case.

All three checks ask the same question of the same place: the ACTIVE account on
the host the run will query, via
`gh auth status --active --hostname "${GH_HOST:-github.com}"`. `gh` reports on
every host it knows and one host can hold several accounts, so a scope held
elsewhere does not count. The invocation is identical in all three scripts, and a
test enforces that — it drifted once, when only the write path was scoped.

- **`read:project`** is checked by `discover-boards.sh` and `inventory-board.sh`
  before they do anything. It covers Phases 1-4. Discovery, inventory, filtering
  and the dry-run preview only read. Reported-and-absent exits **3**.
- **`project` (write)** is checked by `apply-promotions.sh --apply`, before the
  first mutation rather than N failures into it. The check asks about the account
  and host that will actually be used: `gh auth status --active --hostname
  "${GH_HOST:-github.com}"`. `gh` reports every host it knows, and one host can
  hold several accounts, so a `project` scope held by another account or on another
  host does not count. If scopes are reported and `project` is absent, the run
  exits **3** and prints the fix for both an OAuth login and a PAT.
  **`--dry-run` is exempt.** It writes nothing, so you can preview the whole run
  with a read-only token, then grant the scope and apply.
- **Scopes that cannot be read at all** do not stop any of the three. A fine-grained PAT
  reports `none`, because it carries permissions rather than OAuth scopes. A bare
  `GH_TOKEN` often prints no scopes line. Both are frequently Projects-write
  capable, so the run **warns and continues** instead of blocking a token that
  probably works. If the token really cannot write, the first item fails and says
  so.

## Progress Tracking (MANDATORY)

Generate the task checklist before starting:

```bash
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" full-run
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
"${CLAUDE_SKILL_DIR}/scripts/discover-boards.sh" <owner> <repo> --json > /tmp/release-board-list.json
jq '.boards | length' /tmp/release-board-list.json
```

The second command prints the board count (`COUNT`). Each Bash call is a fresh shell, so
nothing below reads a shell variable set by an earlier command.

- `COUNT == 0` → exit cleanly with "no boards linked to this repo, nothing to
  promote". Mark all remaining tasks `deleted`. This is a valid steady state.
- `COUNT == 1` → use that board. Skip board-selection prompt.
- `COUNT > 1` → call `AskUserQuestion` with one option per board (label = title,
  description = `#<number> · <url>`). The user picks.

The board list is cached for 7 days (`--no-cache` skips it). A board linked to the repo while a
list is cached shows up only when the entry ages out, so pass `--no-cache` right after linking a
board. If Phase 2 exits 4 saying the board id did not resolve, `inventory-board.sh` has dropped
the cached list: re-run Phase 1 once.

### Phase 2 — Inventory

Take the picked board's `id` from `/tmp/release-board-list.json` (`.boards[<picked-index>].id`)
and write it literally in place of `<board-id>`:

```bash
"${CLAUDE_SKILL_DIR}/scripts/inventory-board.sh" --board-id <board-id> > /tmp/release-board-inv.json
"${CLAUDE_SKILL_DIR}/scripts/inventory-board.sh" --board-id <board-id> --human   # also show summary
```

The script auto-detects the Status field (single-select with a `done|released|shipped`
option). If it can't find one, it bails with exit 5 — surface the error and stop.

### Phase 3 — Find promotable

```bash
"${CLAUDE_SKILL_DIR}/scripts/find-promotable.sh" /tmp/release-board-inv.json --human
"${CLAUDE_SKILL_DIR}/scripts/find-promotable.sh" /tmp/release-board-inv.json > /tmp/release-board-cand.json
```

Every candidate (status set, not already Done, closed Issue or merged PR) is assigned
exactly one `promoteClass`. Three promote, six hold:

| `promoteClass` | Condition | Comment posted |
|---|---|---|
| `merged` | ≥1 merged PR whose `mergeCommit.oid` is reachable from `main` | 🚀 Released in `<tag>` |
| `wontfix` | `stateReason=NOT_PLANNED`, no merged PR | no-merged-PR note |
| `nopr` | closed, **not** `NOT_PLANNED`, **zero** linked PRs of any kind | no-merged-PR note |
| `hold-unreleased` | has a merged PR, none reachable from `main` | — |
| `hold-unmerged-pr` | `COMPLETED`, linked PRs exist but none merged | — |
| `hold-no-fallback` | `--no-fallback-discovery` passed, so no evidence to reason from | — |
| `hold-foreign-pr` | no merged PR in the issue's repo, but a PR from **another** repo, merged or not, claims the issue — its merge commit says nothing about this repo's releases | — |
| `hold-discovery-failed` | fallback discovery hit an API/auth/rate-limit error — the PR set could not be verified | — |
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
> "${CLAUDE_SKILL_DIR}/scripts/find-promotable.sh" inv.json > /tmp/cand-default.json                   # reaches nopr + wontfix
> "${CLAUDE_SKILL_DIR}/scripts/find-promotable.sh" inv.json --skip-main-check > /tmp/cand-merged.json  # reaches merged
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

**Why `nopr` does not claim "completed".** `stateReason` is nullable — GitHub
returns null for issues closed before the field existed. Requiring `COMPLETED`
would park every such legacy issue in a hold class that can never resolve, which is
the permanently-stuck card `wontfix` exists to prevent. The class promotes on what
is actually observed: closed, not `NOT_PLANNED`, no linked PRs. The comment it
posts says exactly that and no more.

**Why `nopr` requires zero linked PRs, not zero merged ones.** An issue closed
whose PR is still open is stalled work, and promoting it would hide that.
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
> that exact issue (`Closes/Fixes/Resolves #N`, or `owner/repo#N` naming the issue's
> own repo); connected/closer links are accepted directly. Only a PR in the **issue's
> own repo** is accepted: a PR from another repo is never credited, and when one claims
> the issue the card is held as `hold-foreign-pr`. Reachability and the release lookup
> always use the issue's repo. Every discovered PR still passes the same main-reachability guard, so the
> fallback can only add genuinely-shipped items — it never promotes unreleased work.
> Pass `--no-fallback-discovery` to restrict to formal links only.
>
> **The fallback fails closed.** If the timeline query errors (auth expiry, rate
> limit, missing scope, network), the PR set is *unknown*, not empty. Collapsing it
> to `[]` would hand the issue straight to `nopr` — the class that promotes on the
> evidence "zero linked PRs" — so a transient API failure would promote unreleased
> work and comment that it was an administrative closure. Such candidates are
> classified `hold-discovery-failed` and never promoted; the failure is printed to
> stderr. Re-run once the API is healthy.

If the candidate count is 0, exit cleanly — board is in sync with main.

### Phase 4 — Preview

```bash
"${CLAUDE_SKILL_DIR}/scripts/apply-promotions.sh" /tmp/release-board-cand.json --dry-run
```

Always run dry-run first. The preview shows per-item: current → Done transition
AND the resolved release tag that will appear in the issue comment. For a `merged`
item whose milestone is not the release milestone, it adds
`would set milestone: <current|none> -> <target> (<tag>)`. When the milestone is
left alone it says why in a `milestone: skipped — <reason>` line, and when it
cannot be checked in a `milestone: UNAVAILABLE — …` or `milestone: FAILED — …`
line. No milestone line at all means the milestone already matches, or the item is
`nopr`/`wontfix`.

The preview header names the **target column** (`Target column: <name> [<option id>]`), not just the
opaque option id — the resolver's last tier is a substring match on
`done|released|shipped`, and boards in this workflow legitimately contain columns
like "Done in develop". Check that line before approving.

Two preview lines look alike and mean opposite things — read them before deciding
to proceed:

- **`(no release contains <sha>)`** — the release list WAS read and checked, and
  nothing published contains that commit yet. Usually it means the skill ran before
  the release shipped. Wait for the release, then re-run; the answer will change.
- **`(release listing UNAVAILABLE for <repo> — see WARN above)`** — the release list
  could not be read at all (expired auth, rate limit, network), so nothing was
  checked and nothing is known about where this item shipped. Waiting will not help.
  Fix the `gh` auth or wait out the rate limit, then re-run — the answer is
  currently unknown, not negative. The stderr `WARN:` line above carries the actual
  API error.

Milestone lines, and the stderr `WARN:` each skip also prints once per repo and tag:

- **`skipped — no milestone titled X.Y.Z or X.Y for <tag>`**
  (`WARN: no milestone titled …`) — no milestone matches the release tag, so the milestone is left alone.
- **`skipped — ambiguous: <title> #<n>, <title> #<n> for <tag>`** (`WARN: ambiguous: …`)
  — two milestones match, for example `v4.0` and `4.0`. Rename one; the script never
  picks.
- **`skipped — tag '<tag>' is not vX.Y.Z or vX.Y`**
  (`WARN: release tag … is not vX.Y.Z or vX.Y`) — the tag has no version to map.
- **`skipped — no release contains <sha>`** — as for the comment above.
- **`UNAVAILABLE — …`** — the release or the milestone list could not be read.
- **`FAILED — malformed issue number or repo (…)`** — the candidate's number or repo
  cannot go into a REST path (not a positive integer, not `OWNER/REPO`, or a `.` or
  `..` part). Nothing is written.

To set a skipped milestone later (for example after creating `v4.0`), re-run
`apply-promotions.sh` against the SAME candidates file with
`--apply --no-release-comment`. A fresh Phase 3 run no longer lists items already in
Done, and a plain re-run posts the release comment a second time.

### Phase 5 — Confirm and apply

Use `AskUserQuestion` with options:
1. **Apply all N promotions** (Recommended) — proceeds with `--apply`.
2. **Cancel** — bail out without writing.

The user can also type a custom answer ("apply but skip #X") — handle by mutating
the candidate JSON before calling `--apply`.

```bash
"${CLAUDE_SKILL_DIR}/scripts/apply-promotions.sh" /tmp/release-board-cand.json --apply
```

For each candidate the apply phase performs up to three writes:
1. **Status mutation** — `updateProjectV2ItemFieldValue` to Done (primary).
2. **Release milestone** (`merged` items only) — when the item's milestone is not
   the release milestone, `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`.
   The release milestone is the one titled with the exact tag (`v3.18.1`), else its
   minor version (`v3.18`); the leading `v` is optional on both sides. Unlike
   `gh issue edit --milestone`, REST by number can assign a closed milestone, which
   the release milestone usually is. The reply must name the milestone number sent,
   or the write counts as failed; on an HTTP error the response body (a 422's
   `errors[]`) is printed. No match, or two matches, prints a skip line and a
   warning and changes nothing. `nopr` and `wontfix` items keep their milestone:
   they did not ship in a release. Best-effort, like the comment: a failure is
   reported and counted on the `Milestones:` summary line, and never undoes the
   board move. The summary is `Milestones: N set, N unchanged, N skipped, N failed`
   after `--apply` and `Milestones: N to set, N unchanged, N skipped, N cannot check`
   after `--dry-run`, and appears only when at least one item is `merged`.
3. **Release comment** — posts `🚀 Released in [v1.6.2](url) (published 2026-04-22).
   Moved to Done on the project board.` to the linked issue/PR (best-effort; a
   comment failure does NOT mark the promotion as failed — the board move is the
   primary side-effect).

The release lookup walks `gh api /repos/{owner}/{repo}/releases` oldest-first and
picks the **smallest** release whose tag contains the PR's merge commit. Per-repo
release listing and per-(repo,sha) result are cached for the run.

**When the release listing is unavailable** (the Phase 4 state above), the item is
still moved to Done and its comment is counted as a comment **FAILURE**, not a skip.
That distinction is deliberate: a "skipped — no release contains `<sha>`" line would
assert a check that never happened, and the run's summary would read as complete.
The board is correct either way — only the annotation is missing. To fill it in
later, re-run `apply-promotions.sh` against the SAME candidates file (the card is
now Done, so a fresh Phase 3 pass will no longer list it):

```bash
"${CLAUDE_SKILL_DIR}/scripts/apply-promotions.sh" /tmp/release-board-cand.json --apply
```

The status mutation is idempotent, so the re-run is safe — but note that items whose
release comment posted successfully the first time will get a second one. Only the
no-merged-PR note (`nopr`/`wontfix`) is marker-deduplicated; the 🚀 release comment
is not. If most items succeeded, comment on the few by hand instead.

Override flags:
- `--release-tag <tag>` — skip auto-detect, use this tag for every comment and
  every release milestone. Useful when the auto-detect picks the wrong release
  (e.g. you ran the skill late and items were already in older releases).
- `--no-release-comment` — skip commenting entirely. The board move and the release
  milestone still happen, so the release lookup still runs.

### Phase 6 — Summary

Print: project title, items moved (count + #s), items skipped (count + reasons), the
`Milestones:` line (set, unchanged, skipped, failed), and
a one-line "verify in browser" link to the board URL. Use the emoji-prefixed list
format the user prefers (per `feedback_list_over_table_status` memory) — never a
markdown table.

## Edge cases the scripts handle

- **No board on repo** — `discover-boards.sh` returns `{boards: []}`, skill no-ops.
- **No Status field on board** — `inventory-board.sh` exits 5 with a clear error.
- **No "Done"-like option** — same error path.
- **Item is a DraftIssue** — filtered out by `find-promotable.sh` (only Issue or PR).
- **Issue closed but no linked PR at all** — promoted, with an explanatory comment.
  `stateReason=NOT_PLANNED` → `wontfix`; anything else with zero linked PRs → `nopr`
  (including a null `stateReason`, which legacy issues carry).
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
- **Timeline discovery hits an API error** — classified `hold-discovery-failed`,
  reported on stderr, never promoted. An unverifiable PR set is not an empty one.

## Anti-patterns

- **Skipping the dry-run preview** — write mutations are reversible (re-run with the
  prior option ID), but a surprised user is worse than a 5-second preview. The
  milestone write replaces the item's old milestone, and only the preview shows
  what that old value was.
- **Hardcoding a board number** — boards get archived, replaced, renumbered. Always
  discover first.
- **Promoting items where the linked PR isn't merged yet** — the filter prevents
  this. Don't relax it; an in-flight PR landing on a release is the symptom of a
  Git Flow violation, not a board-sync problem.
- **Running this before the release/hotfix is actually merged to main** — the issue
  is closed at PR-merge-to-develop time, but the skill's *trigger* is the release
  shipping (`/finish` done, Release published). Calling it earlier promotes items
  that aren't yet in production.
- **Treating one filter pass as the complete set** — in a squash-release repo,
  `--skip-main-check` reaches only the `merged` class and the default pass reaches
  only `nopr`/`wontfix`. Each reports success on its own subset, so neither surfaces
  what the other missed. Union both, and reconcile the total against the source
  column's size before declaring the board drained.

## See Also

- `git-flow` plugin (`/release`, `/hotfix`, `/finish`) — the surrounding
  release/hotfix workflow. This skill is the optional last step after `/finish`
  completes a release or hotfix and the GitHub Release is published.
- `triage-issues` — different goal (audit + label open issues), but shares the
  closed-issue-with-merged-PR primitive.
- `references/projects-v2-graphql-snippets.md` — raw GraphQL queries for debugging
  outside the scripts.
