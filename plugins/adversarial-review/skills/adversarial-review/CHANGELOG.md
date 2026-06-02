# Changelog

All notable changes to this skill will be documented in this file.

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
