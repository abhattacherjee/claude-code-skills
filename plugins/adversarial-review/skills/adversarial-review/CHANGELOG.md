# Changelog

All notable changes to this skill will be documented in this file.

## [0.1.0] - 2026-06-02

### Added

- **3-round refutation pipeline** — R1 Claude review → R2 Gemini refute+augment → R3 Claude cross-examine → `synthesize.py` → `sink.sh`
- **Both-confirm survivor rule** — only findings confirmed by both models are survivors; UNCONFIRMED and REJECTED buckets are always surfaced
- **PR mode + local mode** — PR detected → survivors posted as review comments; no PR → terminal report + gitignored `<branch>.adversarial-review.md`
- **Loud adversary-unavailable degradation** — Gemini unauthenticated/parse failure → Claude-only review with `ADVERSARY UNAVAILABLE` banner; never silent
- **Six scripts** — `ensure-gemini.sh`, `detect-mode.sh`, `gemini-review.sh`, `synthesize.py`, `sink.sh`, `run-tests.sh`
- **Guided Gemini setup (Step 0)** — `ensure-gemini.sh` detects missing/unauthenticated Gemini; orchestrator offers install and API-key setup before the pipeline starts
- **gemini-cli v0.44.x envelope extraction** — `gemini-review.sh` recovers `{verdicts, new_findings}` from the `"response"`-nested envelope shape with optional prose prefix lines
- **Headless auth detection** — `ensure-gemini.sh` reports `GEMINI_AUTHED=no` for interactive OAuth credentials that are insufficient for `gemini -p ... -o json` calls
- **Script-level test suite** — `run-tests.sh` covers mode detection, diff extraction, Gemini JSON parse/retry/degradation, and classification partition

### Fixed

- **synthesize.py: KeyError on id-less entries (AR-001)** — `classify_findings` now skips any R1/R2/R3 entry where `"id"` is missing or empty rather than crashing with `KeyError`
- **synthesize.py: r1.json dict shape accepted (AR-002)** — `synthesize.py` now accepts both a bare JSON array and a `{"findings": [...]}` envelope for R1 input, matching the contract documented in SKILL.md
- **gemini-review.sh: id-less entries dropped in R2 producer (AR-001)** — the post-parse validation step now filters out any verdict or new_finding entry that lacks a non-empty string `"id"` before writing to disk
- **gemini-review.sh: hardcoded /tmp paths replaced with mktemp (AR-003)** — `GEMINI_STDERR_FILE` and `VALIDATE_ERR_FILE` are now created with `mktemp` and added to the `EXIT` trap for reliable cleanup
- **detect-mode.sh: large-diff line count off-by-one (AR-004)** — replaced `wc -l` with `grep -c ''` so a file lacking a trailing newline is counted correctly

### Changed

- **detect-mode.sh: exit-code header comment (AR-006)** — removed the non-existent `3=adversary-unavailable` exit code from the header comment; actual exit codes are 0=ok, 1=error, 2=usage/large-diff
- **Fixture IDs renamed to AR-NNN scheme (AR-005)** — `r1_claude_findings.json` IDs updated from `claude-001…005` to `AR-001…005`; cross-references in `r2_gemini_response.json` and `r3_claude_response.json` updated to match
- **Symmetric pipeline** — pipeline is now symmetric: both Claude and Gemini discover findings independently in R1 (blind to each other), then each cross-examines the other's findings in R2; convergence is mechanical via `synthesize.py` with 4 input files; replaces the prior Claude-first/Claude-adjudicates flow. `adversarial-r3-adjudicator` agent replaced by `adversarial-cross-examiner` (judges Gemini's R1 findings in R2, parallel with Gemini judging Claude's).
