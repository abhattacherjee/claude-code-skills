---
name: adversarial-review
description: "Runs a Claude↔Gemini adversarial code review on a PR diff or working-tree diff, surfacing only findings both models independently confirm (high-precision, both-confirm rule). Use when: (1) reviewing a PR or working-tree diff with adversarial rigor and you want fewer false positives, (2) you want only findings two independent AI models agree on rather than a single-model opinion, (3) replacing a lost external PR reviewer (e.g. Copilot) with a second independent model cross-examining Claude's analysis, (4) running a high-precision pre-merge review before shipping to production. Supports automatic PR mode (posts review comments) and local mode (terminal report + gitignored markdown file). Degrades loudly to Claude-only review when Gemini is unavailable."
metadata:
  version: 0.1.0
---

# Adversarial Review

Runs a symmetric 2-round Claude↔Gemini cross-examination on a diff. Both models discover findings independently in R1, then each cross-examines the other's findings in R2. Only findings **the opposing model confirms** reach the final report. Single-model findings are retained as `UNCONFIRMED`, never silently dropped.

## Prerequisites

Gemini setup is **guided automatically** via Step 0 below. When the skill runs, `ensure-gemini.sh` detects whether Gemini is installed and has a **headless-capable credential**, then the orchestrator prompts the user to install or authenticate with their consent before proceeding. No manual pre-flight needed; the skill degrades to Claude-only mode only if the user declines or setup fails.

**Important — interactive Google login is NOT sufficient.** The skill's headless calls (`gemini -p ... -o json -m <model>`) require a `GEMINI_API_KEY` (or Vertex AI credentials). `ensure-gemini.sh` correctly reports `GEMINI_AUTHED=no` when only OAuth credentials are present.

**Recommended credential location:** add `GEMINI_API_KEY=<key>` to `~/.gemini/.env`. The gemini CLI auto-loads this file for all invocations including non-login shells and sub-agent contexts — no shell profile changes needed.

## Quick Start

```bash
# PR mode (auto-detected when branch has an open PR)
/adversarial-review

# Local mode (working-tree diff vs base)
/adversarial-review

# Force large-diff past the size warning
/adversarial-review --force
```

---

## Pipeline Overview

```
detect-mode.sh
     │
     ├── MODE=pr   → diff from PR
     └── MODE=local → diff from working tree vs base

R1 (parallel, blind — neither side sees the other):
  Claude: bug-hunter (opus) + convention-reviewer (sonnet) → r1-claude.json [C-001, C-002, ...]
  Gemini: gemini-review.sh --mode find                     → r1-gemini.json [G-001, G-002, ...]
     │
     │  emit R1 DIGEST
     │
R2 (parallel, symmetric cross-examination):
  Claude: adversarial-cross-examiner (opus)  reads r1-gemini.json → r2-claude-verdicts.json
  Gemini: gemini-review.sh --mode judge      reads r1-claude.json  → r2-gemini-verdicts.json
     │
     │  emit R2 DIGEST
     │
CONVERGE: synthesize.py (4 files) → report.md + report.json

sink.sh → PR comments (MODE=pr) | terminal + .md (MODE=local)
```

## Sub-Agent Registry

| Agent | Model | Round | Purpose | Scheduling |
|---|---|---|---|---|
| `adversarial-bug-hunter` | opus | R1 | Find bugs, security, perf, correctness in actual source | Parallel with convention-reviewer and Gemini find |
| `adversarial-convention-reviewer` | sonnet | R1 | Find convention, CLAUDE.md, maintainability issues | Parallel with bug-hunter and Gemini find |
| `adversarial-cross-examiner` | opus | R2 | Judges Gemini's R1 findings against actual source; returns confirm/refute verdicts | Parallel with Gemini judge |

Gemini (R1 find + R2 judge) runs via `scripts/gemini-review.sh`, not a Claude sub-agent.

---

## Orchestration Workflow

### Context Discipline

