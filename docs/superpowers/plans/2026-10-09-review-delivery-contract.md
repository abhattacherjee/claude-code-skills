# Review delivery contract (#121, #189)

Branch `feature/121-189-review-delivery`, base `develop` at 376306c.

## Goal

- **#189.** A cross-examiner verdict file keyed `verdict` instead of `claude_verdict` made
  `synthesize.py` warn and report fewer survivors as if the run were valid. Name the key in the
  docs, and make `synthesize.py` stop with a clear message.
- **#121.** Review agents finish their work and never deliver it. Make every dispatch write its
  results to a file the orchestrator named, read results from disk, report silence as a coverage
  gap, and cap chasing.

## Plan

1. **`synthesize.py` fails on an unrecognized verdict (#189).** When any verdict entry has no
   `confirm` or `refute` under the key its direction reads, print one error per direction. It names
   the key it expected (`claude_verdict` for Claude judging the adversary, `adversary_verdict` for
   the other direction) and what it found (`found key 'verdict'`, or `found value 'reject'`). Then
   exit **5**. Codes 0, 1 and 2 are taken in this script. 3 means `ADVERSARY_UNAVAILABLE` in
   `codex-review.sh`, `gemini-review.sh` and `pick-adversary.sh`, and 4 is a `sink.sh` failure, so
   5 cannot be mistaken for either. On exit 5 it writes no report and no `survivors=` line, and it
   deletes any file already at the `--md` or `--json` path, so an old report cannot pass for this
   run's. Fail-first test in `run-tests.sh`: a `verdict`-keyed Claude verdicts file.
2. **Docs name the verdict shape (#189).** `deep/SKILL.md` Step 2.2 and `adversarial/SKILL.md`
   Step 3(a) give `{"verdicts":[{"id":"X-001","claude_verdict":"confirm","reason":"..."}]}`, with
   `claude_verdict` one of `confirm|refute`. `agents/cross-examiner.md` already uses that shape.
   The R2 digest's `UNRECOGNIZED` banner and Step 4 say exit 5 now stops the run.
3. **File-first delivery (#121).** New `deep/references/dispatch-contract.md`:
   - the block every dispatch starts with: write results with the Write tool to the absolute path
     the orchestrator gives, before replying, even if empty or partial; the reply can be one word;
     budget tool calls;
   - the never-idle / foreground-harness rule, once (both halves: what the agent does, and what the
     orchestrator checks before saying "waiting on X");
   - results file names, chosen not to collide with what the scripts write in `RUN_DIR`;
   - collect results from disk; silence is `NO REPORT`; chase at most twice, then switch mechanism.
   `deep/SKILL.md` Phase 1 steps 1, 3 and 4, Steps 2.1, 2.2, 2.3 and 2.5, the Final report and a
   new Red Flag point to it. `adversarial/SKILL.md` Steps 2(a) and 3(a) point to it too.
4. **Body length.** `deep/SKILL.md` body must get shorter (450 now; the validator fails at 500).
5. **Versions.** `review` 1.0.2 to 1.1.0 (`plugin.json`, `marketplace.json`, both READMEs);
   `deep` 1.0.1 to 1.1.0; `adversarial` 1.0.0 to 1.1.0; CHANGELOG entries at root, plugin and skill.
6. Not here: the `/ship` criterion of #121 lives in another repo.

## Corrections to the brief

- **`p1-r<K>-<dimension>.json` uses the wrong counter.** `K` is the audit-trail round counter. It
  is shared by both phases and advances only when a round is recorded, so it is not the Phase 1
  round number while a round runs. Phase 1 files use the Phase 1 round number `N` instead:
  `p1-r<N>-<dimension>.json`.
- **Reading from disk opens a stale-file hole.** A re-review, a chase replacement and the
  low-signal re-judge all reuse a slot. If the old file is still there, the orchestrator reads it as
  this dispatch's delivery. The contract says the path must not exist when the dispatch goes out:
  every retry gets a new name (`-retry1`), and the low-signal re-judge moves the old
  `r2-claude-verdicts.json` aside first.
- **The agents themselves say "return only a JSON object".** `bug-hunter.md`,
  `convention-reviewer.md` and `cross-examiner.md` must also say: when the dispatch names a results
  file, write the same JSON there first. The brief only asked for the cross-examiner shape check.
- **Tests pin the old behaviour.** `run-tests.sh` "Fix-D" expects exit 0 on unrecognized verdicts,
  and `test_skill_docs.py` `test_the_old_prompt_shape_is_not_what_the_docs_ask_for` expects exit 0
  on a `verdict`-keyed file. Seven `test_skill_docs.py` tests assert the never-idle text inside
  each `deep` step. All move to the new behaviour: the step tests check for the pointer, and new
  tests check the rule text in `dispatch-contract.md`.
- **A stale report survives a failed run.** The low-signal re-run writes `report.md` and
  `report.json` again in the same `RUN_DIR`. If that run stopped without touching them, the first
  run's report would still be there and look valid. Hence the delete on exit 5.
- **Exit code.** "A code that does not collide" has to be plugin-wide, not per-script: the skills
  already branch on "exit 3" from other scripts. So 5, not 3.
- **`adversarial/SKILL.md`'s never-idle text stays.** It is short, tested by its own doc tests and
  not repeated six times; only `deep` is consolidated.
