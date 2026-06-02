---
name: adversarial-review
description: "Runs a Claude↔Gemini adversarial code review on a PR diff or working-tree diff, surfacing only findings both models independently confirm (high-precision, both-confirm rule). Use when: (1) reviewing a PR or working-tree diff with adversarial rigor and you want fewer false positives, (2) you want only findings two independent AI models agree on rather than a single-model opinion, (3) replacing a lost external PR reviewer (e.g. Copilot) with a second independent model cross-examining Claude's analysis, (4) running a high-precision pre-merge review before shipping to production. Supports automatic PR mode (posts review comments) and local mode (terminal report + gitignored markdown file). Degrades loudly to Claude-only review when Gemini is unavailable."
metadata:
  version: 0.1.0
---

# Adversarial Review

Runs a bounded 3-round Claude↔Gemini cross-examination on a diff. Only findings **both models confirm** (the survivor rule) reach the final report. Single-model findings are retained as `UNCONFIRMED`, never silently dropped.

## Prerequisites

Gemini setup is now **guided automatically** via Step 0 below. When the skill runs, `ensure-gemini.sh` detects whether Gemini is installed and authenticated, then the orchestrator prompts the user to install or authenticate with their consent before proceeding. No manual pre-flight needed; the skill degrades to Claude-only mode only if the user declines or setup fails.

No setup needed for Claude (runs in the current session).

## Quick Start

```bash
# PR mode (auto-detected when branch has an open PR)
/adversarial-review

# Local mode (working-tree diff vs base)
/adversarial-review

# Force large-diff past the size warning
/adversarial-review --force
```

The skill auto-detects mode. Pass `--force` only to override the large-diff warning.

---

## Pipeline Overview

```
detect-mode.sh
     │
     ├── MODE=pr   → diff from PR
     └── MODE=local → diff from working tree vs base

R1: bug-hunter (opus) ╗
    convention-reviewer (sonnet) ╝ ← parallel, same diff
     │ merge → r1.json

R2: gemini-review.sh → r2.json
     │ exit 3? → DEGRADE (Claude-only report, exit 0)

R3: adversarial-r3-adjudicator (opus) → r3.json

synthesize.py → report.md + report.json

sink.sh → PR comments (MODE=pr) | terminal + .md (MODE=local)
```

## Sub-Agent Registry

| Agent | Model | Round | Purpose | Scheduling |
|---|---|---|---|---|
| `adversarial-bug-hunter` | opus | R1 | Find bugs, security, perf, correctness in actual source | Parallel with convention-reviewer |
| `adversarial-convention-reviewer` | sonnet | R1 | Find convention, CLAUDE.md, maintainability issues | Parallel with bug-hunter |
| `adversarial-r3-adjudicator` | opus | R3 | Adjudicate Gemini's R2 verdicts against real source | Sequential (after R2) |

Gemini (R2) runs via `scripts/gemini-review.sh`, not a Claude sub-agent.

---

## Orchestration Workflow

### Step 0 — Ensure the adversary (Gemini) is available

```bash
SCRIPTS="$(dirname "$0")/scripts"
eval "$($SCRIPTS/ensure-gemini.sh --check)"
# Exports: GEMINI_INSTALLED  GEMINI_VERSION  GEMINI_AUTHED
#          INSTALL_HINT       AUTH_HINT
```

Parse the `KEY=VALUE` output and follow this decision tree:

**Case A — `GEMINI_INSTALLED=no`:**
Tell the user Gemini CLI is not installed and show the `INSTALL_HINT`. ASK whether to install it. If the user consents, run:
```bash
npm install -g @google/gemini-cli
```
After install succeeds, re-run `ensure-gemini.sh --check` to re-evaluate auth. If the user declines, or if install fails, proceed in **degraded Claude-only mode** (print the loud banner from the Degradation Behavior section) and continue directly to the detect-mode step.

