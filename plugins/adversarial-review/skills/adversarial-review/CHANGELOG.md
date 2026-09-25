# Changelog

All notable changes to this skill will be documented in this file.

## [0.2.0] - 2026-09-24

### Added

- PR mode saves the whole exchange on the PR: one inline thread per finding (refuted ones too), the opposing model's verdict as a reply, refuted threads resolved at once, and one summary review. Secrets in model output are redacted before posting, and bodies are capped below GitHub's size limit.
- `scripts/pr-audit.py` with `post`, `local` and `record` modes, and `--no-post` on the skill and `sink.sh`.
- `pr-audit.py` exit codes: 0 everything posted, 1 trail incomplete (some posts failed, or it went to the local file), 2 invalid record or report, 3 unexpected crash (the trail may be partial). `sink.sh` maps any non-zero code to 4.

### Fixed

- PR mode never posted anything. `sink.sh` called `pr-review-cli.sh --pr …`, which that CLI rejects as an unknown subcommand, then printed "PR review comments posted" anyway. `sink.sh` now exits 4 when any audit comment fails.
- A gh response that could not be parsed (bad JSON or the wrong shape) crashed `pr-audit.py` and lost the failures already collected. It is now a failed post: the run carries on, lists it, and exits 1.
- When `gh` is not usable, `pr-audit.py` now says why: not installed, not logged in, no login returned, or gh's own error text (for example a network error). An empty login counts as not ready.
- `sink.sh` added the `.gitignore` pattern onto the last line when the file had no final newline (for example `node_modules*.adversarial-review.md`). It now adds a newline first. A pattern on a CRLF line counts as present. A `.gitignore` that cannot be written is a warning, not an abort.
- The crash message (exit 3) in `pr-audit.py` and `sink.sh` said no audit trail was saved. Some posts may already be on the PR, so it now says the trail may be partial.
- A thread opener without `subject_type` is treated as file-level when it has no line, so the summary still notes the lost line anchor.

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
