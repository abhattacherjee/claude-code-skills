# Dispatch contract — results on disk, silence is a gap

Review agents often finish their work and never deliver it: they go idle with no reply, and
chasing them rarely helps (#121). In one round 6 of 9 agents delivered nothing. What fixed it was
the delivery mechanism, not the prompt: each agent writes its results to a file the orchestrator
named, and the orchestrator reads that file. Every dispatch in `review:deep` and
`review:adversarial` follows this contract: reviewers, judges and implementers.

## Contents

- The block every dispatch starts with
- Results files
- Collect results from disk
- Silence, the chase cap, and NO REPORT
- When an agent says it is waiting on a background job

## The block every dispatch starts with

Put this at the top of every dispatch. Replace `<RESULTS_FILE>` with an absolute path under
`<RUN_DIR>` from the table below, and `<SHAPE>` with that row's shape.

```
DELIVERY CONTRACT — READ FIRST. Agents doing this job have finished their
analysis and never delivered it. Your deliverable is a file, not your reply.
Before you reply, use the Write tool to write your results to <RESULTS_FILE>
in this shape: <SHAPE>. Write it even if you found nothing, and even if your
work is not finished: write early, overwrite as you go, and add
"partial": true at the top level until you are done. Your reply can be one
word. Budget about 15 tool calls (an implementer: write the file after each
numbered fix). A partial file that lands beats a full analysis that does not.

LONG RUNS. Run long harnesses (mutation runs, fuzzers, full suites) in the
foreground, keeping each Bash call under the 10-minute cap: chain calls, or
split the harness into chunks, rather than backgrounding it. On a long run,
update the results file and send partial results at least every ~20 minutes.
Never go idle "waiting for your background run": an idle agent is not woken
when its own background job ends.
```

## Results files

All live in `<RUN_DIR>`. No script writes these names. The scripts write `r1-<ADVERSARY>.json`,
`r2-<ADVERSARY>-verdicts.json`, `r3-codex-counters.json`, `report.md`, `report.json`,
`round-<K>.json`, `fix-range-<K>.diff`, `cites-<K>.diff` and `recheck-<K>.json`, and the Step 2.2
Gemini fallback writes `r2-gemini-prompt.txt`; `review:adversarial` also writes
`r1-empty.json` and `r2-empty.json`.

| Dispatch | Results file | Shape |
|---|---|---|
| Phase 1 reviewer, round `N`, dimension `D` | `p1-r<N>-<D>.json` | `{"dimension":"<D>","status":"CONVERGED\|FINDINGS","findings":[{"severity":"critical\|important\|suggestion","path","line","issue","fix"}]}` |
| Phase 1 implementer, round `N` | `p1-r<N>-fix.md` | each numbered fix: what changed, the commands run and their exit codes |
| R1 `review:bug-hunter` | `r1-bug-hunter.json` | `{"findings":[...]}`, the agent's own format |
| R1 `review:convention-reviewer` | `r1-convention.json` | `{"findings":[...]}`, the agent's own format |
| R2 `review:cross-examiner` | `r2-claude-verdicts.json` | `{"verdicts":[{"id","claude_verdict":"confirm\|refute","reason"}]}` |
| R3 Claude agent that concedes or defends | `r3-claude-counters.json` | `{"counters":[{"id","position":"concede\|defend","reason"}]}` |
| Phase 2 implementer, fix pass `n` | `p2-fix-<n>.md` | as the Phase 1 implementer |

`N` is the Phase 1 round number (1, 2, ...), not the audit-trail counter `K`. `n` is 1 for the
first Step 2.5 pass and goes up by 1 each time Step 2.6 sends you back. `<D>` is a short dimension
name: `code`, `tests`, `silent-failure`, `types` or `comments`. In a re-review, a prior finding
that is not resolved goes back in `findings`; `status` is `CONVERGED` only when `findings` holds
no critical or important item.

**The path must not exist when you dispatch.** A file left by an earlier dispatch would read as
this one's delivery. Check first (`ls "<RESULTS_FILE>"` must fail). A retry of the same slot gets
a new name: add `-retry1`, `-retry2` before the extension. Before the `review:adversarial`
low-signal re-judge, move the old `r2-claude-verdicts.json` to `r2-claude-verdicts.prev.json`.

## Collect results from disk

When every agent in the step has replied or gone idle, read each results file from disk. The
reply is not the result, and a lost reply costs nothing.

- The file parses and has the shape: **delivered**.
- It has `"partial": true`: **PARTIAL**. Use what is there, and report the rest as a gap.
- It is missing, empty or does not parse: **not delivered**. Go to the next section.
- The reply carries results but no file was written: write the reply's content to the file
  yourself and note "delivered by reply".

Then merge, aggregate or synthesize from the files, as the step says.

## Silence, the chase cap, and NO REPORT

1. **Chase at most twice.** Each chase is one SendMessage: "Write `<RESULTS_FILE>` now with what
   you have, even if partial, then reply 'done'." After each chase, check the file, not the reply.
2. **Then switch mechanism once.** Do not chase a third time. Either send a fresh dispatch with
   this contract and a `-retry1` path, or run that dimension yourself when it is small. Chase the
   replacement at most twice as well.
3. **Then record `NO REPORT`.** A dimension with no file after that is a coverage gap. It is
   never CONVERGED and never "no findings":
   - Phase 1: the round cannot converge. Run the next round or, at `--max-rounds`, report it.
   - R1: say in the R1 digest which Claude finder is missing; the merged `r1-claude.json` holds
     only what was delivered.
   - R2: write `{"verdicts":[]}` to `r2-claude-verdicts.json` so `synthesize.py` can run, and say
     in the R2 digest that Claude's verdicts are missing. The adversary's findings stay
     unconfirmed.
   - Implementer: verify against ground truth (`./delegated-verification.md`) before you trust
     any fix.
4. **List every NO REPORT and PARTIAL in the final report:** phase, round, dimension, and what
   was tried (chases, retry, ran it yourself).

## When an agent says it is waiting on a background job

Check its results file, output or process within about 10 minutes
(`ps -axo pid,etime,command | grep <harness>`, or its scratch output), and ping it if it is idle.
Never report "waiting on X" to the user without having looked at X. An idle agent is not woken
when its own background job ends.
