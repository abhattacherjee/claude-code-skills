---
name: deep-review
description: "Use when the user wants a thorough, high-assurance review of code changes — phrases like \"review this until it's clean\", \"converge to zero issues\", \"adversarial review\", \"have Codex or Gemini and Claude review\", \"deep review this PR\", or \"make this change ironclad\". Runs TWO phases on a PR or working-tree diff: (1) iterative multi-reviewer review that loops fix->re-review until a round finds zero actionable issues, then (2) a multi-round adversarial cross-examination with Codex, else Gemini, as the opposing model (it finds -> Claude judges -> it counters), fixing every confirmed finding. Repeatable across any project/PR. Use when: (1) the user wants a thorough, high-assurance review that converges to zero actionable issues, (2) the user asks for an adversarial or Gemini-and-Claude cross-examination review of a code diff, (3) deep-reviewing a PR or working-tree diff before merge, (4) the user wants to make a change ironclad."
metadata:
  version: 1.4.0
---

# Deep Review

> **Path convention:** `./references/…` below is relative to this skill's own base directory —
> announced as "Base directory for this skill" when the skill is invoked. A Bash tool call's working
> directory is the user's project, not the skill directory, so prefix these with that base directory
> when reading them. Paths written without the leading `./` refer to the **target project** being
> reviewed, or — where the text names the owning plugin, as with `adversarial-review`'s
> `scripts/gemini-review.sh` — to that plugin's own directory, not to this skill.

A two-phase convergence harness for high-assurance review of a changeset. Phase 1 drives
specialized reviewers in fix->re-review rounds until they stop finding actionable issues. Phase 2
runs an adversarial cross-examination between Claude and an opposing model (Codex, else Gemini) so
only findings the *opposing* model confirms survive. The output is a changeset that passed both a
depth gauntlet and a cross-model gauntlet, with every confirmed issue fixed and verified.

**Announce at start:** "Using deep-review to run iterative + adversarial review to convergence."

## When to use

- The user wants more than a single review pass — they want *convergence* ("until it's clean").
- High-stakes changes (security-sensitive, load-bearing guards, release candidates).
- The user explicitly asks for adversarial / multi-model / Codex / Gemini review.

Not for: a quick one-shot look (use `/pr-review-toolkit:review-pr` alone) or a trivial diff.

## Arguments

