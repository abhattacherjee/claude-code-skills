---
name: plan-milestones
description: "Re-organises open GitHub issues across milestones so each milestone stays small, themed, and shippable, deferring the rest to a themed backlog rather than letting one milestone absorb everything. Use when: (1) a milestone keeps growing and never ships, (2) new issues land in the open milestone by default, (3) open issues have no milestone at all, (4) planning what a release actually contains, (5) the user asks to re-arrange, re-scope, or focus milestones, (6) a roadmap pivots and leaves version-numbered milestones that never shipped, (7) 'milestone planning' or /github-milestone-planning (the old name of this skill). Covers: milestone themes, accretion detection, keep/defer/backlog triage, what to do with emptied and never-shipped milestones, gh milestone mechanics."
metadata:
  version: 2.2.0
---

# GitHub Milestone Planning

## Problem

Milestones grow because new issues land in whichever one is open. The scoping cohort
ships, the milestone stays open, and everything filed afterwards accumulates in it — so
the release keeps slipping and nobody can say what it contains. The fix is not
prioritising harder; it is deciding membership against a **stated theme**, and moving
everything else somewhere with its own theme.

## Quick Check

```bash
"${CLAUDE_SKILL_DIR}/scripts/release-reconcile.sh" --repo O/R --json release-moves.json  # step 0
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh"                      # themes, open issues, accretion flags
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh" --unassigned         # + open issues with NO milestone
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh" --json               # machine-readable
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json           # dry-run (default)
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json --apply   # write
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" refocus                 # task checklist
```

Requires `gh` (authenticated) and `jq`. Step 0 also needs `git` and a checkout of the repo.

## Progress Tracking (MANDATORY)

Build the checklist from `"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" refocus` before starting. Mark each
task `in_progress` before it and `completed` after. On abort, mark the rest `deleted` —
never leave a triage looking finished when the moves were never applied.

| # | Task |
|---|---|
| 0 | Check closed issues against their releases |
| 1 | Gather milestone + issue state |
| 2 | Establish the theme for each milestone |
| 3 | Judge each open issue against its milestone theme |
| 4 | Check effort on every keep candidate |
| 5 | Confirm the plan with the user |
| 6 | Apply and verify |

## Workflow

### 0. Release check (every invocation)

Run this first, every time, from a full (not shallow) checkout of the repo:

```bash
"${CLAUDE_SKILL_DIR}/scripts/release-reconcile.sh" --repo O/R --json release-moves.json
```

It refuses (exit 2) when the checkout's `origin` is another repo, or a host other than
github.com (`$GH_HOST` when set), or when the clone is shallow (`shallow clone: run git
fetch --unshallow origin, then re-run`). Then it runs `git fetch --tags origin`. For each closed issue (done, not "not planned") that a merged PR
names with a closing keyword, it finds the first release tag containing the PR's merge
commit. Inside a tag, the issue belongs to that release's milestone (`vX.Y.Z`, else
`vX.Y`), even when that milestone is closed. After the last tag, it belongs to the
next-release milestone: `milestones.next_release["O/R"]` in the github-board config, else
the open milestone with the lowest version above the newest tag (a milestone at or below
it has shipped, even if it is still open). Tags are ordered by version, with the leading
`v` optional. When several merged PRs name an issue, the earliest release wins and the
line says so.

- **Show its summary line to the user even when it is clean:**
  `release check: N issues checked, M mismatches, K flagged`. "Checked" counts the issues
  whose milestone was compared. An issue that only a commit names is checked for `FLAG`
  only, and the line adds `, C named only by a commit`.
- **Fold its `closed_moves` into the plan before any theme work.** Each `MISMATCH` line
  gives the issue, PR, commit, tag (or "after <last tag>"), and the current and target
  milestone. `--json` writes `{"repo", "closed_moves"}`, which `apply-plan.sh` takes as is.
- **Raise every `FLAG` line.** It is a closed issue whose linked PRs never merged while a
  merged PR, or a commit on develop or the default branch, names it. The line names the
  branch. Check which PR really shipped the work.
- `NOTE` lines say why an issue was not checked or not moved: its tag has no milestone,
  two milestones match the tag, there is no next-release milestone (for example, every
  open version milestone is at or below the newest tag), or the number does not exist.
