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
- **Six scripts** — `ensure-gemini.sh` (Step 0: guided Gemini install/auth detection; never installs or calls the network — orchestrator acts on its `KEY=VALUE` output with user consent), `detect-mode.sh`, `gemini-review.sh` (with JSON extraction + one retry), `synthesize.py` (SURVIVORS / UNCONFIRMED / REJECTED classifier), `sink.sh` (dual-mode delivery), `run-tests.sh`
- **Guided Gemini setup (Step 0)** — skill now proactively detects missing/unauthenticated Gemini at run-time via `ensure-gemini.sh`; orchestrator offers to install (`npm install -g @google/gemini-cli`) and prompts for API key or Google login before the pipeline starts; degrades to Claude-only mode only if user declines or setup fails
- **Script-level tests with fixtures** — cover mode detection, diff extraction, Gemini JSON parse/retry/degradation, and classification partition under the both-confirm rule; all tests passing
- **R2 extractor handles gemini-cli v0.44.x `.response`-nested envelope + prose prefixes** — `gemini-review.sh` now recovers the model's `{verdicts, new_findings}` payload from the v0.44.x envelope shape where the outer JSON has a `"response"` string field containing the model's actual answer, optionally preceded by prose warning lines (e.g. `Ripgrep is not available.`); falls back to the prior direct/wrapped-JSON extraction path for older gemini-cli versions
- **`ensure-gemini.sh` reports headless readiness correctly** — `GEMINI_AUTHED` now reflects whether a headless-capable credential (API key, `~/.gemini/.env` key, or Vertex AI) is present; interactive Google OAuth login (`google_accounts.json`, `oauth_creds.json`) no longer reported as `yes` since those credentials are insufficient for `gemini -p ... -o json` calls (which exit 41 without an API key)

### Changed

- **Symmetric pipeline** — pipeline is now symmetric: both Claude and Gemini discover findings independently in R1 (blind to each other), then each cross-examines the other's findings in R2 in parallel; convergence is mechanical via `synthesize.py` with 4 input files (claude-findings, gemini-findings, gemini-verdicts, claude-verdicts); replaces the prior Claude-first / Claude-adjudicates flow. `adversarial-r3-adjudicator` agent renamed and rewritten as `adversarial-cross-examiner`, which now judges Gemini's R1 findings (not Claude's own) in the R2 cross-exam round.