```
/deep-review                 # auto: PR diff if branch has an open PR, else working-tree vs base
/deep-review <PR#>           # target a specific PR
/deep-review local           # force working-tree-vs-base mode
/deep-review --phase1-only   # iterative review only (skip adversarial)
/deep-review --phase2-only   # adversarial only (skip iterative)
/deep-review --max-rounds N  # cap Phase-1 rounds (default 4)
/deep-review --no-post       # keep the audit trail local; post nothing to the PR
/deep-review --adversary codex|gemini  # force the Phase 2 adversary; stops if it is not usable
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
  `:adversarial-cross-examiner`, and its `scripts/pick-adversary.sh`, `scripts/codex-review.sh`,
  `scripts/gemini-review.sh` and `scripts/pr-audit.py`). If that plugin is absent, run the pipeline
  manually per the steps below.

Discover whether they're installed before relying on them; degrade with a stated fallback, never
silently skip a phase.

---

## Phase 0 — Scope

1. Establish repo + change scope:
   - `git branch --show-current`; find an open PR for the branch (`gh pr list --head <branch>`).
   - Default base = the PR base, else the repo default branch (`develop`/`main`).
   - Build the diff: `git diff <base>...HEAD` (PR mode) or `git diff <base>` (local mode). Exclude generated/derived artifacts (e.g. rendered `*.html`, lockfiles, build output) from the diff handed to reviewers — review their source instead, as a single-line source change can inflate the diff with hundreds of KB of generated output and waste reviewer budget.
2. Enumerate changed files and classify (code / tests / docs / config). This drives which
   reviewers are applicable.
3. **Include out-of-tree artifacts that are part of the same change-set** if the user mentions
   them (e.g. live runtime config, instruction files not tracked in the repo). Reviewers should
   judge the *whole* change, not just what git shows.
4. Give every reviewer the **intent context** that isn't obvious from the diff (e.g. "this module
   is deliberately retired", "this file is the live regression guard"). Grounding context prevents
   wasted cycles re-flagging intentional decisions — but never use it to suppress a real defect.
5. Record any **environment or toolchain coverage gaps** relevant to the diff. If a portability
   concern depends on a toolchain the review host cannot execute (for example GNU `tar` or `gawk`
   behaviour from a macOS/BSD environment), label it explicitly as **not executed locally** and
   **deferred to CI** — after confirming a CI job actually covers that environment
   (`ls .github/workflows`, check the job's `runs-on`). If none does, label it **UNCOVERED**, not
   deferred. Recommend a concrete cross-platform check when feasible (`gtar`, `gawk`, or a
   Linux container), and never treat the local suite as covering the unavailable environment.
6. **Start the audit trail.** Set up `RUN_ID`, `RUN_DIR`, `AUDIT` and the round counter as in
   `./references/audit-trail.md`. Every round below ends by writing and posting one record, so the
   PR shows each iteration: findings as threads, verdicts, counters, fixes and re-checks as replies.

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
   avoid preflight churn. Before advancing to the re-review, verify the implementer's claims against ground truth in *your own* context per `./references/delegated-verification.md` — a sub-agent can report "done" without writing, or "committed" with only a subset of files. A failed verification is a failure, not a silent retry.
4. **Re-review (next round).** Re-query the same reviewers (continuing them via SendMessage
   preserves their codebase context) with TWO asks: (a) verify each prior finding is *actually*
   resolved against the new diff — not assumed; (b) check whether the fixes **introduced** any new
   bug, inconsistency, or regression. A reviewer replies either with new CRITICAL/IMPORTANT items
   or "CONVERGED — no actionable issues."
5. **Converge or iterate.** If all dimensions report CONVERGED -> Phase 1 done. Else apply the new
   fixes and run another round. Respect `--max-rounds` (default 4); if not converged at the cap,
   surface the remaining items to the user rather than looping forever.
6. **Record the round** per `./references/audit-trail.md` (phase `phase1`): this round's findings
   with their `resolution` events, and `recheck` events for last round's fixes.

### Phase 1 convergence is real only when

- Every dimension returned CONVERGED in the SAME round, and
- That round was a re-review *after* the latest fixes (so "converged" reflects the current tree),
  and
- Fixes were verified by running tests/build, not by inspection alone — except concerns explicitly
  recorded under Phase 0 step 5 as not executable locally, **recorded during Phase 0, before any fix
  round** (a concern added to that list after a fix cannot retroactively excuse it), which converge
  as *deferred to CI* (or *UNCOVERED*) rather than as verified.

Commit Phase 1 with a clear message summarizing rounds + classes of issues fixed. Follow the
repo's commit discipline (run any preflight; if a hook requires preflight and commit as separate
calls, do so; respect changelog/branch rules).

---

## Phase 2 — Multi-round adversarial review

Goal: cross-model confirmation. A finding only "survives" when the *opposing* model confirms it;
single-model findings are retained as UNCONFIRMED, never silently dropped. The opposing model, the
adversary, is Codex, else Gemini, else a second independent Claude agent.

### Step 2.0 — Pick the adversary

`AR_SCRIPTS` is the adversarial-review plugin's `skills/adversarial-review/scripts` directory.

```bash
unset ADVERSARY
PICK="$("$AR_SCRIPTS/pick-adversary.sh" ${ADVERSARY_FLAG:+--adversary "$ADVERSARY_FLAG"})"
PICK_RC=$?
eval "$PICK"
```

`eval "$(cmd)"` alone returns eval's own status, not the command's — so the exit code must be
captured from `$PICK` before `eval` runs, or the "Exit 3" branch below can never be seen and
`$ADVERSARY` stays unset. `ADVERSARY_FLAG` is the value of `--adversary` when the user passed it.
Tell the user `ADVERSARY_REASON` in one line.

- `ADVERSARY=codex`: `ADV_REVIEW="$AR_SCRIPTS/codex-review.sh"`. Codex ids are `X-001…`.
- `ADVERSARY=gemini`: `ADV_REVIEW="$AR_SCRIPTS/gemini-review.sh"`. Renumber its ids `G-001…`.
  **Interactive Google login is NOT sufficient** — headless calls need an API key.
- `ADVERSARY=claude-only`: **PROMPT THE USER at runtime** (this skill's chosen policy): offer to
  (a) set up Codex (install it, then `codex login`) or Gemini (`npm i -g @google/gemini-cli`; add
  `GEMINI_API_KEY=<key>` to `~/.gemini/.env`), then run `pick-adversary.sh` again, or (b) proceed
  Claude-only (self-cross-examination: a second independent Claude agent judges the first's
  findings) with a loud banner that cross-model confirmation was skipped. Do not decide silently.
- `PICK_RC` is 3: the user forced an adversary that is not usable. Show the `ADVERSARY_UNAVAILABLE`
  line and stop. Do not fall back.

Never call `codex` directly. `codex-review.sh` is what keeps your config, hooks and ChatGPT
connectors out of the run (adversarial-review's SKILL.md, "Codex sandbox", says what it does and
does not stop).

### Step 2.1 — R1: blind parallel discovery

In one message, launch (none seeing the others):
- Claude bug-hunter (opus) — bugs/security/perf/correctness, grounded in source.
- Claude convention-reviewer (sonnet) — convention/maintainability/doc-drift.
- Adversary finder — `$ADV_REVIEW --diff <DIFF> --mode find --out "$RUN_DIR/r1-$ADVERSARY.json"`.
  It emits `{"findings":[...]}` with `origin` set to the adversary. Exit 3 means the adversary is
  unavailable: if Codex was picked automatically and `GEMINI_AUTHED=yes`, switch to Gemini for the
  whole phase and rerun this step; otherwise follow Step 2.0's Claude-only path.

Give all the **byte-identical diff** (same-diff invariant). Merge Claude findings -> `C-001..`.
Emit an R1 digest (counts by severity/category). An empty findings array is a respectable, valid
answer. Record the round (phase `phase2-r1`).

### Step 2.2 — R2: symmetric cross-examination

In one message:
- Claude cross-examiner (opus) judges every adversary finding -> `confirm|refute` with reason,
  grounded in the **current** source (findings can be stale if Phase 1 already fixed them).
- The adversary judges every Claude finding:
  `$ADV_REVIEW --diff <DIFF> --findings <claude-r1.json> --mode judge --out "$RUN_DIR/r2-$ADVERSARY-verdicts.json"`.
  Both scripts write the verdict under the key `adversary_verdict`, whichever model gave it.
  - **Gemini reliability note:** `gemini-review.sh` can come back empty when Gemini's JSON lacks
    `verdicts` (observed: `ADVERSARY_UNAVAILABLE: ... missing verdicts key`). Only then, fall back
    to a direct `gemini -m gemini-2.5-pro -p "<brief + each Claude finding, ask for JSON {id,
    verdict:confirm|refute, reason}>"` call. Build a prompt file with the brief and each finding,
    and parse the JSON yourself. Codex has no such fallback: exit 3 from `codex-review.sh` means
    Codex's verdicts are missing. Write `{"verdicts":[]}` to `$RUN_DIR/r2-$ADVERSARY-verdicts.json`
    (`synthesize.py` exits 1 on a missing file), and say in the R2 digest that Codex's verdicts
    are missing. Those Claude findings stay unconfirmed.