All round outputs are written to files in a single `mktemp -d` run directory created at the start of the pipeline. The orchestrator passes **file paths** between sub-agents and reads only counts and digests into the conversation context — never paste full round JSON into the chat. This keeps context windows bounded regardless of finding volume.

```bash
RUN_DIR=$(mktemp -d)
# All round files: $RUN_DIR/r1-claude.json, $RUN_DIR/r1-gemini.json, etc.
```

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
Tell the user Gemini is installed but lacks a headless-capable credential, and show the `AUTH_HINT`. **Emphasise that interactive Google login is NOT sufficient** — the skill's headless calls require an API key. ASK the user to:
- (Recommended) Add `GEMINI_API_KEY=<key>` to `~/.gemini/.env` — auto-loaded for all shells including sub-agents; get a key at [Google AI Studio](https://aistudio.google.com/apikey), OR
- `export GEMINI_API_KEY=<key>` in the current shell session, OR
- Configure Vertex AI: `export GOOGLE_GENAI_USE_VERTEXAI=true && export GOOGLE_CLOUD_PROJECT=<project>`.

**Do NOT suggest** `gemini` interactive login — it produces OAuth credentials insufficient for headless `-p`/`-o json` calls.

Once the user confirms they've set a credential, re-run `ensure-gemini.sh --check` to confirm `GEMINI_AUTHED=yes`. If they decline, proceed in **degraded Claude-only mode**.

**Case C — `GEMINI_AUTHED=unknown`:**
No user interaction needed. Proceed normally; rely on the runtime guard: `gemini-review.sh` exits 3 (`ADVERSARY_UNAVAILABLE`) if Gemini actually fails.

**Case D — `GEMINI_INSTALLED=yes` and `GEMINI_AUTHED=yes`:**
Adversary confirmed available. Continue to Step 1 with no user interaction.

### Step 1 — Detect Mode

```bash
eval "$($SCRIPTS/detect-mode.sh $FORCE_FLAG)"
# Exports: MODE  PR  BASE  DIFF_FILE  FILES_FILE
# Exit 2 = diff too large → stop unless --force was passed
```

Parse the `KEY=VALUE` output. If exit code is 2 and `--force` was not passed, halt and tell the user the diff is too large; offer `--force` to continue.

### Step 2 — R1: Parallel Independent Discovery

Launch all three discovery tasks **in a single message** (parallel dispatch). Neither Claude agent nor Gemini sees the other's output at this stage.

**(a) Claude finders — two agents in parallel:**

Each receives: absolute path to `DIFF_FILE`, absolute path to `FILES_FILE`, and read access to the repo.

- **Bug-hunter** returns `{"findings":[...]}` with `origin="claude"`. Assign sequential ids `BH-001`, `BH-002`, ...
- **Convention-reviewer** returns `{"findings":[...]}` with `origin="claude"`. Assign sequential ids `CR-001`, `CR-002`, ...

Merge both arrays. Renumber with unified prefix: `C-001`, `C-002`, ... Set `claude_verdict=null`, `gemini_verdict=null`, `status="unconfirmed"` on every entry. Write to `$RUN_DIR/r1-claude.json`.

**(b) Gemini finder — run in parallel with Claude agents:**

```bash
$SCRIPTS/gemini-review.sh \
  --diff "$DIFF_FILE" \
  --mode find \
  --out "$RUN_DIR/r1-gemini.json"
```

**If exit code is 3** (`ADVERSARY_UNAVAILABLE`): print the degradation banner (see Degradation Behavior), emit the Claude findings as the report (all `status=unconfirmed`), and exit 0.

Script emits `{"findings":[...]}` with `origin="gemini"`. Renumber ids: `G-001`, `G-002`, ... Write to `$RUN_DIR/r1-gemini.json`.

**r1-claude.json and r1-gemini.json format:**

```json
{
  "findings": [
    {
      "id": "C-001",
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

**Emit R1 DIGEST** (print to conversation after both sides complete):

```
=== R1 Discovery Digest ===
Claude findings: <N> total  (critical=X important=Y minor=Z)
  bug=A  security=B  perf=C  convention=D  maintainability=E
Gemini findings: <M> total  (critical=X important=Y minor=Z)
  (categories if available)
```

### Step 3 — R2: Parallel Symmetric Cross-Examination

Launch both cross-examination tasks **in a single message** (parallel dispatch).

**(a) Claude cross-examines Gemini's findings:**

Launch the `adversarial-cross-examiner` agent (opus). Provide:
- Absolute path to `$RUN_DIR/r1-gemini.json` (Gemini's findings)
- Absolute path to `DIFF_FILE`
- Repo read access

Agent returns `{"verdicts":[{"id":"G-NNN","claude_verdict":"confirm|refute","reason":"..."}]}`. Write to `$RUN_DIR/r2-claude-verdicts.json`.

**(b) Gemini cross-examines Claude's findings:**

```bash
$SCRIPTS/gemini-review.sh \
  --diff "$DIFF_FILE" \
  --findings "$RUN_DIR/r1-claude.json" \
  --mode judge \
  --out "$RUN_DIR/r2-gemini-verdicts.json"
```

**If exit code is 3** (`ADVERSARY_UNAVAILABLE`): print the degradation banner, emit Claude findings as unconfirmed report, exit 0.

Script emits `{"verdicts":[{"id":"C-NNN","gemini_verdict":"confirm|refute","reason":"...","confidence":...}]}`. Written to `$RUN_DIR/r2-gemini-verdicts.json`.

**Emit R2 DIGEST** (print to conversation after both sides complete):

```
=== R2 Cross-Examination Digest ===
Gemini's verdict on Claude's findings (<N> total):
  confirmed=A  refuted=B  judged=J  confirm_rate=R.RRR  low_signal=true|false  unrecognized=U
  [⚠ LOW SIGNAL — near-unanimous verdicts; judge may be rubber-stamping]
  [⚠ UNRECOGNIZED — U verdict(s) had an unrecognized value; judge output may be malformed]
Claude's verdict on Gemini's findings (<M> total):
  confirmed=D  refuted=E  judged=K  confirm_rate=S.RRR  low_signal=true|false  unrecognized=V
  [⚠ LOW SIGNAL — near-unanimous verdicts; judge may be rubber-stamping]
  [⚠ UNRECOGNIZED — V verdict(s) had an unrecognized value; judge output may be malformed]
```

The per-direction fields `confirmed`, `refuted`, `judged`, `confirm_rate`, `low_signal`, and `unrecognized` come verbatim from `synthesize.py` stdout. The orchestrator may derive `unjudged = <total findings> − judged` if it wants to display that count.

The `LOW SIGNAL` banner line is printed only when `synthesize.py` reports `low_signal=true` for that direction (confirm_rate >= 0.950 or <= 0.050 over a sample of >= 5 judged findings). Omit the banner line when `low_signal=false`. The `UNRECOGNIZED` banner is printed only when `unrecognized > 0`.

**Low-signal escalation:** A `low_signal=true` direction means the judge confirmed (or refuted) nearly everything it judged over a meaningful sample, producing little discriminating signal. Before trusting the Survivors list, re-run that direction's judge with maximum skepticism and re-synthesize:

- Gemini rubber-stamping Claude's findings: `$SCRIPTS/gemini-review.sh --diff "$DIFF_FILE" --findings "$RUN_DIR/r1-claude.json" --mode judge --strict --out "$RUN_DIR/r2-gemini-verdicts.json"` (the `--strict` flag forces the hardened judge prompt on the first call, requiring Gemini to quote the exact offending diff line verbatim for every confirm)
- Claude rubber-stamping Gemini's findings: re-spawn the `adversarial-cross-examiner` agent with an explicit instruction for a maximum-skepticism re-judge — refute unless the evidence is unambiguous and cite the proving line

Re-run `synthesize.py` after the escalation pass and relay the updated digest. The `low_signal` flag is informational only — it does not change survivor classification; surviving findings are still those confirmed by the opposing model (see Survivor Rule).

### Step 4 — Converge: Synthesize

```bash
$SCRIPTS/synthesize.py \
  --claude-findings "$RUN_DIR/r1-claude.json" \
  --gemini-findings "$RUN_DIR/r1-gemini.json" \
  --gemini-verdicts "$RUN_DIR/r2-gemini-verdicts.json" \
  --claude-verdicts "$RUN_DIR/r2-claude-verdicts.json" \
  --md "$RUN_DIR/report.md" \
  --json "$RUN_DIR/report.json"
```

Script applies the survivor rule and prints `survivors=N unconfirmed=M rejected=K` to stdout, followed by per-direction lines containing `confirmed=`, `refuted=`, `judged=`, `confirm_rate=`, `low_signal=true|false`, and `unrecognized=`. Read and relay these counts and any `low_signal=true` flags and any `unrecognized > 0` count to the user.

### Step 5 — Sink

```bash
$SCRIPTS/sink.sh \
  --report-md "$RUN_DIR/report.md" \
  --report-json "$RUN_DIR/report.json" \
  --mode "$MODE" \
  [--pr "$PR"] \
  [--branch "$(git branch --show-current)"]
```

---

## Survivor Rule

A finding reaches the **Survivors** section only when the **opposing model** confirms it. Convergence is mechanical — no model adjudicates both sides.

| Finding origin | Survives when |
|---|---|
| Claude finding (C-NNN in r1-claude.json) | Gemini verdict = `confirm` in r2-gemini-verdicts.json |
| Gemini finding (G-NNN in r1-gemini.json) | Claude verdict = `confirm` in r2-claude-verdicts.json |

- **Survivors** — confirmed by the opposing model; both models agree
- **Unconfirmed** — not judged by the opponent, or opponent abstained
- **Rejected** — opponent explicitly refuted; retained with refuter and reason

Nothing is ever silently discarded.

## Degradation Behavior

If `gemini-review.sh` exits with code 3 (unauthenticated, network error, unparseable JSON after one retry) at **either** the R1 find step or the R2 judge step, the skill degrades loudly to Claude-only mode:

```
╔══════════════════════════════════════════════════════════╗
║  ADVERSARY UNAVAILABLE — single-model review only        ║
║  Gemini did not respond. Showing Claude R1 findings.     ║
║  Re-run after: add GEMINI_API_KEY=<key> to              ║
║  ~/.gemini/.env  (interactive login is NOT enough)       ║
╚══════════════════════════════════════════════════════════╝
```

Claude findings are reported as-is with `status=unconfirmed` — they cannot be cross-confirmed without Gemini. The skill exits 0 (not an error).

## Same-Diff Invariant

Both Claude agents (R1) and Gemini (R1 find + R2 judge) receive the **byte-identical** `DIFF_FILE` path produced by `detect-mode.sh`. The orchestrator must not re-generate or alter the diff between steps.

## Output Locations

| Mode | Output |
|---|---|
| `pr` | Review comments posted to the PR via `sink.sh` (uses `pr-review-loop`'s `pr-review-cli.sh` if present) |
| `local` | Terminal report + `<branch>.adversarial-review.md` (gitignored) in repo root |

## See Also

- `scripts/ensure-gemini.sh` — Step 0 detection: emits Gemini install/auth status + hints; never installs or calls the network
- `scripts/detect-mode.sh` — diff extraction and mode detection
- `scripts/gemini-review.sh` — R1 find + R2 judge Gemini calls
- `scripts/synthesize.py` — survivor rule application (4-file symmetric input)
- `scripts/sink.sh` — output routing (PR comments or local file)
- `pr-review-loop` plugin — PR comment posting used by sink in PR mode
