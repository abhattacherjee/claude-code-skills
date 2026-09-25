# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-09-24

### Added

- PR mode saves the whole exchange on the PR: one inline thread per finding (refuted ones too), the opposing model's verdict as a reply, refuted threads resolved at once, and one summary review. Secrets in model output are redacted before posting, and bodies are capped below GitHub's size limit.
- `scripts/pr-audit.py` with `post`, `local` and `record` modes, and `--no-post` on the skill and `sink.sh`.
- `pr-audit.py` exit codes: 0 everything posted, 1 trail incomplete (some posts failed, or it went to the local file), 2 invalid record or report, 3 unexpected crash (the trail may be partial). `sink.sh` maps any non-zero code to 4.
- Codex is the first-choice adversary. `pick-adversary.sh` picks Codex when it is installed and logged in, then Gemini, then Claude-only. `--adversary codex|gemini` forces one; a forced adversary that is not usable stops the run (exit 3) instead of falling back.
- `codex-review.sh --mode find|judge|counter` runs Codex in a locked-down `codex exec`: only `PATH`, `HOME` and your own `CODEX_HOME` in its environment; user config, rules, the reviewed repo's `AGENTS.md`, apps, plugins, hooks and memories off; a read-only sandbox; the diff on a closed stdin pipe; and a timeout that kills the whole process group. Its output is checked against a schema, capped and redacted. Codex finding ids are `X-001…`.
- Isolation is enforced, not assumed: every argv must carry all the isolation flags, and the first review on each Codex version runs a canary repo that tries to steer Codex from all four surfaces it could load — `AGENTS.md`, `.codex/config.toml`, `.agents/skills` and `.mcp.json`. A leak on any of the four stops the run with exit 3. `codex-review.sh --self-test` reruns the canary.
- A pass is stamped in `codex-isolation-<version>-<key>.ok`, keyed on the Codex version, a hash of the isolation recipe, the resolved Codex binary's realpath and sha256, and `CODEX_HOME`; any change reruns the canary, and a missing or unreadable stamp counts as no stamp. For an npm install, the sha256 covers only the JS entry script `codex` points at, so a same-version package swap keeps the stamp.
- `ensure-codex.sh --check` reports `CODEX_INSTALLED`, `CODEX_VERSION` and `CODEX_AUTHED`, from the exit code of `codex login status`.
- `synthesize.py --adversary codex|gemini|claude-only` labels the report with the real adversary. `--adversary-findings` and `--adversary-verdicts` are new names for the Gemini-named flags. `claude-only` is the degraded no-adversary path (pass empty findings/verdicts files) so `pr-audit.py record --adversary claude-only` never trips its adversary/summary mismatch guard.
- `pr-audit.py recheck` turns Codex's re-checks of earlier findings into `recheck` events, so a fixed finding's thread closes when Codex says it is resolved. `recheck` is Codex-only.

### Changed

- The adversary's verdict on a Claude finding is now `adversary_verdict` (it was `gemini_verdict`) in every file the skill writes. Old run files and report files with `gemini_verdict` still load.

### Fixed

- PR mode never posted anything. `sink.sh` called `pr-review-cli.sh --pr …`, which that CLI rejects as an unknown subcommand, then printed "PR review comments posted" anyway. `sink.sh` now exits 4 when any audit comment fails.
- A gh response that could not be parsed (bad JSON or the wrong shape) crashed `pr-audit.py` and lost the failures already collected. It is now a failed post: the run carries on, lists it, and exits 1.
- When `gh` is not usable, `pr-audit.py` now says why: not installed, not logged in, no login returned, or gh's own error text (for example a network error). An empty login counts as not ready.
- `sink.sh` added the `.gitignore` pattern onto the last line when the file had no final newline (for example `node_modules*.adversarial-review.md`). It now adds a newline first. A pattern on a CRLF line counts as present. A `.gitignore` that cannot be written is a warning, not an abort.
- The crash message (exit 3) in `pr-audit.py` and `sink.sh` said no audit trail was saved. Some posts may already be on the PR, so it now says the trail may be partial.
- A thread opener without `subject_type` is treated as file-level when it has no line, so the summary still notes the lost line anchor.

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
