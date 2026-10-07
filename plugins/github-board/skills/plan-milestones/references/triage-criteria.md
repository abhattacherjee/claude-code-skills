# Triage criteria and a worked example

## Contents
- [The criterion: theme, not priority](#the-criterion-theme-not-priority)
- [Writing a milestone theme](#writing-a-milestone-theme)
- [The four buckets](#the-four-buckets)
- [Effort check before "keep"](#effort-check-before-keep)
- [Worked example: an app's v3.6 → v3.7](#worked-example-an-apps-v36--v37)
- [gh mechanics that bite](#gh-mechanics-that-bite)

## The criterion: theme, not priority

A milestone with a stated theme makes membership **decidable**. Without one, "should this
be in v3.6?" has no answer beyond taste, and the milestone grows until someone declares
bankruptcy on it.

Priority labels do not decide membership. In the worked example below the highest-priority
open issue (P2-medium) was deferred and two P3-lows were kept, because the P3s matched the
theme and the P2 did not. Priority orders work *within* a milestone; theme decides *which*
milestone.

Corollary: if a milestone has no description, **stop and write one with the user** before
triaging. Judging membership against an unstated theme is how a triage pass turns into an
argument.

## Writing a milestone theme

A usable theme names a **failure mode or a class of change**, not a component or a quarter.

| Weak | Usable |
|---|---|
| "v3.6 — check-items improvements" | "silent wrong answers: a confident result that is wrong, with nothing surfacing the fault" |
| "Q3 bugs" | "gaps we left open on purpose: found, understood, and consciously deferred with a recorded reason" |
| "performance" | "operations that are correct but cost more than the user agreed to" |

Test it: read the theme, then read a candidate issue's title. If you cannot answer
yes/no in one breath, the theme is too vague to triage against.

The deferral target needs its own theme too. A milestone called "backlog" or "future"
is a dumping ground and will need this same exercise again in a month.

## The four buckets

For each open issue in the milestone under review:

| Bucket | Test | Action |
|---|---|---|
| **Keep** | Matches the theme AND is shippable within the milestone's horizon | Leave it |
| **Defer** | Real work, but a different failure class | Move to a themed milestone, comment why |
| **Backlog** | Real work, no coherent home yet | Move to a standing backlog milestone, comment why |
| **Close** | Already resolved, obsolete, or duplicate | Not this skill's job — use `triage-issues` |

Do the `triage-issues` pass **first** if the issue list has not been audited
recently. Re-milestoning an issue that is already resolved is wasted motion. A closed
issue belongs in the milestone of the release that shipped it; fix it with
`closed_moves`.

## Effort check before "keep"

"Keep" must mean *shippable*, not merely *on-theme*. Before keeping an issue, probe its
blast radius:

```bash
grep -rn "the_function_it_changes" hooks/ skills/ | grep -v "^tests/"   # production callers
grep -rc "the_function_it_changes" tests/*.py | grep -v ':0'            # test references
```

An issue that changes a function's return shape with 37 test references is on-theme and
still not a quick win. Keep it only if the milestone's horizon can absorb it; otherwise
say so explicitly and let the user decide. Surfacing the tension is the job — silently
keeping it is how a milestone slips.

## Worked example: an app's v3.6 → v3.7

**Situation.** v3.6 had 15 closed and 7 open. Every one of the 7 had been filed that same
day as a follow-up from two shipped issues. `milestone-report.sh` flagged all 7 as
`ACCRETION` — created after the newest closed issue — and printed the "original scope is
finished, now absorbing new work by default" warning.

**Theme.** v3.6: *"silent wrong answers — the system returns a confident result that is
wrong, with nothing surfacing the fault."*

**Judgement.**

| Issue | Priority | Verdict | Reason |
|---|---|---|---|
| #336 dead `except OSError` around `glob()` | P3-low | **keep** | Swallows the error, proceeds as if the dir were empty, **duplicates a session note**. Confident wrong result, nothing surfaces it. |
| #340 cascade-only flips render unchecked | P3-low | **keep** | Vault has the box checked, report shows it unchecked. The theme names "a wrong checkbox flipped" almost verbatim. |
| #339 restore evidence via per-verdict provenance | **P2-medium** | defer | Nothing silently wrong — something deliberately *absent*, and documented. Also the largest item. |
| #337 write-time drift hook | P2-medium | defer | Closest call. The failure is on-theme, but the detector already shipped, so the fault now surfaces. This is automation on a solved detection problem. |
| #341 Rule 0 exact-match miss | P4-trivial | defer | Fail-closed: a missed detection, never a wrong verdict. Degrades to prior behaviour. |
| #342 dead check + per-project re-walk | P3-low | defer | Dead code plus measured perf. Neither returns a wrong answer. |
| #343 preflight false positive | P3-low | defer | Fails **loudly**. The opposite of the theme, and tooling rather than product. |

**Outcome.** v3.6 went 7 open → 2. A new v3.7 was created with its own theme (*"gaps we
left open on purpose"*), and each moved issue got a comment explaining why it did not fit
v3.6 — not merely that it had moved.

**What the report caught that the milestone view hid:** 75 open issues with **no milestone
at all**, three of them P1-high. Run with `--unassigned`; a tidy milestone list means
nothing if the real queue is parked outside it.

## gh mechanics that bite

- `gh api repos/O/R/milestones` returns **open milestones only**. Closed ones are invisible
  without `?state=all`, which hides the numbering history you need to pick the next title.
- `gh issue edit N --milestone` takes the milestone **title**, not its number. Titles are
  case-sensitive and a typo creates nothing — it errors. It cannot assign a **closed**
  milestone. REST by number can: `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`
  (the number is in the `?state=all` list). `apply-plan.sh` writes every move this way.
- `gh issue list --milestone` also takes the title.
- Creating a milestone is `gh api repos/O/R/milestones -X POST -f title= -f description=`;
  there is no `gh milestone` subcommand.
- The milestone `description` field is where a theme lives. Nothing else in the GitHub UI
  carries it, and it is the field this whole skill depends on.
