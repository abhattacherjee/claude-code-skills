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
`git diff --name-only --no-renames` on the whole change, before Phase 0 leaves out lockfiles and
generated files. A lockfile hidden from this list would turn a mixed diff into a `light` one, and
without `--no-renames` a code file renamed into `docs/` shows only its new path. Then run:

```bash
python3 "<SCRIPTS_DIR>/lane_scope.py" --files "<RUN_DIR>/files.txt"
```

It prints `light` or `full`. Only the exact word `light` takes the light path. Exit 2, any other
output, or an empty file list means `full`. If `ADVERSARY` is `claude-only` there is no cross-model
reviewer, so the answer is `full` whatever the script says.

- `full`: go to T1.
- `light` (only lockfiles or docs changed; manifests such as `package.json` can carry scripts, so
  they are `full`): first wait for CI. With a PR,
  poll `gh pr checks <PR>` until nothing is pending. Any failing check: stop and tell the user. With
  no PR, run `./scripts/commit-preflight.sh` (or the repo's equivalent) and stop if it fails. Then
  run only the adversary find command from T1, with no Claude reviewers. Give it the whole diff,
  lockfiles included; Phase 0 would leave them out, and the diff would be empty. There are no
  Claude findings, so write `{"findings":[]}` to `<RUN_DIR>/r1-claude.json` and `{"verdicts":[]}` to
  `<RUN_DIR>/r2-<ADVERSARY>-verdicts.json` before T2: `synthesize.py` stops on a missing file. The
  adversary's findings go through T2 to T4 as usual, and T5 signs off.

### T1 Round 1

In one message, launch these three, none seeing the others:

- `review:bug-hunter`, dispatched with `model: "sonnet"`.
- `review:convention-reviewer`, dispatched with `model: "sonnet"`.
- A test-quality pass, when the change adds or edits a test, or adds a check, guard or
  validation: a second `review:bug-hunter`, dispatched with `model: "sonnet"`, given the test
  brief below in place of its usual focus.
- The adversary finder:

```bash
"<SCRIPTS_DIR>/codex-review.sh" --mode find --diff <DIFF> --timeout 540 --out "<RUN_DIR>/r1-<ADVERSARY>.json"
```

With Gemini, use `gemini-review.sh` in its place. Handle exit 3 and exit 4 as Step 2.1 says,
including the forced-adversary stop. If Codex was picked automatically and is unavailable, T6
applies.

Every Claude dispatch uses the delivery contract in `./references/dispatch-contract.md`, with its
tool-call budget (results files `<RUN_DIR>/r1-bug-hunter.json`, `<RUN_DIR>/r1-convention.json`
and, when it runs, `<RUN_DIR>/r1-tests.json`). Give them the byte-identical diff and the
untrusted-input text from Step 2.1. Merge the Claude files into `<RUN_DIR>/r1-claude.json`
(`C-001..`) and record the round, as Step 2.1 says.

**The test brief.** The general bug-hunter misses tests that cannot fail: on one replay it found
none of six vacuous-test defects. Give the test-quality pass this brief, and tell it to report
only test and guard defects:

> For each test the change adds or edits, and each check, guard or validation it adds:
> 1. Name the code change that should turn the test red. Read the assertion and decide whether a
>    broken version of the code would still pass it (a prefix or substring check that a wrong
>    value also satisfies, an assertion on a string that is always present).
> 2. For a test that walks files or scans for matches: is there a positive control that the walk
>    found at least one file and the scan at least one match? Without one, an empty walk passes.
> 3. For a regex or pattern guard: list the forms it must catch, including every syntax variant
>    the tool accepts (shorthands, quoting, whitespace), and check each against the pattern.
> 4. Exported or public values the change edits: is each one asserted somewhere?
> 5. Claims in docs or comments about behavior the change adds: is each one true, and tested?
>
> See `./references/vacuous-tests.md` for the patterns. Give each defect `file:line` and the
> concrete test that would catch the regression.

### T2 Judge

First label the findings both sides raised. This run takes no verdict files:

```bash
"<SCRIPTS_DIR>/synthesize.py" --match \
  --adversary "<ADVERSARY>" \
  --claude-findings "<RUN_DIR>/r1-claude.json" \
  --adversary-findings "<RUN_DIR>/r1-<ADVERSARY>.json" \
  --json "<RUN_DIR>/match.json"
```

A matched pair gets `raised_by_both` and `matched_with` in `match.json`. A match is only a label:
it never makes a survivor and never skips a judge, because two different defects on nearby lines
can match. Every finding is judged. The label is only a hint in the report: fix and check each
confirmed finding on its own, even when one change looks like it fixes both.

- The adversary judges every Claude finding: Step 2.2's `--mode judge` call.
- `review:cross-examiner`, dispatched with `model: "sonnet"`, judges every adversary finding.
  Opus runs only in T3, to break a tie. Its prompt holds only those
  findings, each with its cited line range, and nothing else from the run. It keeps its read-only
  repo tools, so it still reads the current source. Dispatch it as Step 2.2 says (results file
  `<RUN_DIR>/r2-claude-verdicts.json`, with the exact verdict shape given there).

When both judges are done, run Step 2.4's `synthesize.py` command with `--match` added, then go to
T3. On the light path there are no Claude findings, so only the cross-examiner runs.

### T3 Tiebreak

Findings that the other side refuted get Step 2.3's concede or defend turn. Collect every
defended finding first, then make **one** `review:cross-examiner` dispatch with `model: "opus"`
for all of them. It decides each from three things only: the finding, the defence and the cited
lines. This is the only Opus call in the lane, at most once per T2 pass, and Opus is never asked
to judge an Opus finding: no Claude reviewer runs on Opus in this lane. Record the round as
Step 2.3 says.

Then write every outcome to `<RUN_DIR>/r3-decisions.json`: concessions and the cross-examiner's
decisions, as `{"decisions":[{"id","status":"survivor|rejected","reason"}]}`. Re-run the T2
`synthesize.py` command with `--decisions "<RUN_DIR>/r3-decisions.json"` added, so `report.json`
and `report.md` carry the outcome before T4 picks the survivors. Never edit `report.json` by
hand: Step 2.5, the re-check and any replay scoring read it.

### T4 Fix

One fix wave for all survivors, as Step 2.5 says: check cites first, then one implementer sub-agent
on `model: "sonnet"`. Never give the fixes to the adversary's model (Codex, or Gemini on the
fallback path), even through a code-change tool such as `cx`: its re-check in T5 is the sign-off,
and it must not sign off its own fixes. This lane never puts the implementer on Opus unless the
user asks for it; Step 2.5's security-gate exception does not apply here, because the adversary
re-checks every fix in T5. Verify the fixes in your own context, as Step 2.5 says, and record
`phase2-fix`.

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