- A squashed `release/* -> main` merge breaks tag containment. A merge commit that no tag
  contains but that is older than the newest **release** tag (`vX.Y.0` or `vX.Y`) gets
  `NOTE #N: PR #P merged before <tag> but no tag contains it (squashed release?);
  milestone left as <current>`, and no move. Hotfix tags (`vX.Y.Z`, Z > 0) are ignored
  for this date test, so develop work merged before a hotfix still moves to the next
  release. With only hotfix tags, no date test applies.
- Exit 1 means the result is incomplete, and no JSON is written (an old `--json` file is
  deleted at the start of every run). It happens when git, gh or jq is missing, the fetch
  fails, a merged-PR list fails, is empty or hits the 1000-PR limit, a merged PR has no
  merge commit, the milestone list fails, an issue cannot be read, or a merge commit is
  not in the clone.

### 1. Gather

```bash
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh" --unassigned
```

Read two things from the output:

- **`THEME:`** — the milestone's description. `⚠ NONE SET` means stop; see step 2.
- **`[ACCRETION]`** — this issue was created after the newest *closed* issue in the
  milestone. When every open issue is flagged, the script says so explicitly: the
  original scope is finished and the milestone is now absorbing new work by default.
  That is the signal that a re-focus is overdue.

Always pass `--unassigned`. A tidy milestone list proves nothing if the real queue is
parked outside it — the first run of this script on its origin repo found 75 unassigned
open issues, three of them P1-high.

### 2. Establish the theme

A milestone with no description cannot be triaged, because membership has no criterion.
Write one with the user before judging anything. A usable theme names a **failure mode or
class of change**, not a component or a quarter — see
**[references/triage-criteria.md](references/triage-criteria.md)** for the weak-vs-usable
table and the one-breath test.

The deferral target needs its own theme too. "Backlog" and "future" are dumping grounds
that will need this exercise again shortly.

### 3. Judge — inline, not fanned out

Classify every open issue into **keep / defer / backlog / close**. Do this reasoning
**in your own context** over the report JSON. This is classification over structured data
against one shared criterion; splitting it across sub-agents costs consistency and buys
nothing, because each agent would judge in isolation against the same short theme.

The criterion is the theme. **Priority labels do not decide membership** — in the worked
example a P2-medium was deferred while two P3-lows were kept. Priority orders work
*within* a milestone; theme decides *which* milestone.

If the issue list has not been audited recently, run `triage-issues` **first**.
Re-milestoning an issue that is already resolved is wasted motion.

### 4. Check effort on the keeps

"Keep" must mean shippable, not merely on-theme. For each keep candidate, probe blast
radius before committing to it:

```bash
grep -rn "<function it changes>" <src dirs> | grep -v "^tests/"   # production callers
grep -rc "<function it changes>" tests/*.py | grep -v ':0'        # test references
```

An on-theme issue that changes a function's return shape across 37 test references is
still not a quick win. Surface the tension rather than silently keeping it — a milestone
slips one optimistic "keep" at a time.

### 5. Confirm

Present keep vs defer with a one-line rationale each, plus the deferral milestone's own
theme, and get explicit approval. This step writes to a shared tracker that other people
read; do not skip straight to applying.

### 6. Apply and verify

Write the plan, dry-run it, then apply:

```json
{
  "repo": "owner/repo",
  "create_milestones": [{"title": "v3.7", "description": "Theme: ..."}],
  "moves": [{"issue": 337, "to": "v3.7", "rationale": "Why it does not fit the source theme."}],
  "closed_moves": [{"issue": 181, "to": "v3.6"}],
  "keep": [{"issue": 336, "note": "optional, not written anywhere"}]
}
```

```bash
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json            # preview
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json --apply    # write
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh"                       # verify the resulting split
```

The script checks the whole plan before it writes anything, and exits 1 without a
write when any check fails. It **refuses**:

- a plan with the wrong shape: `moves`, `closed_moves`, `create_milestones` or `keep`
  that is not a list, or an entry that is not an object;
- a repo that is not `OWNER/REPO`, or has a `.` or `..` part;
- a move without a real rationale (≥10 chars);
- an issue that is not a positive integer, or a move with no target title;
- a `create_milestones` entry without a non-empty string title;
- an issue listed more than once across `moves` and `closed_moves`;
- a target milestone that neither exists nor is being created (a typo'd title is
  caught here, before any write);
- a target title that two milestones share. GitHub rejects duplicate titles (see
  step 7), so this guard is defensive: it refuses rather than pick one;
