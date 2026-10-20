# Tiered lane — the `--lane tiered` steps

`review:deep --lane tiered` runs the steps below in place of Phase 1 and Phase 2's R1 to R3. The
steps use Phase 2's building blocks (Steps 2.0 to 2.6 in SKILL.md). Each step says where this lane
differs. Scripts are written `<SCRIPTS_DIR>`, as in the other reference files.

Use the Step 2.6 values by name: `FIX_K`, `FIX_SHA`, `REVIEWED_SHA`, `BASE_REF`, `RECHECK_ROUND` and
`ID_START`. This file does not redefine them. Run Step 2.0 first (`ADVERSARY`, `ADVERSARY_FLAG`),
because T0 needs to know whether a cross-model reviewer exists.

## Contents

- T0 Size gate
- T1 Round 1
- T2 Judge
- T3 Tiebreak
- T4 Fix
- T5 Re-check and sign-off
- T6 Fallbacks

### T0 Size gate

Write every changed file path to `<RUN_DIR>/files.txt`, one per line. Take the list from
`git diff --name-only` on the whole change, before Phase 0 leaves out lockfiles and generated files.
A lockfile hidden from this list would turn a mixed diff into a `light` one. Then run:

```bash
python3 "<SCRIPTS_DIR>/lane_scope.py" --files "<RUN_DIR>/files.txt"
```

It prints `light` or `full`. Only the exact word `light` takes the light path. Exit 2, any other
output, or an empty file list means `full`. If `ADVERSARY` is `claude-only` there is no cross-model
reviewer, so the answer is `full` whatever the script says.