**Case B — installed but `GEMINI_AUTHED=no`:**
Tell the user Gemini is installed but unauthenticated and show the `AUTH_HINT`. ASK the user to:
- set `GEMINI_API_KEY=<key>` (from [Google AI Studio](https://aistudio.google.com/apikey)), OR
- run `gemini` once in a terminal to complete the interactive Google login.

Once the user confirms they've completed auth (or set the env var in the current shell), re-run `ensure-gemini.sh --check` to confirm `GEMINI_AUTHED=yes`. If they decline, proceed in **degraded Claude-only mode**.

**Case C — `GEMINI_AUTHED=unknown` (installed, auth state indeterminate):**
No user interaction needed. Proceed normally and rely on the runtime guard: `gemini-review.sh` exits 3 (`ADVERSARY_UNAVAILABLE`) if Gemini actually fails, which triggers the same degradation backstop.

**Case D — `GEMINI_INSTALLED=yes` and `GEMINI_AUTHED=yes`:**
Adversary confirmed available. Continue to Step 1 with no user interaction.

> The runtime guard in `gemini-review.sh` (exit 3) remains as the final backstop for transient failures even when Step 0 passes (network errors, expired tokens, etc.).

### Step 1 — Detect Mode

```bash
SCRIPTS="$(dirname "$0")/scripts"
eval "$($SCRIPTS/detect-mode.sh $FORCE_FLAG)"
# Exports: MODE  PR  BASE  DIFF_FILE  FILES_FILE
# Exit 2 = diff too large → stop unless --force was passed
```

Parse the `KEY=VALUE` output. If exit code is 2 and `--force` was not passed, halt and tell the user the diff is too large, offer `--force` to continue.

### Step 2 — R1: Parallel Claude Review

Launch **both agents in a single message** (parallel dispatch). Each receives:
- The absolute path to `DIFF_FILE`
- The absolute path to `FILES_FILE` (list of changed file paths for repo navigation)
- Read access to the repo for full source context

**Bug-hunter returns** a JSON array of findings (see Finding Schema below), `origin="claude"`, categories limited to `bug|security|perf`.

**Convention-reviewer returns** a JSON array of findings, `origin="claude"`, categories limited to `convention|maintainability`.

Merge both arrays into `r1.json`. Set `claude_verdict=null`, `gemini_verdict=null`, `status="unconfirmed"` for every finding at this stage. Assign sequential IDs (`AR-001`, `AR-002`, …).

**r1.json format:**

```json
{
  "findings": [
    {
      "id": "AR-001",
      "path": "src/foo.ts",
      "line": 42,
      "severity": "critical|important|minor",
      "category": "bug|security|perf|convention|maintainability",
      "title": "Short title",
      "rationale": "Why this is a problem, grounded in source",
      "origin": "claude",
      "claude_verdict": null,
      "gemini_verdict": null,
      "status": "unconfirmed",
      "killed_by": null,
      "kill_reason": null
    }
  ]
}
```

### Step 3 — R2: Gemini Cross-Examination

```bash
$SCRIPTS/gemini-review.sh \
  --diff "$DIFF_FILE" \
  --findings r1.json \
  --out r2.json
```

**If exit code is 3** (`ADVERSARY_UNAVAILABLE`): skip R3 and synthesis. Print the degradation banner (see below), emit the R1 findings as the report (all status=`unconfirmed`), and exit 0.

**r2.json format** (returned by script):

```json
{
  "verdicts": [
    {
      "id": "AR-001",
      "gemini_verdict": "confirm|refute",
      "reason": "...",
      "confidence": "high|medium|low"
    }
  ],
  "new_findings": [
    {
      "id": "G-001",
      "path": "src/bar.ts",
      "line": 17,
      "severity": "important",
      "category": "bug",
      "title": "...",
      "rationale": "..."
    }
  ]
}
```

### Step 4 — R3: Claude Adjudicates Gemini's Output

Launch the `adversarial-r3-adjudicator` agent (opus, sequential). Provide:
- `r1.json` (Claude's original findings)
- `r2.json` (Gemini's verdicts + new findings)
- Repo access to read actual source for any finding Gemini introduced

**r3.json format** (returned by agent):

```json
{
  "defends": [
    {
      "id": "AR-001",
      "defends": true
    }
  ],
  "gemini_finding_verdicts": [
    {
      "id": "G-001",
      "claude_verdict": "confirm|refute",
      "reason": "Grounded explanation citing actual source"
    }
  ]
}
```

`defends: true` means Claude stands by the finding despite Gemini's refutation.
`defends: false` means Claude accepts Gemini's kill — finding becomes `rejected`.

### Step 5 — Synthesize

```bash
$SCRIPTS/synthesize.py \
  --r1 r1.json \
  --r2 r2.json \
  --r3 r3.json \
  --md report.md \
  --json report.json
```

Script applies the survivor rule and prints `survivors=N unconfirmed=M rejected=K`.

### Step 6 — Sink

```bash
$SCRIPTS/sink.sh \
  --report-md report.md \
  --report-json report.json \
  --mode "$MODE" \
  [--pr "$PR"] \
  [--branch "$(git branch --show-current)"]
```

---

## Survivor Rule

A finding reaches the **Survivors** section only when BOTH models confirm it:

| Finding origin | Survives when |
|---|---|
| Claude (R1) | Gemini verdict = `confirm` in R2 |
| Gemini new (R2) | Claude verdict = `confirm` in R3 |

All other findings go to **UNCONFIRMED** (single-model). Rejected findings (killed by the opposing model) are listed separately with the kill reason. Nothing is ever silently discarded.

## Degradation Behavior

If `gemini-review.sh` exits with code 3 (unauthenticated, network error, unparseable JSON after one retry), the skill degrades loudly:

```
╔══════════════════════════════════════════════════════════╗
║  ADVERSARY UNAVAILABLE — single-model review only        ║
║  Gemini did not respond. Showing Claude R1 findings.     ║
║  Re-run after: export GEMINI_API_KEY=... or gemini auth  ║
╚══════════════════════════════════════════════════════════╝
```

The R1 Claude findings are reported as-is with status=`unconfirmed`. The skill exits 0 (not an error).

## Same-Diff Invariant

Both Claude agents (R1) and Gemini (R2) receive the **byte-identical** `DIFF_FILE` path produced by `detect-mode.sh`. The orchestrator must not re-generate or alter the diff between steps.

## Output Locations

| Mode | Output |
|---|---|
| `pr` | Review comments posted to the PR via `sink.sh` (uses `pr-review-loop`'s `pr-review-cli.sh` if present) |
| `local` | Terminal report + `<branch>.adversarial-review.md` (gitignored) in repo root |

## See Also

- `scripts/ensure-gemini.sh` — Step 0 detection: emits Gemini install/auth status + install/auth hints; never installs or calls the network
- `scripts/detect-mode.sh` — diff extraction and mode detection
- `scripts/gemini-review.sh` — R2 Gemini cross-examination
- `scripts/synthesize.py` — survivor rule application
- `scripts/sink.sh` — output routing (PR comments or local file)
- `pr-review-loop` plugin — PR comment posting used by sink in PR mode
