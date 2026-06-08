---
name: deep-review
description: "Use when the user wants a thorough, high-assurance review of code changes — phrases like \"review this until it's clean\", \"converge to zero issues\", \"adversarial review\", \"have Gemini and Claude review\", \"deep review this PR\", or \"make this change ironclad\". Runs TWO phases on a PR or working-tree diff: (1) iterative multi-reviewer review that loops fix->re-review until a round finds zero actionable issues, then (2) a multi-round Gemini-primary adversarial cross-examination (Gemini finds -> Claude judges -> Gemini counters), fixing every confirmed finding. Repeatable across any project/PR. Use when: (1) the user wants a thorough, high-assurance review that converges to zero actionable issues, (2) the user asks for an adversarial or Gemini-and-Claude cross-examination review of a code diff, (3) deep-reviewing a PR or working-tree diff before merge, (4) the user wants to make a change ironclad."
metadata:
  version: 1.0.0
---

# Deep Review

A two-phase convergence harness for high-assurance review of a changeset. Phase 1 drives
specialized reviewers in fix->re-review rounds until they stop finding actionable issues. Phase 2
runs an adversarial Claude<->Gemini cross-examination so only findings the *opposing* model confirms
survive. The output is a changeset that passed both a depth gauntlet and a cross-model gauntlet,
with every confirmed issue fixed and verified.

**Announce at start:** "Using deep-review to run iterative + adversarial review to convergence."

## When to use

- The user wants more than a single review pass — they want *convergence* ("until it's clean").
- High-stakes changes (security-sensitive, load-bearing guards, release candidates).
- The user explicitly asks for adversarial / multi-model / Gemini review.

Not for: a quick one-shot look (use `/pr-review-toolkit:review-pr` alone) or a trivial diff.

## Arguments

```
/deep-review                 # auto: PR diff if branch has an open PR, else working-tree vs base
/deep-review <PR#>           # target a specific PR
/deep-review local           # force working-tree-vs-base mode
/deep-review --phase1-only   # iterative review only (skip adversarial)
/deep-review --phase2-only   # adversarial only (skip iterative)
/deep-review --max-rounds N  # cap Phase-1 rounds (default 4)
```

## Prerequisites & composition

This skill ORCHESTRATES two existing capabilities; it does not reimplement them:

- **Phase 1** uses the `pr-review-toolkit` reviewer sub-agents
  (`pr-review-toolkit:code-reviewer`, `:pr-test-analyzer`, `:silent-failure-hunter`,
  `:type-design-analyzer`, `:comment-analyzer`). If that plugin is absent, fall back to the
  `feature-dev:code-reviewer` / `Explore` agents or a `general-purpose` reviewer with the same
  per-dimension prompts.
- **Phase 2** uses the `adversarial-review` skill's engine + agents
  (`adversarial-review:adversarial-bug-hunter`, `:adversarial-convention-reviewer`,
  `:adversarial-cross-examiner`, and `scripts/gemini-review.sh`). If that plugin is absent, run the
  pipeline manually per the steps below.

Discover whether they're installed before relying on them; degrade with a stated fallback, never
silently skip a phase.

---

## Phase 0 — Scope

1. Establish repo + change scope:
   - `git branch --show-current`; find an open PR for the branch (`gh pr list --head <branch>`).
   - Default base = the PR base, else the repo default branch (`develop`/`main`).
   - Build the diff: `git diff <base>...HEAD` (PR mode) or `git diff <base>` (local mode).
2. Enumerate changed files and classify (code / tests / docs / config). This drives which
   reviewers are applicable.
3. **Include out-of-tree artifacts that are part of the same change-set** if the user mentions
   them (e.g. live runtime config, instruction files not tracked in the repo). Reviewers should
   judge the *whole* change, not just what git shows.
4. Give every reviewer the **intent context** that isn't obvious from the diff (e.g. "this module
   is deliberately retired", "this file is the live regression guard"). Grounding context prevents
   wasted cycles re-flagging intentional decisions — but never use it to suppress a real defect.

---

## Phase 1 — Iterative review to convergence

Loop until a full round produces **zero actionable (Critical/Important) issues from every
dimension** AND the previous round's fixes introduced nothing new.

### Each round