- `full`: go to T1.
- `light` (only dependency manifests, lockfiles or docs changed): first wait for CI. With a PR,
  poll `gh pr checks <PR>` until nothing is pending. Any failing check: stop and tell the user. With
  no PR, run `./scripts/commit-preflight.sh` (or the repo's equivalent) and stop if it fails. Then
  run only the adversary find command from T1, with no Claude reviewers. Give it the whole diff,
  lockfiles included; Phase 0 would leave them out, and the diff would be empty. Its findings go through
  T2 to T4 as usual, and T5 signs off.

### T1 Round 1

In one message, launch these three, none seeing the others:

- `review:bug-hunter`, dispatched with `model: "sonnet"`.
- `review:convention-reviewer`, dispatched with `model: "sonnet"`.
- The adversary finder:

```bash
"<SCRIPTS_DIR>/codex-review.sh" --mode find --diff <DIFF> --timeout 540 --out "<RUN_DIR>/r1-<ADVERSARY>.json"
```

With Gemini, use `gemini-review.sh` in its place. Handle exit 3 and exit 4 as Step 2.1 says,
including the forced-adversary stop. If Codex was picked automatically and is unavailable, T6
applies.

Both Claude dispatches use the delivery contract in `./references/dispatch-contract.md`, with its
tool-call budget (results files `<RUN_DIR>/r1-bug-hunter.json` and `<RUN_DIR>/r1-convention.json`).
Give them the byte-identical diff and the untrusted-input text from Step 2.1. Merge the two Claude
files into `<RUN_DIR>/r1-claude.json` (`C-001..`) and record the round, as Step 2.1 says.

### T2 Judge

A finding both sides raised needs no judge. Find those first. This run takes no verdict files:

```bash
"<SCRIPTS_DIR>/synthesize.py" --match \
  --adversary "<ADVERSARY>" \
  --claude-findings "<RUN_DIR>/r1-claude.json" \
  --adversary-findings "<RUN_DIR>/r1-<ADVERSARY>.json" \
  --json "<RUN_DIR>/match.json"
```

Every finding in `match.json` with `status_reason` "raised by both" is a survivor already. Every
other finding is unmatched. When unsure whether two findings match, treat both as unmatched: the
judge sees them. A wrong match must never skip a judge.

- The adversary judges the unmatched Claude findings: Step 2.2's `--mode judge` call, with a
  findings file that holds only those.
- `review:cross-examiner` judges the unmatched adversary findings. Its prompt holds only those
  findings, each with its cited line range, and nothing else from the run. It keeps its read-only
  repo tools, so it still reads the current source. Dispatch it as Step 2.2 says (results file
  `<RUN_DIR>/r2-claude-verdicts.json`, with the exact verdict shape given there).

When both judges are done, run Step 2.4's `synthesize.py` command with `--match` added. Then
apply R3 concessions by hand, as Step 2.4 says. On the light path there are no Claude findings, so
only the cross-examiner runs.

### T3 Tiebreak

Findings that the other side refuted get Step 2.3's concede or defend turn. If the originator
defends, `review:cross-examiner` decides from three things only: the finding, the defence and the
cited lines. Opus is never asked to judge an Opus finding: no Claude reviewer runs on Opus in this
lane. Record the round as Step 2.3 says.

### T4 Fix

One fix wave for all survivors, as Step 2.5 says: check cites first, then one implementer sub-agent
on `model: "sonnet"`. Use Opus for the implementer only when a fix touches a security gate, data
migration or destructive path, and say why. Verify the fixes in your own context, as Step 2.5
says, and record `phase2-fix`.

### T5 Re-check and sign-off

The adversary re-checks the fix range `REVIEWED_SHA..FIX_SHA` with `--prior`, under the cap
`RECHECK_ROUND` = 3. Right after the `phase2-fix` record, set `FIX_K` and `FIX_SHA` as Step 2.6
says, work out `ID_START` again before each call, and add 1 to `RECHECK_ROUND` on each pass. With
Codex, run Step 2.6 as written, including its exit-code rules. With Gemini, T6 gives the command.
The re-check is the sign-off:

- Clean means signed off: every finding the adversary can check is `resolved`, `unchecked=0`, and
  there are no new survivors. The final report names the sign-off model (Codex or Gemini) and the
  `FIX_SHA` it checked.
- New findings go back through T2 to T4, for those findings only. Then re-check the new fix range.
- At the cap, the open items go to the user. The run is not signed off.

The Claude reviewers do not run again in rounds 2+. There is one exception: a re-check finding that
changes the design, or touches the guard behind a Critical. For that, run T1's two reviewers once
more on the fix range.

### T6 Fallbacks

- **Codex is unavailable at the start.** Step 2.0 returns `ADVERSARY=gemini`. Gemini then does
  every adversary job in T1 to T5. For T5, run:

```bash
"<SCRIPTS_DIR>/gemini-review.sh" --mode find --prior "<RUN_DIR>/round-<FIX_K>.json" --id-start <ID_START> --diff "<RUN_DIR>/fix-range-<FIX_K>.diff" --timeout 540 --out "<RUN_DIR>/recheck-<K>.json"
```

  Exit 4 (`SECRET_SUSPECTED`): as in Step 2.1. Exit 3 or 1: stop, leave the threads open and name the
  failure. On exit 0, build and post the record with
  `python3 "<SCRIPTS_DIR>/pr-audit.py" recheck --adversary gemini --prior "<RUN_DIR>/round-<FIX_K>.json" --rechecks "<RUN_DIR>/recheck-<K>.json" --round "<K>" --head-sha "<FIX_SHA>" --out "<RUN_DIR>/round-<K>.json"`.
  Gemini closes resolved threads for findings with `origin` `gemini` or `claude`, the way a Codex
  re-check closes Codex's and Claude's. It never closes a Codex finding: those threads stay open for
  a person to resolve; list them in the final report. A clean Gemini re-check (no new survivors,
  every re-checked finding resolved) is a sign-off, and the report names Gemini.
- **Codex becomes unavailable during the re-check.** Stop the re-check loop at once, as Step 2.6
  says for any other exit 3, and leave the remaining threads open. Do not retry, and do not switch
  to Gemini mid-loop; the one exception is Step 2.6's own `ADVERSARY_REFUSED:` sweep. Post the
  round summary and tell the user. The run is not signed off: the report's first line says `Not signed
  off: Codex unavailable during the re-check (<reason>)`.
- **No cross-model reviewer.** Follow Step 2.0's Claude-only path (the user is asked first). Run T1
  without the finder; `review:cross-examiner` judges the Claude findings; fix as T4 says; there is
  no re-check. The report's first line says `Not signed off: no cross-model pass (<reason>)`, with
  the reason (quota, login or timeout). Never call this run signed off.