- a `closed_moves` issue that is open, or whose state cannot be read. Put an open
  issue in `moves`, with a rationale.

A `create_milestones` title that already exists is not created again; the dry run
says `EXISTS (<state>), will not create`.

`closed_moves` fix the milestone of a **closed** issue, usually to the release that
shipped it. They need no rationale and post no comment. The target may be a closed
milestone: unlike `gh issue edit --milestone`, REST by number can assign one. A write
counts as failed when gh fails (its error and the response body are printed) or when
the reply names another milestone. The rest of the plan still runs, and the script
exits 1 with `completed with N failure(s): #11 #12`.

### 7. After a pivot: reconcile the version sequence

Steps 1-6 assume the milestones themselves are sound and only their *membership* is
wrong. A **pivot** is different: the project changes direction, and a milestone is left
holding a version number for work that will never ship under it. Triage alone leaves a
misleading roadmap — empty milestones, and version numbers reserved for releases that
never happened.

Reconcile in this order.

**Move every straggler, then judge the milestone.** A milestone with one open issue left
in it is worse than an empty one: it reads as live work. Do not strand an issue to avoid
a separate decision about it — moving is not closing, and the no-closing rule (see Key
rules) does not justify leaving a lone occupant behind. Move it and flag it for triage in
the same comment.

**Distinguish shipped from never-shipped before touching any name.** Check what actually
closed under each milestone:

```bash
gh issue list --state closed --milestone "v0.3 — Observability" --limit 50 \
  --json number,title -q '.[] | "#\(.number) \(.title)"'
```

A milestone whose only closed issue is a test probe did not ship. One with real closed
issues did, and its number is now history — leave it alone.

**Free the numbers that never shipped.** A never-shipped `v0.3` blocks that number
forever and implies a release that never existed. Rename it to state the fact:

```bash
gh api repos/O/R/milestones/3 -X PATCH -f title="Superseded — Observability (never shipped)"
```

Then the next real milestone takes the next number after the last one that *did* ship, so
the sequence reads as a history of releases rather than of intentions.

**Give the deferral target no version number at all.** `Backlog — <theme> (paused)` is a
holding area, not a release; numbering it implies a slot in the sequence it does not have.

**Close emptied milestones, do not delete them.** Closing preserves the record and is
reversible if the direction resumes; deleting silently unassigns every issue that
referenced it.

Order matters: rename the old holder of a number *before* claiming it, because GitHub
rejects duplicate milestone titles even when one is closed.

## Key rules

- **The rationale comment is the deliverable, not decoration.** Six months later the
  assignment is visible and the reasoning is not, and "why isn't this in the release?"
  gets re-litigated from scratch. Explain why it does not fit the theme, not that it moved.
- **A milestone with no theme is not triageable.** Write the theme first.
- **Deferring is not rejecting.** Say so in the comment; a P2 moved out of a release still
  matters.
- **Never close an issue as part of this pass.** Closing is `triage-issues`'s job and
  a different decision with different evidence.
- **Check `--unassigned` every time.** The issues nobody milestoned are the ones nobody sees.
- **A version number is a claim that something shipped.** Never leave one on a milestone
  that delivered nothing — rename it `Superseded — … (never shipped)` and let the next
  real milestone take the number. Check what actually closed before deciding; do not
  infer it from the milestone's name.
- **Never strand a lone issue to dodge a decision.** One open issue in an otherwise-empty
  milestone reads as live work. Move it and flag it, rather than leaving it as the reason
  a dead milestone stays open.

## gh mechanics that bite

`gh api repos/O/R/milestones` returns **open milestones only** — closed ones need
`?state=all`. `gh issue edit --milestone` and `gh issue list --milestone` both take the
**title**, not the number, and titles are case-sensitive. `gh issue edit --milestone`
cannot assign a **closed** milestone; `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`
can, and `apply-plan.sh` writes that way. There is no `gh milestone`
subcommand; create via `gh api ... -X POST -f title= -f description=`. Full list in
**[references/triage-criteria.md](references/triage-criteria.md)**.

## See Also
- `triage-issues` — decides whether an issue is still *valid* (close, update, label).
  Complementary and runs first; this skill decides where a valid issue *belongs*.
- `promote-shipped` — moves board cards after a release ships.
- `ship` — drives a single issue end-to-end; assigns the open milestone on the way.