1. **Dispatch applicable reviewers in parallel** (one message, multiple agents). Map dimensions to
   the changed files: always run general code review; add test-coverage if tests changed,
   silent-failure if error handling/guards changed, type-design if types added, comment/doc if
   docs/comments changed. Each reviewer gets: the diff command, the file list, repo read access,
   the intent context, and an instruction to **return findings grouped CRITICAL / IMPORTANT /
   SUGGESTION with file:line + concrete fix**, and to **say so plainly if clean — do not invent
   issues to seem thorough.**
2. **Aggregate.** Deduplicate convergent findings (multiple reviewers flagging the same thing ->
   higher confidence). Note which are factual vs judgment calls.
3. **Fix** all Critical/Important via a single **implementer sub-agent** given the exact,
   numbered fix spec (read-then-edit in its own context; this also sidesteps any parent-side
   router restrictions on Read/Edit). Address cheap Suggestions too when they reduce future review
   noise. The implementer must **verify empirically** — run the tests, and for any new guard/check,
   **prove it fails-first** (a planted-regression that would pass even when the code is broken is a
   silent defect; see Red Flags). Do not commit per-round by default — checkpoint at phase end to
   avoid preflight churn.
4. **Re-review (next round).** Re-query the same reviewers (continuing them via SendMessage
   preserves their codebase context) with TWO asks: (a) verify each prior finding is *actually*
   resolved against the new diff — not assumed; (b) check whether the fixes **introduced** any new
   bug, inconsistency, or regression. A reviewer replies either with new CRITICAL/IMPORTANT items
   or "CONVERGED — no actionable issues."
5. **Converge or iterate.** If all dimensions report CONVERGED -> Phase 1 done. Else apply the new
   fixes and run another round. Respect `--max-rounds` (default 4); if not converged at the cap,
   surface the remaining items to the user rather than looping forever.

### Phase 1 convergence is real only when

- Every dimension returned CONVERGED in the SAME round, and
- That round was a re-review *after* the latest fixes (so "converged" reflects the current tree),
  and
- Fixes were verified by running tests/build, not by inspection alone.

Commit Phase 1 with a clear message summarizing rounds + classes of issues fixed. Follow the
repo's commit discipline (run any preflight; if a hook requires preflight and commit as separate
calls, do so; respect changelog/branch rules).

---

## Phase 2 — Multi-round Gemini-primary adversarial review

Goal: cross-model confirmation. A finding only "survives" when the *opposing* model confirms it;
single-model findings are retained as UNCONFIRMED, never silently dropped.

### Step 2.0 — Ensure the adversary (Gemini)

Run the adversarial-review skill's `ensure-gemini.sh --check` (or check `command -v gemini` +
whether `~/.gemini/.env` has `GEMINI_API_KEY`). **Interactive Google login is NOT sufficient** —
headless calls need an API key.