Emit an R2 digest (confirmed/refuted/unjudged each direction). Record the round (phase
`phase2-r2`): record each judged finding with its `verdict` event; confirmed findings take
`status: survivor`, refuted ones stay `status: unconfirmed` until the R3 record (see
./references/audit-trail.md).

### Step 2.3 — R3: counter-round (the "let the primary counter" round)

This is what makes it >=3 rounds and forces genuine convergence rather than a stalemate:
- For each finding the opponent **refuted**, send it back to the originator to **concede or
  defend**, grounded in source. Feed the refuter's reason and the relevant current file facts.
  - With Codex as the originator, use the script:
    `$AR_SCRIPTS/codex-review.sh --diff <DIFF> --mode counter --findings <refuted-X.json> --out "$RUN_DIR/r3-codex-counters.json"`.
    Each finding in `<refuted-X.json>` carries Claude's refutation in `kill_reason`. It returns
    `{"counters":[{"id","position":"concede|defend","reason"}]}`.
  - For Claude findings that Codex refuted, write Claude's defence into each finding's `rationale`
    and ask Codex again with `--mode judge`.
- **Settle factual disputes with direct evidence, not opinion.** If one model claims "X already
  exists / the catch is empty / the name has a space", run the actual `grep`/read and put the
  evidence in front of both. Evidence ends the dispute (in this skill's origin run, a `grep` of
  all check-name assignments settled a naming dispute and the primary conceded).
- A judgment-call disagreement (e.g. keep-vs-delete dead code) can be legitimately *defended* by
  either side on its real merits — if it stays split after evidence, escalate it to the user as an
  explicit decision rather than forcing a verdict.

Record the round (phase `phase2-r3`). For contested findings, record `counter` then `verdict`:
`survivor` if the refuter backed down, `rejected` if the origin gave up. Every other R2-refuted
finding gets `rejected`.

### Step 2.4 — Converge (survivor rule)

| Finding origin | Survives when |
|---|---|
| Claude (C-NNN) | The adversary confirms (R2), or concedes its refutation (R3) |
| Adversary (X-NNN Codex, G-NNN Gemini) | Claude confirms (R2), or concedes its refutation (R3) |

