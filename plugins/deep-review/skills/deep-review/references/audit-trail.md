# Audit trail — one record per round

Every round of Phase 1 and Phase 2 is saved on the PR (or, with no PR, in the local report file) by
the adversarial-review plugin's `scripts/pr-audit.py`. You write one JSON record per round; the
script posts it. Never post comments by hand.

## Setup (Phase 0)

```bash
RUN_ID="dr-$(date +%Y%m%d-%H%M%S)-$$"
RUN_DIR="$(mktemp -d)"
AUDIT="<adversarial-review plugin dir>/skills/adversarial-review/scripts/pr-audit.py"
K=0            # round counter, shared by both phases
PREV_HEAD=null # previous round's head SHA, JSON null for the first round
PR=""          # the PR number in PR mode; empty in local mode
NO_POST=false  # true when the user asked not to post to the PR
```

## After each round

1. `K=$((K+1))`. Head SHA: `gh pr view "$PR" --json headRefOid -q .headRefOid` in PR mode,
   `git rev-parse HEAD` otherwise.
2. Write `$RUN_DIR/round-$K.json`:

```json
{
  "schema": "audit-round/v1", "run_id": "<RUN_ID>", "skill": "deep-review",
  "phase": "phase1 | phase2-r1 | phase2-r2 | phase2-r3 | phase2-fix",
  "round": <K>, "adversary": "gemini | codex | claude-only",
  "head_sha": "<40 hex>", "prev_head_sha": <PREV_HEAD>,
  "findings": [{
    "id": "R-001", "origin": "claude | gemini | codex",
    "path": "src/a.py or null", "line": 41,
    "severity": "critical | important | minor", "category": "bug",
    "title": "...", "rationale": "...",
    "status": "survivor | rejected | unconfirmed",
    "events": [ only THIS round's events, in order ]
  }]
}
```

   Events: `{"by": "claude|gemini|codex", "kind": "verdict", "verdict": "confirm|refute", "text": "..."}`,
   `{"by": ..., "kind": "counter", "text": "..."}`,
   `{"by": ..., "kind": "resolution", "resolution": "fixed|pushback|deferred", "sha": "<40 hex, only once committed>", "text": "..."}`,
   `{"by": ..., "kind": "recheck", "result": "resolved|partly|missed", "text": "..."}`.

3. Post it:

```bash
if [[ "$NO_POST" == "true" ]]; then python3 "$AUDIT" local --record "$RUN_DIR/round-$K.json" --out "<branch with / as ->.adversarial-review.md";
elif [[ -n "$PR" ]]; then python3 "$AUDIT" post --pr "$PR" --record "$RUN_DIR/round-$K.json";
else python3 "$AUDIT" local --record "$RUN_DIR/round-$K.json" --out "<branch with / as ->.adversarial-review.md"; fi
```

   pr-audit.py only trusts markers in comments written by the logged-in `gh` user, so post with
   the same account every round.

4. `PREV_HEAD="\"<head sha>\""`.

Exit codes:

- 0: everything was posted.
- 1: the trail is incomplete. Some posts failed (listed on stderr), or it went to the local file
  because `gh` is unusable or the PR cannot be read. Note it for the final report and carry on.
  Rerunning the same command later posts only what is missing and updates the summary.
- 2: the record is invalid. Fix the JSON and rerun.
- 3: pr-audit.py crashed. Some posts may already be on the PR, so the trail may be partial.
  Note its one-line error for the final report and carry on.

A posting failure never stops the review.

## What goes in each record

| Round | Findings to include | Events |
|---|---|---|
| Phase 1, each round | every actionable finding raised this round, ids `R-001…` continuing across rounds; plus earlier findings being re-checked; `adversary: claude-only` | `resolution` for each fix or pushback (`fixed` has no `sha` until the Phase 1 commit); `recheck` by the re-reviewer for findings fixed last round |
| Phase 2 R1 | all Claude (`C-`) and adversary (`G-`/`X-`) findings, `status: unconfirmed` | none |
| Phase 2 R2 | every judged finding; confirmed findings get `status: survivor`, refuted ones keep `status: unconfirmed` — a refute's final status is decided in R3, not here | `verdict` by the judging model |
| Phase 2 R3 | every R2-refuted finding | For contested findings, record `counter` then `verdict`: `survivor` if the refuter backed down, `rejected` if the origin gave up. Every other R2-refuted finding gets `rejected`. |
| Phase 2 fix | survivors | `resolution` with the Phase 2 commit `sha` |

A `rejected` finding's thread is resolved at once. So a finding refuted in R2 keeps
`status: unconfirmed` in the phase2-r2 record, even though its refute `verdict` is recorded there.
Writing `rejected` in R2 would close the thread before the R3 counter round runs. A contested
refutation could then flip the finding back to `survivor` after its thread was closed.

A fixed finding's thread stays open until the latest `recheck` event on it in the record says
`resolved` and was made by the record's `adversary` (with `claude-only`, any model's re-check
counts). Phase 1 records use `"adversary": "claude-only"`, so the Claude re-reviewer's re-check can
resolve a Phase 1 thread. Phase 2 records use the Phase 2 adversary: `gemini`, `codex` later, or
`claude-only` when Step 2.0 degrades. With `gemini` or `codex`, only that model's re-check resolves
a Phase 2 thread.

Phase 2 has no adversary re-check round yet, so fixed Phase 2 threads stay open until the re-review
rounds that #135 part 2 adds. On repos that require conversation resolution before merge, resolve
those threads by hand after checking the fix.
