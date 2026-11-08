# Redesign stop rule

Read this when a round's findings trace back to the previous round's fix. It applies to every
loop in this skill that fixes and then looks again: a Phase 1 round, a Step 2.6 re-check and a
tiered-lane T5 re-check.

## The rule

When two rounds in a row each find a defect caused by the previous round's fix, in the same rule
or subsystem, stop patching that rule. Do not send a third, narrower patch.

The first finding, the one the first fix was for, does not count. The rule trips on the second round in a row whose defect the previous fix caused.

A defect is caused by the previous fix when its cited lines are in that fix's range (the round's
fix diff, or `REVIEWED_SHA..FIX_SHA` in Step 2.6 and T5), or when it is a new bypass or edge case
of the guard, parser or heuristic that the fix changed.

## What to do when it trips

1. Send no more fixes for that rule. Findings in other rules go on through the loop as usual.
2. Write the defect trend: one line per round, with the round, the finding id and the fix that
   caused it.
3. Propose a structural redesign, and say what it removes. Typical ones: an allowlist in place of
   a list of blocked cases, a different evidence source in place of a smarter parser, fewer cases
   for the rule to handle.
4. Ask the user (or the caller, such as `/ship`) once, with the trend and the proposal.
5. The run is not signed off. The final report's first line says
   `Not signed off: redesign needed (<rule>)`, followed by the trend.

An approved redesign is a design change. In the tiered lane, run T1's two reviewers once more on
the fix range, as T5's exception says, and re-check that fix range as usual.

## Why

The lesson came back in 9 retros across 5 projects between 2026-08-19 and 2026-10-24. Each time,
review loops sent a third or fourth narrower patch to a guard or heuristic after each fix had
opened a new hole next to the last one, and the round cap came before anyone asked for a
redesign. A word list grown one edge case at a time, or a guard that needs a second bypass fix,
is the usual shape.
