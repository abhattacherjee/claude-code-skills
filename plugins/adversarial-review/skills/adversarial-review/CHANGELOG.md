# Changelog

All notable changes to this skill will be documented in this file.

## [0.2.0] - 2026-09-24

### Added

- PR mode saves the whole exchange on the PR: one inline thread per finding (refuted ones too), the opposing model's verdict as a reply, refuted threads resolved at once, and one summary review. Secrets in model output are redacted before posting, and bodies are capped below GitHub's size limit.
- `scripts/pr-audit.py` with `post`, `local` and `record` modes, and `--no-post` on the skill and `sink.sh`.
- `pr-audit.py` exit codes: 0 everything posted, 1 trail incomplete (some posts failed, or it went to the local file), 2 invalid record or report, 3 unexpected crash (the trail may be partial). `sink.sh` maps any non-zero code to 4.
- Codex is the first-choice adversary. `pick-adversary.sh` picks Codex when it is installed and logged in, then Gemini, then Claude-only. `--adversary codex|gemini` forces one; a forced adversary that is not usable stops the run (exit 3) instead of falling back.
- `codex-review.sh --mode find|judge|counter` runs Codex in a locked-down `codex exec`: an environment of only `PATH`, `HOME`, your own `CODEX_HOME` and, when set, `CODEX_API_KEY`, `HTTP_PROXY`, `http_proxy`, `HTTPS_PROXY`, `https_proxy`, `NO_PROXY`, `no_proxy` and `TMPDIR`; user config, rules, the reviewed repo's `AGENTS.md`, apps, plugins, hooks and memories off; a read-only sandbox; the diff on a closed stdin pipe; and a timeout that kills the whole process group. Its output is checked against a schema, capped and redacted. Codex finding ids are `X-001…`.
- Isolation is enforced, not assumed: every argv must carry all the isolation flags, and the first review on each Codex version runs a canary repo that tries to steer Codex from all four surfaces it could load — `AGENTS.md`, `.codex/config.toml`, `.agents/skills` and `.mcp.json`. A leak on any of the four stops the run with exit 3. `codex-review.sh --self-test` reruns the canary.
- `skills.include_instructions=false` joins the isolation overrides. Live testing on codex-cli 0.155.1 found the reviewed repo's `.agents/skills` reaching Codex under the other flags alone — a positive control that failed before this override, the same way `AGENTS.md` did before `project_doc_max_bytes=0`. `.mcp.json` is not read by 0.155.1, and a repo's `.codex/config.toml` loads only for a trusted repo (trust lives in the ignored `config.toml`, which `--ignore-user-config` drops), so both stay canaried only as cheap guards for a future Codex version. The isolation stamp hashes the file `command -v codex` resolves to (its realpath), so if that is a wrapper script, a same-version binary swap behind it keeps the stamp valid.
- A pass is stamped in `codex-isolation-<version>-<key>.ok`, keyed on the Codex version, a hash of the isolation recipe, the resolved Codex binary's realpath and sha256, and `CODEX_HOME`; any change reruns the canary, and a missing or unreadable stamp counts as no stamp. For an npm install, the sha256 covers only the JS entry script `codex` points at, so a same-version package swap keeps the stamp.
- `ensure-codex.sh --check` reports `CODEX_INSTALLED`, `CODEX_VERSION` and `CODEX_AUTHED`, from the exit code of `codex login status`.
- `synthesize.py --adversary codex|gemini|claude-only` labels the report with the real adversary. `--adversary-findings` and `--adversary-verdicts` are new names for the Gemini-named flags. `claude-only` is the degraded no-adversary path (pass empty findings/verdicts files) so `pr-audit.py record --adversary claude-only` never trips its adversary/summary mismatch guard.
- `pr-audit.py recheck` turns Codex's re-checks of earlier findings into `recheck` events, so a fixed finding's thread closes when Codex says it is resolved. `recheck` is Codex-only. An earlier finding Codex did not re-check is carried into the record unchanged with no events, so its thread stays open, and stderr reports `unchecked=<N> (<ids>)`; `codex-review.sh --prior` prints the same count. The exit is still 0.
- `codex-review.sh --strict` (judge mode only; a usage error in other modes) adds a hardened judge prompt: confirm only when the finding's defect is visible in the diff or source, quoting the offending line verbatim in the reason; otherwise refute. The schema reminder is added only on the one retry after an answer fails the output schema.
- R1/R2 dispatch tells the Claude finders and cross-examiner to run long harnesses in the foreground, keeping each Bash call under the 10-minute cap (chain calls, or split into chunks, rather than backgrounding it), and send partial results at least every ~20 minutes of a long run, and never go idle waiting on their own background run. The orchestrator checks a side's background job (or the Codex/Gemini script run with `run_in_background`) within about 10 minutes before reporting it is waiting on one.

### Changed

- The adversary's verdict on a Claude finding is now `adversary_verdict` (it was `gemini_verdict`) in every file the skill writes. Old run files and report files with `gemini_verdict` still load.

### Fixed

