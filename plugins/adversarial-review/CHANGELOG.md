# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-06-02

### Added

- **`adversarial-review` skill** — main entry point; auto-detects PR vs local (working-tree) mode and drives the full 3-round refutation pipeline
- **3-round refutation loop** — R1 Claude review → R2 Gemini refute+augment → R3 Claude refute → synthesize → sink; bounded to exactly 3 rounds with no unbounded looping
- **Both-confirm survivor rule** — only findings confirmed by both models survive; UNCONFIRMED (single-model) and REJECTED (with killer model + reason) buckets are always surfaced, never silently dropped
- **PR mode** — auto-detected when a PR exists for the current branch; survivors posted as PR review comments via `pr-review-loop`'s `pr-review-cli.sh`
- **Local mode** — no PR detected; terminal report + gitignored `<branch>.adversarial-review.md` written to working tree
- **Loud adversary-unavailable degradation** — Gemini unauthenticated / parse failure after one retry → Claude-only review with `ADVERSARY UNAVAILABLE — single-model review only` banner; exit 0
- **Three sub-agents** — `adversarial-bug-hunter` (Opus, R1 bug-hunt), `adversarial-convention-reviewer` (Sonnet, R1 convention scan), `adversarial-r3-adjudicator` (Opus, R3 cross-examination against actual source files)
- **Five scripts** — `detect-mode.sh`, `gemini-review.sh` (with JSON extraction + one retry), `synthesize.py` (SURVIVORS / UNCONFIRMED / REJECTED classifier), `sink.sh` (dual-mode delivery), `run-tests.sh`
- **Script-level tests with fixtures** — cover mode detection, diff extraction, Gemini JSON parse/retry/degradation, and classification partition under the both-confirm rule; all tests passing