- If Gemini is installed + headless-authed -> proceed.
- **If not -> PROMPT THE USER at runtime** (this skill's chosen policy): offer to (a) install/auth
  Gemini now (`npm i -g @google/gemini-cli`; add `GEMINI_API_KEY=<key>` to `~/.gemini/.env`), or
  (b) proceed Claude-only (self-cross-examination: a second independent Claude agent judges the
  first's findings) with a loud banner that cross-model confirmation was skipped. Do not decide
  silently.

### Step 2.1 — R1: blind parallel discovery

In one message, launch (none seeing the others):
- Claude bug-hunter (opus) — bugs/security/perf/correctness, grounded in source.
- Claude convention-reviewer (sonnet) — convention/maintainability/doc-drift.
- Gemini finder — `gemini-review.sh --diff <DIFF> --mode find` (or a direct
  `gemini -p ... -o json -m gemini-2.5-pro` with the same brief).

Give all the **byte-identical diff** (same-diff invariant). Merge Claude findings -> `C-001..`;
Gemini -> `G-001..`. Emit an R1 digest (counts by severity/category). An empty findings array is a
respectable, valid answer.

### Step 2.2 — R2: symmetric cross-examination

In one message:
- Claude cross-examiner (opus) judges every Gemini finding -> `confirm|refute` with reason,
  grounded in the **current** source (findings can be stale if Phase 1 already fixed them).
- Gemini judges every Claude finding (`gemini-review.sh --mode judge`).

Emit an R2 digest (confirmed/refuted/unjudged each direction).

### Step 2.3 — R3: counter-round (the "let the primary counter" round)

This is what makes it >=3 rounds and forces genuine convergence rather than a stalemate:
- For each finding the opponent **refuted**, send it back to the originator to **concede or
  defend**, grounded in source. Feed the refuter's reason and the relevant current file facts.
- **Settle factual disputes with direct evidence, not opinion.** If one model claims "X already
  exists / the catch is empty / the name has a space", run the actual `grep`/read and put the
  evidence in front of both. Evidence ends the dispute (in this skill's origin run, a `grep` of
  all check-name assignments settled a naming dispute and the primary conceded).
- A judgment-call disagreement (e.g. keep-vs-delete dead code) can be legitimately *defended* by
  either side on its real merits — if it stays split after evidence, escalate it to the user as an
  explicit decision rather than forcing a verdict.

### Step 2.4 — Converge (survivor rule)

| Finding origin | Survives when |
|---|---|
| Claude (C-NNN) | Gemini confirms (R2), or concedes its refutation (R3) |
| Gemini (G-NNN) | Claude confirms (R2), or concedes its refutation (R3) |

- **Survivors** — both models agree -> fix them.
- **Unconfirmed** — opponent abstained -> report, fix at discretion.
- **Rejected** — opponent refuted and originator conceded -> record with reason; do not fix.

If the adversarial-review skill is installed, `synthesize.py` applies this rule; otherwise apply it
by hand and print `survivors / unconfirmed / rejected` counts.

### Step 2.5 — Fix survivors + finalize

Fix all survivors via an implementer sub-agent (same verify-empirically discipline as Phase 1).
Then finalize:
- Re-run the full test/build suite; confirm green.
- **Sync any deployed/derived artifacts** the change affects (e.g. re-run an installer that copies
  a test suite to a runtime location; regenerate a generated doc/architecture page). A repo's own
  CLAUDE.md often mandates this in the same change-set.
- Commit Phase 2 with a message naming the survivors and noting what the adversarial pass
  dismissed (and why). Push; if the repo polls CI after push, check it.

---

## Final report

Summarize for the user:
- Phase 1: rounds run, count + classes of issues found and fixed, convergence confirmation.
- Phase 2: R1 counts, what survived cross-examination, what was dismissed and why, any unresolved
  judgment call escalated to them.
- Verification evidence (test results, exit codes), commits/SHAs, push + CI status.

## Red Flags — do not

- **Declare convergence without a re-review after the last fix.** "Converged" must reflect the
  current tree, in a round that ran *after* the fixes.
- **Trust a finding-resolved claim without checking the diff.** Re-review verifies against source,
  not memory. Likewise, a reviewer judging stale findings must read the *current* file.
- **Accept a planted-regression test that can pass vacuously.** Every new guard/check needs a
  fail-first negative: confirm the assertion FAILS when the code is broken. A test asserting on a
  static string that's always present is the classic vacuous trap.
- **Let the adversarial pass rubber-stamp.** The point is the *opposing* model. If running
  Claude-only, use a genuinely independent second agent and say cross-model confirmation was
  skipped.
- **Silently drop a single-model finding.** Retain as UNCONFIRMED.
- **Force a verdict on a genuine judgment call.** Escalate keep-vs-delete / design-taste splits to
  the user.
- **Fix in the parent context.** Dispatch an implementer sub-agent (clean context, no router
  friction); the parent orchestrates.
- **Skip syncing deployed artifacts** after changing a suite/config the runtime consumes.
- **Hand a fix to re-review without self-checking it.** A new guard needs its planted-regression in the *same* edit; retiring/disabling/renaming code needs a sweep of *every* descriptor string (manifest, README tagline, comments), not just the banner — don't let the next round be the first to catch your fix's new gap.

## Integration

- `pr-review-toolkit:review-pr` — the per-dimension reviewers Phase 1 drives.
- `adversarial-review:adversarial-review` — the Claude<->Gemini engine Phase 2 drives.
- Repo `CLAUDE.md` — commit/branch/preflight discipline and any "keep X in sync" mandates.