- **Survivors** — both models agree -> fix them.
- **Unconfirmed** — opponent abstained -> report, fix at discretion.
- **Rejected** — opponent refuted and originator conceded -> record with reason; do not fix.

If the adversarial-review skill is installed, `synthesize.py --adversary "$ADVERSARY"` applies this
rule; otherwise apply it by hand and print `survivors / unconfirmed / rejected` counts.

### Step 2.5 — Fix survivors + finalize

Fix all survivors via an implementer sub-agent (same verify-empirically discipline as Phase 1).
Before finalizing, verify the implementer's fixes against ground truth in *your own* context per `./references/delegated-verification.md` — never trust the sub-agent's narration that the survivors were fixed.
Then finalize:
- Re-run the full test/build suite; confirm green.
- **Sync any deployed/derived artifacts** the change affects (e.g. re-run an installer that copies
  a test suite to a runtime location; regenerate a generated doc/architecture page). A repo's own
  CLAUDE.md often mandates this in the same change-set.
- Commit Phase 2 with a message naming the survivors and noting what the adversarial pass
  dismissed (and why). Push; if the repo polls CI after push, check it. Then record the round
  (phase `phase2-fix`): a `resolution` event with the pushed commit's `sha` for each survivor.

### Step 2.6 — Adversary re-check rounds (Codex only)

With `ADVERSARY=codex`, Codex checks each fix itself, so fixed Phase 2 threads can close. Right
after writing the `phase2-fix` record, set:

```bash
FIX_K="$K"                  # the phase2-fix record's own round number
FIX_SHA="<its head_sha>"    # the commit that record's resolution events point to
REVIEWED_SHA="<the head the Phase 2 R1 diff was taken from>"
RECHECK_ROUND=0             # re-check rounds run so far, capped at 3 (see step 4)
```

1. `git diff "$REVIEWED_SHA".."$FIX_SHA" > "$RUN_DIR/fix-range-$FIX_K.diff"` — only the changes
   made since the reviewed head.
2. `K=$((K+1))`, then
   `$AR_SCRIPTS/codex-review.sh --diff "$RUN_DIR/fix-range-$FIX_K.diff" --mode find --prior "$RUN_DIR/round-$FIX_K.json" --id-start <highest X number so far + 1> --out "$RUN_DIR/recheck-$K.json"`.
   The prior record holds each fixed finding and the author's reply, so Codex sees both. `--id-start`
   must be above every finding id used anywhere in this run so far — Codex's and Claude's alike —
   so a new finding never reuses a dropped finding's id. Never reuse a `--round` value, here or
   anywhere else in the run; `K` only ever increases.
   - **Exit 3** here means Codex became unavailable partway through the re-check loop (auth
     expiry, quota, a tripped isolation canary) — not at Step 2.0, where it was picked.
     Stop the re-check loop at once: do not retry, and do not fall back to Gemini or Claude-only,
     because a different model cannot close a Codex thread (only `codex`'s own re-check does, per
     ./references/audit-trail.md). Leave every remaining re-check thread open, post the round
     summary you already have noting Codex became unavailable, and surface it to the user — the
     same outcome as the Gemini/Claude-only path below, reached mid-loop instead of at Step 2.0.
   - **Exit 1** means `codex-review.sh` could not use its inputs (for example a missing
     `--prior` or `--diff` file) or could not write `--out`. Stop the re-check loop the same way
     as exit 3: do not retry with guessed flags, and leave the remaining threads open. Note it,
     with the exact stderr message, in the round summary you post, and tell the user.
3. `python3 "$AUDIT" recheck --prior "$RUN_DIR/round-$FIX_K.json" --rechecks "$RUN_DIR/recheck-$K.json" --round "$K" --head-sha "$FIX_SHA" --out "$RUN_DIR/round-$K.json"`,
   then post it as in ./references/audit-trail.md. A `resolved` re-check closes its thread.
   - **Exit 2** means the re-check inputs don't make a valid record (see
     ./references/audit-trail.md for the causes). Stop, report the exact stderr message to the
     user, and leave the remaining threads open — do not retry with guessed flags.
4. `partly` or `missed`: set `REVIEWED_SHA="$FIX_SHA"`, then fix again (Step 2.5) — this keeps the
   next fix range to only what changed since *this* re-check, not every earlier fix stacked
   together. Step 2.5 writes a new `phase2-fix` record; set `FIX_K` to its round and `FIX_SHA` to
   its `head_sha`, then repeat from 1. New findings in the re-check record: judge them with the
   cross-examiner (Step 2.2), fix the survivors (Step 2.5) the same way, and repeat from 1.
   `RECHECK_ROUND=$((RECHECK_ROUND+1))` each time through — once per full loop back to step 1
   (whether that loop was triggered by `partly`/`missed` or by new findings), right before checking
   the cap below. Stop when a re-check round has every finding `resolved` and no new survivors, or
   once `RECHECK_ROUND` reaches 3 — a fixed cap on re-check rounds, separate from Phase 1's
   `--max-rounds`; surface whatever is left to the user.

