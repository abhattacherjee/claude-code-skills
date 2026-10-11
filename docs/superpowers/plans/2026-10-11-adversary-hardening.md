# Adversary hardening: Gemini time limit, stale Codex CLI, Codex refusal

Issues: #53, #207, #185, #171 (milestone v4.2). One branch, `feature/adversary-hardening`, one PR.

Scripts live in `plugins/review/skills/adversarial/scripts/` (called `S/` below). `deep` calls them
through `${CLAUDE_PLUGIN_ROOT}/skills/adversarial/scripts/`. There is no second copy.
Test suite: `bash plugins/review/skills/adversarial/scripts/run-tests.sh` (what CI runs).

## What already exists (do not rebuild)

- `gemini-review.sh --mode find` (lines 349-393) and CLI-envelope unwrapping (`extract_model_answer`, 236-338).
- The 8 MiB stdin cap in `gemini-review.sh` (lines 519-528).
- `codex_review.py --timeout` / `CODEX_REVIEW_TIMEOUT`, default 540 (`DEFAULT_TIMEOUT`, `run_codex` 567-590). It kills the process group with `start_new_session=True` and `os.killpg`.

## Rulings

- **#53 path exclusion is not built.** A reviewer that silently drops files from the diff fails open. The time limit bounds the hang, and the byte cap already exists.
- **Refusal and stale CLI keep exit 3.** Every existing exit-3 branch in both SKILL.md files keeps working unchanged. The distinct reason is in the stderr prefix (`ADVERSARY_REFUSED:`) or message text, never a new exit code.
- **Detection is anchored on `codex exec`'s own `ERROR:` line.** Match only the stderr of a `codex exec` that exited nonzero, and only on a line that starts with `ERROR:` (`(?m)^ERROR: [^\n]*<phrase>`). The diff is sent on stdin and may be echoed to stderr, but its lines never start with `ERROR:` (diff lines start with ` `, `+`, `-`, `@` or a header). Real refusal text, from a 2026-10-03 run: `ERROR: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. ...`
- **The #171 fallback never closes a Codex thread.** Only Codex's own re-check closes one (`deep/references/audit-trail.md`). Gemini sweeps the fix-range diff for new defects, and every Codex thread it would have re-checked stays open, marked as refused.

## Tasks

### Task 1 — Gemini time limit (#53)

`S/gemini-review.sh`:
- Add `--timeout <secs>` (integer ≥ 1, else usage exit 2), then env `GEMINI_REVIEW_TIMEOUT` when it is a positive integer, else 540. Same precedence as `codex_review.py`.
- Run each `gemini` call through a small bounded runner that puts it in its own process group and kills the whole group on timeout. macOS bash 3.2 has no `setsid` and no `timeout`. Use `python3` (already a dependency of the script) with `subprocess.Popen(..., start_new_session=True)`, `os.killpg(..., SIGKILL)` on `TimeoutExpired`, and the existing stdin/stdout/stderr file redirects. The runner returns a distinct code (124) for a timeout.
- On timeout: print `ADVERSARY_UNAVAILABLE: gemini timed out after <N>s; killed its process group` and exit 3. Do not retry a timed-out call (the existing JSON retry at lines 573-580 is only for a call that returned).
- Update the header comment and `--help` text.
- Tests (in `test_gemini_review.py`, using its `STUB`): a stub that sleeps 30 s and spawns a child, run with `--timeout 2`; assert exit 3, the message, wall time well under 30 s, and that the stub and its child are gone. Also: `--timeout 0` is a usage error; `GEMINI_REVIEW_TIMEOUT` is honoured; a timed-out call is made only once.

`plugins/review/skills/deep/SKILL.md` line ~252 runs `gemini ... < prompt` directly. Bound it: prefer replacing it with a `gemini-review.sh` call if that fits the step. If it does not, wrap it as `perl -e 'alarm 540; exec @ARGV' gemini ...` with stdin from the file, and say that exit 142 means the time limit fired.

### Task 2 — `--timeout` in the SKILL.md commands (#207)

In `skills/adversarial/SKILL.md` and `skills/deep/SKILL.md`, every `codex-review.sh` and `gemini-review.sh` command that runs a review passes `--timeout 540` (R1 find, R2 judge, the `--strict` re-judge, R3 counter, the Step 2.6 re-check, and the new Gemini sweep from Task 4). `--self-test` is not a review; leave it. Add one line in each file: do not wrap these scripts in `timeout`; macOS has none, and the wrapper fails with exit 127 before the review starts. The scripts bound themselves. `test_skill_docs.py` / `test_skill_paths.py` must stay green; add a test that every review command line in both files carries `--timeout` (a static check over the fenced commands).

### Task 3 — Stale Codex CLI (#185)

`S/ensure-codex.sh` (bash 3.2, always exit 0 except usage, output through the existing `emit()`):
- New lines `CODEX_STALE` (`yes|no|unknown`), `CODEX_NEWER_BIN` (path or `-`) and `CODEX_STALE_HINT`.
- Sources, each optional: `client_version` in `${CODEX_HOME:-$HOME/.codex}/models_cache.json`, read with `python3 -c` and never `eval`'d; and the ChatGPT-bundled binary at `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`. Tests can override that path with `CODEX_APP_BIN`. Run that binary's `--version` with stdin closed and a bound (`perl -e 'alarm 10; exec @ARGV'`).
- Compare MAJOR.MINOR.PATCH numerically, ignoring a prerelease suffix (so `0.159.0-alpha.12.1` counts as `0.159.0`). `yes` when the current version is lower than either source. `no` when at least one source was read and neither is higher. `unknown` when no source could be read, or the current version is unknown.
- When the bundled binary is newer, `CODEX_NEWER_BIN` is its path, and the hint is `ln -sfn <that path> "$(command -v codex)"`. Otherwise the hint names the newer version and says to update the Codex CLI.
- Tests in `test_ensure_codex.py`: stale against the cache; stale against a fake bundled binary; current; unknown (no sources); a malformed `models_cache.json` gives `unknown`, not a crash; exit 0 in every case; output still `eval`-safe.

