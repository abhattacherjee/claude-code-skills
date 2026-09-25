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

Exit 1 means some comments failed (listed on stderr). Note it for the final report and carry on;
rerunning the same command later posts only what is missing. Exit 2 means the record is invalid:
fix the JSON and rerun. A posting failure never stops the review.

## What goes in each record

| Round | Findings to include | Events |
|---|---|---|
| Phase 1, each round | every actionable finding raised this round, ids `R-001…` continuing across rounds; plus earlier findings being re-checked; the record's adversary value is explained below | `resolution` for each fix or pushback (`fixed` has no `sha` until the Phase 1 commit); `recheck` by the re-reviewer for findings fixed last round |
| Phase 2 R1 | all Claude (`C-`) and adversary (`G-`/`X-`) findings, `status: unconfirmed` | none |
| Phase 2 R2 | every judged finding, `status: unconfirmed` — a refute's final status is decided in R3, not here | `verdict` by the judging model |
| Phase 2 R3 | findings whose refutation was contested, plus every other R2-refuted finding getting its final status (`rejected` or `survivor`) written | `counter` by the finding's origin, then `verdict` for the concede-or-defend answer |
| Phase 2 fix | survivors | `resolution` with the Phase 2 commit `sha` |

A refuted finding's thread is resolved at once — which is why a finding refuted in R2 keeps
`status: unconfirmed` in the phase2-r2 record even though its `verdict` refute event is recorded
there: writing `rejected` (and resolving the thread) before the R3 counter round has run would let a
contested refutation flip the finding back to `survivor` after its thread was already closed. A
fixed finding's thread stays open until the LATEST `recheck` event on it says `resolved` and was
made by the record's `adversary`. Phase 1 records therefore use `"adversary": "claude-only"`, so the
Claude re-reviewer's re-check can resolve a Phase 1 thread. Phase 2 records use the Phase 2 adversary
(`gemini`, or `codex` later), so only that model's re-check resolves a Phase 2 thread.

Phase 2 has no adversary re-check round yet, so fixed Phase 2 threads stay open until the re-review
rounds that #135 part 2 adds. On repos that require conversation resolution before merge, resolve
those threads by hand after checking the fix.