With Gemini or Claude-only there is no re-check round, and fixed Phase 2 threads stay open for a
person to resolve.

---

## Final report

Summarize for the user:
- Phase 1: rounds run, count + classes of issues found and fixed, convergence confirmation.
- Phase 2: R1 counts, what survived cross-examination, what was dismissed and why, any unresolved
  judgment call escalated to them.
- Verification evidence (test results, exit codes), commits/SHAs, push + CI status.
- Portability concerns that were not executable locally: for each, either the exact CI/toolchain
  coverage it was deferred to, or an explicit **UNCOVERED** marker when no CI job covers that
  environment — plus any concrete command recommended for pre-CI reproduction.
- Audit trail: the PR link (or local file), rounds posted, and any posting failures with the
  command to rerun them; the run directory path holding every `round-<k>.json`.

## Red Flags — do not

- **Declare convergence without a re-review after the last fix.** "Converged" must reflect the
  current tree, in a round that ran *after* the fixes.
- **Trust a finding-resolved claim without checking the diff.** Re-review verifies against source,
  not memory. Likewise, a reviewer judging stale findings must read the *current* file.
- **Accept a planted-regression test that can pass vacuously.** Every new guard/check needs a
  fail-first negative: confirm the assertion FAILS when the code is broken. A test asserting on a
  static string that's always present is the classic vacuous trap.
- **Accept a negative control that re-implements the assertion instead of invoking it.** A control
  built from the guard's own logic tests the copy, not the guard: gut the real assertion and the
  control still passes. Measured on openclaw #336 — a doc-contract test added specifically to
  prevent vacuous assertions had three controls of this shape, and three mutations each gutting a
  real assertion all SURVIVED at `5 passed`. The control must call the same function the suite
  calls, or parametrize over the same table it does.
- **Accept an "expect nothing" assertion with no positive control.** An absent-pattern fixture
  catches a guard stuck ON; only a present-pattern fixture catches one stuck OFF, where "correctly
  reports nothing" and "hardcoded empty" produce the same green. (Downstream side effects can
  sometimes tell them apart — assert on what the code was supposed to *write*, not only on what it
  reported.) Require both directions for any detector or guard, and prefer proving it by mutation —
  patch the guard to `false &&`, confirm the suite goes red — over inspection. **Fixture
  reachability is a third axis, independent of both:** a fixture that cannot reach the failing half
  yields a green assertion over an uncovered path, so check that each assertion's fixture can
  actually express the failure, not merely that the assertion exists.
- **Let the adversarial pass rubber-stamp.** The point is the *opposing* model. If running
  Claude-only, use a genuinely independent second agent and say cross-model confirmation was
  skipped.
- **Call `codex` directly.** Every Codex call goes through adversarial-review's
  `codex-review.sh`. A direct call runs with your config, hooks and ChatGPT connectors, outside
  the lockdown.
- **Silently drop a single-model finding.** Retain as UNCONFIRMED.
- **Force a verdict on a genuine judgment call.** Escalate keep-vs-delete / design-taste splits to
  the user.
- **Fix in the parent context.** Dispatch an implementer sub-agent (clean context, no router
  friction); the parent orchestrates.
- **Skip syncing deployed artifacts** after changing a suite/config the runtime consumes.
- **Imply portability coverage from an unavailable toolchain.** A green BSD/macOS run does not
  verify GNU/Linux behaviour (or vice versa). State what was not executed, defer that concern to the
  matching CI job **(or mark it UNCOVERED when no such job exists)**, and recommend a concrete
  alternate-toolchain check where possible.
- **Hand a fix to re-review without self-checking it.** A new guard needs its planted-regression in the *same* edit; retiring/disabling/renaming code needs a sweep of *every* descriptor string (manifest, README tagline, comments), not just the banner — don't let the next round be the first to catch your fix's new gap.

## Integration

- `pr-review-toolkit:review-pr` — the per-dimension reviewers Phase 1 drives.
- `adversarial-review:adversarial-review` — the Claude-versus-adversary engine (Codex or Gemini) Phase 2 drives, and `pr-audit.py` for the audit trail.
- Repo `CLAUDE.md` — commit/branch/preflight discipline and any "keep X in sync" mandates.