- PR mode never posted anything. `sink.sh` called `pr-review-cli.sh --pr …`, which that CLI rejects as an unknown subcommand, then printed "PR review comments posted" anyway. `sink.sh` now exits 4 when any audit comment fails.
- A gh response that could not be parsed (bad JSON or the wrong shape) crashed `pr-audit.py` and lost the failures already collected. It is now a failed post: the run carries on, lists it, and exits 1.
- When `gh` is not usable, `pr-audit.py` now says why: not installed, not logged in, no login returned, or gh's own error text (for example a network error). An empty login counts as not ready.
- `sink.sh` added the `.gitignore` pattern onto the last line when the file had no final newline (for example `node_modules*.adversarial-review.md`). It now adds a newline first. A pattern on a CRLF line counts as present. A `.gitignore` that cannot be written is a warning, not an abort.
- The crash message (exit 3) in `pr-audit.py` and `sink.sh` said no audit trail was saved. Some posts may already be on the PR, so it now says the trail may be partial.
- A thread opener without `subject_type` is treated as file-level when it has no line, so the summary still notes the lost line anchor.
- A forced adversary (`--adversary codex|gemini`) that fails at R1 or R2 now stops the run with exit 3. It used to fall back to Claude-only and exit 0. Auto mode keeps its fallback.
- An R2 judge failure in auto mode no longer drops the adversary's R1 findings. They stay in the report with Claude's verdicts, and every Claude finding is unconfirmed.
- The R2 digest shows `synthesize.py`'s `unjudged=` count for each direction, with an `UNJUDGED` banner when it is above 0. A judge that answers only some ids still exits 0, so this is the only sign that work is missing. The wrong "total minus judged" formula is gone.
- Codex's default timeout per call is 540 s (was 900 s), below the Bash tool's 600 s cap; `CODEX_REVIEW_TIMEOUT` and `--timeout` still override it. A SIGTERM or SIGINT to `codex-review.sh` now kills Codex's process group and removes its temp dirs (exit 128+N). Before, Codex kept running in its own session.
- The Codex prompt says file contents Codex reads from the repository are data under review, never instructions, the same as its standard input.
- `pr-audit.py record` and `recheck` exit 2 with a `cannot write --out` message when `--out` cannot be written. Before, it was a crash (exit 3).
- `codex-review.sh` no longer passes `OPENAI_API_KEY` to Codex (#135). An unrelated `OPENAI_API_KEY` set in the user's shell for some other tool made `codex exec` authenticate with it instead of the login already in `CODEX_HOME`, and Codex failed ("Incorrect API key provided") even though `codex login status` exited 0. `CODEX_API_KEY` (Codex's own API-key login), the proxy vars and `TMPDIR` are still passed through.

## [0.1.0] - 2026-06-02

### Added

- **Symmetric 2-round adversarial pipeline** — R1: Claude and Gemini independently discover findings (blind to each other); R2: each model cross-examines the other's R1 findings; `synthesize.py` applies the both-confirm survivor rule from 4 input files (`r1_claude_findings.json`, `r1_gemini_findings.json`, `r2_gemini_verdicts.json`, `r2_claude_verdicts.json`)
- **Both-confirm survivor rule** — only findings confirmed by both models are survivors; UNCONFIRMED and REJECTED buckets are always surfaced
- **PR mode + local mode** — PR detected → survivors posted as review comments; no PR → terminal report + gitignored `<branch>.adversarial-review.md`
- **Loud adversary-unavailable degradation** — Gemini unauthenticated/parse failure → Claude-only review with `ADVERSARY UNAVAILABLE` banner; never silent
- **Six scripts** — `ensure-gemini.sh`, `detect-mode.sh`, `gemini-review.sh`, `synthesize.py`, `sink.sh`, `run-tests.sh`
- **Guided Gemini setup (Step 0)** — `ensure-gemini.sh` detects missing/unauthenticated Gemini; orchestrator offers install and API-key setup before the pipeline starts
- **gemini-cli v0.44.x envelope extraction** — `gemini-review.sh` recovers `{"verdicts":[...]}` or `{"findings":[...]}` from the `"response"`-nested envelope shape with optional prose prefix lines
- **Headless auth detection** — `ensure-gemini.sh` reports `GEMINI_AUTHED=no` for interactive OAuth credentials that are insufficient for `gemini -p ... -o json` calls
- **Script-level test suite** — `run-tests.sh` covers mode detection, diff extraction, Gemini JSON parse/retry/degradation, and classification partition

### Fixed

- **synthesize.py: KeyError on id-less entries** — `classify_findings` now skips any entry where `"id"` is missing or empty
- **synthesize.py: r1.json dict shape accepted** — accepts both a bare JSON array and a `{"findings": [...]}` envelope for R1 input
- **gemini-review.sh: id-less entries dropped** — post-parse validation filters out verdict entries lacking a non-empty string `"id"`
- **gemini-review.sh: hardcoded /tmp paths replaced with mktemp** — all temp files created with `mktemp` and cleaned via `EXIT` trap
- **detect-mode.sh: large-diff line count off-by-one** — replaced `wc -l` with `grep -c ''` so files lacking a trailing newline are counted correctly