`S/codex_review.py`:
- When `codex exec` exits nonzero and its stderr has a line matching `(?m)^ERROR: [^\n]*is not supported when using Codex with a ChatGPT account`, raise `Unavailable` with a message naming the cause. Example: `codex CLI <version> looks stale: the server refused the model for this client. Check for a newer CLI (ensure-codex.sh --check prints CODEX_STALE) before changing the model or logging in again.` Exit stays 3, prefix `ADVERSARY_UNAVAILABLE:`.
- Test via `fixtures/codex_stub.py` (`exec` action `stderr` + `exit`): the real two-line message (the `Model metadata ... not found` warning, then the `ERROR: {...400...}` line) gives the stale message. A generic failure still gives `codex exec exited N`.

`skills/adversarial/SKILL.md`: one line in Degradation Behavior (there is no Troubleshooting section): if Codex says a model is "not supported when using Codex with a ChatGPT account", run `ensure-codex.sh --check` and read `CODEX_STALE` before changing the model or logging in again.

### Task 4 — Codex refusal and the Gemini sweep (#171)

`S/codex_review.py`:
- When `codex exec` exits nonzero and its stderr has a line matching `(?m)^ERROR: [^\n]*flagged for possible cybersecurity risk`, raise a new `Refused` exception (a subclass of `Unavailable`, so exit 3). `main()` prints it with the prefix `ADVERSARY_REFUSED:` instead of `ADVERSARY_UNAVAILABLE:`. Update the module docstring's exit-code list.
- Tests: the real refusal text through the stub gives exit 3 and `ADVERSARY_REFUSED:`. The same sentence on a line that does not start with `ERROR:`, or inside the diff while exec fails for another reason, gives `ADVERSARY_UNAVAILABLE:`.

`S/gemini-review.sh`:
- `--id-start N` (find mode only, N ≥ 1; else usage exit 2), numbering new findings `X-NNN` from N, as `codex_review.py` does. Check how find-mode ids are assigned today (the model writes `"<unique-id>"` at lines 71 and 363). The script must assign the ids itself, not trust the model's. Test it.

`skills/deep/SKILL.md` Step 2.6:
- Split exit 3: stderr starting `ADVERSARY_REFUSED:` versus everything else. Everything else keeps today's text unchanged: stop the loop, no fallback.
- On `ADVERSARY_REFUSED:` with auto mode (no `ADVERSARY_FLAG`) and `GEMINI_AUTHED=yes`, run `gemini-review.sh --diff "<RUN_DIR>/fix-range-<FIX_K>.diff" --mode find --id-start <...> --timeout 540 --out "<RUN_DIR>/recheck-<K>-gemini.json"`. Record any new findings as Gemini-origin findings, the same way Phase 2 records Gemini findings. Read `references/audit-trail.md` and `audit_record.py` to find that path, and do not invent a new record shape. Leave every Codex re-check thread open, noted as "Codex refused the re-check; not closed". Say so in the round summary. Then stop the re-check loop: the next fix gets no Codex re-check either.
- With `ADVERSARY_FLAG=codex`, or `GEMINI_AUTHED` not `yes`: stop as today, and name the refusal in the summary.
- Update `adversarial/SKILL.md`'s exit-code notes so `ADVERSARY_REFUSED:` is listed as a kind of exit 3. At R1 the existing auto switch to Gemini already covers it.

### Task 5 — Versions and changelogs

`review` 1.3.0: `plugins/review/.claude-plugin/plugin.json`, `metadata.version` in both SKILL.md files, `plugins/review/CHANGELOG.md` and both skill CHANGELOGs (`## [1.3.0] - <date>`), and an `[Unreleased]` entry in the root `CHANGELOG.md`. Then run `scripts/catalogue.py` (or whatever `scripts/check-docs.sh` says) so the README catalogue and `marketplace.json` match. Count every number in the CHANGELOG from the diff.

## Failure modes (write these tests first)

1. **Fail-open paths.** A Gemini hang must end as exit 3, never as success. A refusal must never read as "no findings". A `models_cache.json` that cannot be read must give `CODEX_STALE=unknown`, never `no`. The Gemini sweep must not close a Codex thread. Tests: timeout exit 3; refusal exit 3; malformed cache gives `unknown`; and a doc test that Step 2.6 says the Codex threads stay open.
2. **Exit codes.** `ensure-codex.sh` must stay exit 0 when every new source fails. The timeout runner's 124 must map to 3, not leak out as 124. `--timeout 0` and `--id-start 0` exit 2. Tests for each.
3. **Date boundaries.** Not applicable: nothing here reads a date.
4. **Doc counts.** CHANGELOG entries and the PR body state no number the diff does not support. Count from `git diff`.
5. **Broken Markdown.** New SKILL.md lines and CHANGELOG entries stay inside their list or table blocks. `scripts/check-docs.sh` and markdownlint (via `scripts/commit-preflight.sh`) must pass.

## Out of scope

- #171's optional pre-flight probe on security-heavy diffs.
- A Gemini fallback at R2 / R3 (still R1 only).
- Refusal detection for Gemini.
