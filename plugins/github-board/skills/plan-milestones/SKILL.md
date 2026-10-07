---
name: plan-milestones
description: "Re-organises open GitHub issues across milestones so each milestone stays small, themed, and shippable, deferring the rest to a themed backlog rather than letting one milestone absorb everything. Use when: (1) a milestone keeps growing and never ships, (2) new issues land in the open milestone by default, (3) open issues have no milestone at all, (4) planning what a release actually contains, (5) the user asks to re-arrange, re-scope, or focus milestones, (6) a roadmap pivots and leaves version-numbered milestones that never shipped, (7) 'milestone planning' or /github-milestone-planning (the old name of this skill). Covers: milestone themes, accretion detection, keep/defer/backlog triage, what to do with emptied and never-shipped milestones, gh milestone mechanics."
metadata:
  version: 2.1.0
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
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh"                      # themes, open issues, accretion flags
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh" --unassigned         # + open issues with NO milestone
"${CLAUDE_SKILL_DIR}/scripts/milestone-report.sh" --json               # machine-readable
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json           # dry-run (default)
"${CLAUDE_SKILL_DIR}/scripts/apply-plan.sh" --plan plan.json --apply   # write
"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" refocus                 # task checklist
```

Requires `gh` (authenticated) and `jq`.

## Progress Tracking (MANDATORY)

Build the checklist from `"${CLAUDE_SKILL_DIR}/scripts/task-manifest.sh" refocus` before starting. Mark each
task `in_progress` before it and `completed` after. On abort, mark the rest `deleted` —
never leave a triage looking finished when the moves were never applied.

| # | Task |
|---|---|
| 1 | Gather milestone + issue state |
| 2 | Establish the theme for each milestone |
| 3 | Judge each open issue against its milestone theme |
| 4 | Check effort on every keep candidate |
| 5 | Confirm the plan with the user |
| 6 | Apply and verify |

## Workflow

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

The script **refuses** a plan whose move lacks a real rationale (≥10 chars), and refuses
a target milestone that neither exists nor is being created — a typo'd title otherwise
fails silently per-issue. It also refuses a target title that two milestones share, and
an issue listed twice.

`closed_moves` fix the milestone of a **closed** issue, usually to the release that
shipped it. They need no rationale and post no comment. The target may be a closed
milestone: every write goes through REST by number, so it works where
`gh issue edit --milestone` cannot. A failed write prints gh's error, the rest of the
plan still runs, and the script exits 1.

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
