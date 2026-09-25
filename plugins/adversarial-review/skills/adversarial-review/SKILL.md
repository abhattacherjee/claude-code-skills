---
name: adversarial-review
description: "Runs an adversarial code review of a PR diff or working-tree diff between Claude and an opposing model (Codex when installed and logged in, else Gemini), surfacing only findings both models independently confirm (high-precision, both-confirm rule). Use when: (1) reviewing a PR or working-tree diff with adversarial rigor and you want fewer false positives, (2) you want only findings two independent AI models agree on rather than a single-model opinion, (3) replacing a lost external PR reviewer (e.g. Copilot) with a second independent model cross-examining Claude's analysis, (4) running a high-precision pre-merge review before shipping to production. Supports automatic PR mode (saves the exchange as PR threads) and local mode (terminal report + gitignored markdown file). Degrades loudly to Claude-only review when no adversary is available."
metadata:
  version: 0.2.0
---

# Adversarial Review

Runs a symmetric 2-round cross-examination on a diff between Claude and an opposing model, the adversary: Codex, else Gemini. Both sides discover findings independently in R1, then each cross-examines the other's findings in R2. Only findings **the opposing model confirms** reach the final report. Single-model findings are retained as `UNCONFIRMED`, never silently dropped.

## Prerequisites

Step 0 picks the adversary: **Codex** when the Codex CLI is installed and logged in (`codex login status` exits 0), else **Gemini** when it has a headless credential, else **Claude-only** with a loud banner. `--adversary codex|gemini` forces one. A forced adversary that is not usable stops the run instead of falling back.

**Gemini: interactive Google login is NOT sufficient.** The skill's headless calls (`gemini -p ... -o json -m <model>`) need a `GEMINI_API_KEY` (or Vertex AI credentials). `ensure-gemini.sh` reports `GEMINI_AUTHED=no` when only OAuth credentials are present. Recommended: add `GEMINI_API_KEY=<key>` to `~/.gemini/.env`, which the gemini CLI loads in every shell, sub-agents included.

### Codex sandbox

`codex-review.sh` never runs `codex` with your normal setup. Each call is one `codex exec` with:

- an environment holding only `PATH`, `HOME` and your own `CODEX_HOME` (as set, else Codex's default `~/.codex`), so your login works and nothing else from your shell leaks in;
- `--ephemeral --ignore-user-config --ignore-rules`, so your `config.toml` and rules are not loaded, and `--disable` for `apps`, `plugins`, `remote_plugin`, `memories`, `multi_agent`, `image_generation`, `view_image`, `hooks`, `skill_search`, `skill_mcp_dependency_install`, `browser_use`, `browser_use_external` and `computer_use`. Turning off `apps` removes the ChatGPT connector tools (Gmail send, GitHub merge and others) that run outside the sandbox. The `hooks` feature is disabled, so your own Codex hooks do not run during a review;
- `-c project_doc_max_bytes=0` and `-c project_doc_fallback_filenames=[]`, so the reviewed repo's `AGENTS.md` cannot instruct Codex; `-c skills.include_instructions=false`, so its `.agents/skills` cannot either — that setting defaults to true, so a repo's own skill instructions would otherwise land in the prompt. A repo's `.codex/config.toml` applies only to trusted repos, and trust lives in the `config.toml` that is ignored;
- `-s read-only`, the diff and findings on a stdin pipe that is closed after writing, and a timeout (default 900 s, `CODEX_REVIEW_TIMEOUT`) that kills Codex's whole process group.

Two checks enforce this, and both stop the run with exit 3. Every argv is checked for all of the flags above just before Codex starts. And the first review on each Codex version runs an isolation canary: a throwaway repo whose `AGENTS.md`, `.codex/config.toml`, `.agents/skills` and `.mcp.json` each carry a canary instruction or marker. If any of the four reaches Codex, the review does not run. `codex-review.sh --self-test` reruns the canary on demand.

Live testing on codex-cli 0.155.1 proved two of the four canary surfaces leak without their override — each caught by a positive control that failed before the fix existed: `AGENTS.md` (fixed by `project_doc_max_bytes=0` / `project_doc_fallback_filenames=[]`) and `.agents/skills` (fixed by `skills.include_instructions=false`). The other two are not exercised the same way by that version: it does not read `.mcp.json` at all, and it loads a repo's `.codex/config.toml` only for a trusted repo — trust lives in the user's own `config.toml`, which `--ignore-user-config` already drops. Both stay canaried anyway, as cheap guards against a future Codex version that changes either.

A pass is stamped in `$XDG_CACHE_HOME/adversarial-review/codex-isolation-<version>-<key>.ok` (falling back to `~/.cache/adversarial-review/` when `XDG_CACHE_HOME` is unset), one file per Codex version. The key is a short hash of: the Codex version, the isolation recipe (the required argv flags, the disabled features, the four canary surfaces above, and a `CANARY_SCHEMA` constant bumped whenever the canary itself changes), the resolved Codex binary's realpath and sha256, and `CODEX_HOME` (empty when unset). Any change to any of these — a Codex upgrade, an edited recipe, a different binary, a different `CODEX_HOME` — makes the old stamp not match, so the canary reruns. A missing, unreadable or corrupt stamp counts the same as no stamp. For an npm install, the sha256 covers only the resolved JS entry script `codex` points at, not every file `npm install` laid down — a same-version package swap that replaces other files keeps the stamp valid. The stamp hashes the file `command -v codex` resolves to (its realpath): if that is a wrapper script, a same-version binary swap behind the wrapper keeps the stamp valid too.

What you accept by using it: the read-only sandbox still lets Codex read any file your user can read, not only the repo. Review needs Codex's shell tool to read the repo, so this stays. Codex cannot run tests that write temp files, so a Codex claim that tests pass covers pure tests only. Codex output is untrusted: it is checked against a schema, capped (50 findings, 4000 characters per text), and redacted before anything reaches the PR.

## Quick Start

```bash
# PR mode (auto-detected when branch has an open PR)
/adversarial-review

# Local mode (working-tree diff vs base)
/adversarial-review

# Force large-diff past the size warning
/adversarial-review --force

# Review without posting anything to the PR (report + local file only)
/adversarial-review --no-post

# Force the adversary (a forced adversary that is not usable stops the run)
/adversarial-review --adversary codex
```

---

## Pipeline Overview

```
detect-mode.sh
     │
     ├── MODE=pr   → diff from PR
     └── MODE=local → diff from working tree vs base

R1 (parallel, blind — neither side sees the other):
  Claude:    bug-hunter (opus) + convention-reviewer (sonnet) → r1-claude.json [C-001, ...]
  Adversary: $ADV_REVIEW --mode find                          → r1-<adversary>.json [X-001 Codex | G-001 Gemini]
     │
     │  emit R1 DIGEST
     │
R2 (parallel, symmetric cross-examination):
  Claude:    adversarial-cross-examiner (opus) reads r1-<adversary>.json → r2-claude-verdicts.json
  Adversary: $ADV_REVIEW --mode judge           reads r1-claude.json      → r2-<adversary>-verdicts.json
     │
     │  emit R2 DIGEST
     │
CONVERGE: synthesize.py --adversary <adversary> (4 files) → report.md + report.json

sink.sh → PR audit trail (MODE=pr) | terminal + .md (MODE=local)
```

## Sub-Agent Registry

| Agent | Model | Round | Purpose | Scheduling |
|---|---|---|---|---|
| `adversarial-bug-hunter` | opus | R1 | Find bugs, security, perf, correctness in actual source | Parallel with convention-reviewer and the adversary's find |
| `adversarial-convention-reviewer` | sonnet | R1 | Find convention, CLAUDE.md, maintainability issues | Parallel with bug-hunter and the adversary's find |
| `adversarial-cross-examiner` | opus | R2 | Judges the adversary's R1 findings against actual source; returns confirm/refute verdicts | Parallel with the adversary's judge |

The adversary (R1 find + R2 judge) runs via `scripts/codex-review.sh` or `scripts/gemini-review.sh`, not a Claude sub-agent.

---

## Orchestration Workflow

### Context Discipline

All round outputs are written to files in a single `mktemp -d` run directory created at the start of the pipeline. The orchestrator passes **file paths** between sub-agents and reads only counts and digests into the conversation context — never paste full round JSON into the chat. This keeps context windows bounded regardless of finding volume.

```bash
RUN_DIR=$(mktemp -d)
# All round files: $RUN_DIR/r1-claude.json, $RUN_DIR/r1-gemini.json, etc.
```

### Step 0 — Pick the adversary

The adversary is the opposing model: Codex first, then Gemini, then Claude-only.

```bash
SCRIPTS="$(dirname "$0")/scripts"
unset ADVERSARY
PICK="$($SCRIPTS/pick-adversary.sh ${ADVERSARY_FLAG:+--adversary "$ADVERSARY_FLAG"})"
PICK_RC=$?
eval "$PICK"
# Exports: ADVERSARY (codex | gemini | claude-only)  ADVERSARY_REASON
#          CODEX_INSTALLED  CODEX_VERSION  CODEX_AUTHED  CODEX_INSTALL_HINT  CODEX_AUTH_HINT
#          GEMINI_INSTALLED GEMINI_VERSION GEMINI_AUTHED INSTALL_HINT        AUTH_HINT
```

`eval "$(cmd)"` alone returns eval's own status, not the command's — so the exit code must be captured from `$PICK` before `eval` runs, or the "Exit 3" branch below can never be seen and `$ADVERSARY` stays unset. `ADVERSARY_FLAG` holds the value of `--adversary codex|gemini` when the user passed it. Tell the user `ADVERSARY_REASON` in one line.

- **`ADVERSARY=codex`:** set `ADV_REVIEW="$SCRIPTS/codex-review.sh"`. No questions.
- **`ADVERSARY=gemini`:** set `ADV_REVIEW="$SCRIPTS/gemini-review.sh"`. No questions.
- **`ADVERSARY=claude-only`:** no adversary is usable. Show the Codex hint (`CODEX_INSTALL_HINT` or `CODEX_AUTH_HINT`) and the Gemini hint (`INSTALL_HINT` or `AUTH_HINT`), and ASK the user to choose: set up Codex, set up Gemini, or go on Claude-only. After any setup, run `pick-adversary.sh` again. If they decline, go on in **degraded Claude-only mode** and print the banner from Degradation Behavior.
- **`PICK_RC` is 3:** the user forced an adversary that is not usable. Show the `ADVERSARY_UNAVAILABLE` line from stderr and stop. Do not fall back; the user asked for that model.

**Setting up Codex:** with the user's consent, install it with `CODEX_INSTALL_HINT`. The user then runs `codex login` themselves.

**Setting up Gemini:** with the user's consent, install it with `npm install -g @google/gemini-cli`. Headless calls need an API key: add `GEMINI_API_KEY=<key>` to `~/.gemini/.env` (recommended; get a key at [Google AI Studio](https://aistudio.google.com/apikey)), or `export GEMINI_API_KEY=<key>`, or set `GOOGLE_GENAI_USE_VERTEXAI=true` and `GOOGLE_CLOUD_PROJECT=<project>`. **Do NOT suggest** `gemini` interactive login — it produces OAuth credentials insufficient for headless `-p`/`-o json` calls.

### Step 1 — Detect Mode

```bash
eval "$($SCRIPTS/detect-mode.sh $FORCE_FLAG)"
# Exports: MODE  PR  BASE  DIFF_FILE  FILES_FILE
# Exit 2 = diff too large → stop unless --force was passed
```

Parse the `KEY=VALUE` output. If exit code is 2 and `--force` was not passed, halt and tell the user the diff is too large; offer `--force` to continue.

### Step 2 — R1: Parallel Independent Discovery

Launch all three discovery tasks **in a single message** (parallel dispatch). Neither Claude agent nor the adversary sees the other's output at this stage.

**(a) Claude finders — two agents in parallel:**

Each receives: absolute path to `DIFF_FILE`, absolute path to `FILES_FILE`, and read access to the repo.

- **Bug-hunter** returns `{"findings":[...]}` with `origin="claude"`. Assign sequential ids `BH-001`, `BH-002`, ...
- **Convention-reviewer** returns `{"findings":[...]}` with `origin="claude"`. Assign sequential ids `CR-001`, `CR-002`, ...

Merge both arrays. Renumber with unified prefix: `C-001`, `C-002`, ... Set `claude_verdict=null`, `adversary_verdict=null`, `status="unconfirmed"` on every entry. Write to `$RUN_DIR/r1-claude.json`.

**(b) Adversary finder — run in parallel with Claude agents:**

```bash
$ADV_REVIEW \
  --diff "$DIFF_FILE" \
  --mode find \
  --out "$RUN_DIR/r1-$ADVERSARY.json"
```

**If exit code is 3** (`ADVERSARY_UNAVAILABLE`): when Codex was picked automatically (no `--adversary`) and `GEMINI_AUTHED=yes`, switch to Gemini for the whole run (`ADVERSARY=gemini`, `ADV_REVIEW="$SCRIPTS/gemini-review.sh"`), tell the user, and rerun this step once. Otherwise go to the degraded no-adversary path in Degradation Behavior.

Codex findings arrive numbered `X-001`, `X-002`, ... with `origin="codex"`. Gemini findings arrive with `origin="gemini"`; renumber them `G-001`, `G-002`, ... The file is `$RUN_DIR/r1-$ADVERSARY.json`.

**r1-claude.json and r1-<adversary>.json format:**

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
      "adversary_verdict": null,
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
Adversary (<adversary>) findings: <M> total  (critical=X important=Y minor=Z)
  (categories if available)
```

### Step 3 — R2: Parallel Symmetric Cross-Examination

Launch both cross-examination tasks **in a single message** (parallel dispatch).

**(a) Claude cross-examines the adversary's findings:**

Launch the `adversarial-cross-examiner` agent (opus). Provide:
- Absolute path to `$RUN_DIR/r1-$ADVERSARY.json` (the adversary's findings)
- Absolute path to `DIFF_FILE`
- Repo read access

Agent returns `{"verdicts":[{"id":"X-NNN or G-NNN","claude_verdict":"confirm|refute","reason":"..."}]}`. Write to `$RUN_DIR/r2-claude-verdicts.json`.

**(b) The adversary cross-examines Claude's findings:**

```bash
$ADV_REVIEW \
  --diff "$DIFF_FILE" \
  --findings "$RUN_DIR/r1-claude.json" \
  --mode judge \
  --out "$RUN_DIR/r2-$ADVERSARY-verdicts.json"
```

**If exit code is 3** (`ADVERSARY_UNAVAILABLE`): go to the degraded no-adversary path in Degradation Behavior. The Codex-to-Gemini auto-switch in Step 2(b) is R1-only — by R2 the run is already committed to whichever adversary found in R1, so there is no switch here.

Both scripts emit `{"verdicts":[{"id":"C-NNN","adversary_verdict":"confirm|refute","reason":"...","confidence":...}]}`. The key is `adversary_verdict` for both models; it was `gemini_verdict` before #135, and old run files still load.

**Emit R2 DIGEST** (print to conversation after both sides complete):

```
=== R2 Cross-Examination Digest ===
<Adversary>'s verdict on Claude's findings (<N> total):
  confirmed=A  refuted=B  judged=J  confirm_rate=R.RRR  low_signal=true|false  unrecognized=U
  [⚠ LOW SIGNAL — near-unanimous verdicts; judge may be rubber-stamping]
  [⚠ UNRECOGNIZED — U verdict(s) had an unrecognized value; judge output may be malformed]
Claude's verdict on <Adversary>'s findings (<M> total):
  confirmed=D  refuted=E  judged=K  confirm_rate=S.RRR  low_signal=true|false  unrecognized=V
  [⚠ LOW SIGNAL — near-unanimous verdicts; judge may be rubber-stamping]
  [⚠ UNRECOGNIZED — V verdict(s) had an unrecognized value; judge output may be malformed]
```

The per-direction fields `confirmed`, `refuted`, `judged`, `confirm_rate`, `low_signal`, and `unrecognized` come verbatim from `synthesize.py` stdout. The orchestrator may derive `unjudged = <total findings> − judged` if it wants to display that count. The direction lines are named `<adversary>_on_claude:` and `claude_on_<adversary>:` (for example `codex_on_claude:`).

The `LOW SIGNAL` banner line is printed only when `synthesize.py` reports `low_signal=true` for that direction (confirm_rate >= 0.950 or <= 0.050 over a sample of >= 5 judged findings). Omit the banner line when `low_signal=false`. The `UNRECOGNIZED` banner is printed only when `unrecognized > 0`.

**Low-signal escalation:** A `low_signal=true` direction means the judge confirmed (or refuted) nearly everything it judged over a meaningful sample, producing little discriminating signal. Before trusting the Survivors list, re-run that direction's judge with maximum skepticism and re-synthesize:

- The adversary rubber-stamping Claude's findings: `$ADV_REVIEW --diff "$DIFF_FILE" --findings "$RUN_DIR/r1-claude.json" --mode judge --strict --out "$RUN_DIR/r2-$ADVERSARY-verdicts.json"` (`--strict` forces the hardened judge prompt on the first call)
- Claude rubber-stamping the adversary's findings: re-spawn the `adversarial-cross-examiner` agent with an explicit instruction for a maximum-skepticism re-judge — refute unless the evidence is unambiguous and cite the proving line

Re-run `synthesize.py` after the escalation pass and relay the updated digest. The `low_signal` flag is informational only — it does not change survivor classification; surviving findings are still those confirmed by the opposing model (see Survivor Rule).

### Step 4 — Converge: Synthesize

```bash
$SCRIPTS/synthesize.py \
  --adversary "$ADVERSARY" \
  --claude-findings "$RUN_DIR/r1-claude.json" \
  --adversary-findings "$RUN_DIR/r1-$ADVERSARY.json" \
  --adversary-verdicts "$RUN_DIR/r2-$ADVERSARY-verdicts.json" \
  --claude-verdicts "$RUN_DIR/r2-claude-verdicts.json" \
  --md "$RUN_DIR/report.md" \
  --json "$RUN_DIR/report.json"
```

Script applies the survivor rule and prints `survivors=N unconfirmed=M rejected=K` to stdout, followed by per-direction lines containing `confirmed=`, `refuted=`, `judged=`, `confirm_rate=`, `low_signal=true|false`, and `unrecognized=`. Read and relay these counts and any `low_signal=true` flags and any `unrecognized > 0` count to the user.

When `ADVERSARY="claude-only"` (Degradation Behavior fired), there is no second model to feed Step 4 real findings from. Run the same command with `--adversary claude-only`, and write `{"findings":[]}` once to `$RUN_DIR/r1-empty.json` for `--adversary-findings`, and `{"verdicts":[]}` once to `$RUN_DIR/r2-empty.json` for both `--adversary-verdicts` and `--claude-verdicts` (R2 never ran). Every Claude finding comes out `status=unconfirmed`; nothing is silently dropped, and `report.json`'s `summary.adversary` is `"claude-only"` — matching what Step 4b passes to `pr-audit.py record --adversary "$ADVERSARY"`, so its adversary/summary mismatch guard does not fire.

### Step 4b — Write the round record

The round record is what `sink.sh` posts to the PR: every finding, and the opposing model's verdict with its reason. Build it from `report.json`, never by hand.

```bash
RUN_ID="ar-$(date +%Y%m%d-%H%M%S)-$$"
if [[ "$MODE" == "pr" ]]; then
  HEAD_SHA="$(gh pr view "$PR" --json headRefOid -q .headRefOid)"
else
  HEAD_SHA="$(git rev-parse HEAD)"
fi
# ADVERSARY was set in Step 0 ("codex" or "gemini"), or to "claude-only" on any degraded-mode fallback.
$SCRIPTS/pr-audit.py record \
  --report-json "$RUN_DIR/report.json" \
  --run-id "$RUN_ID" --skill adversarial-review --phase review --round 1 \
  --adversary "$ADVERSARY" --head-sha "$HEAD_SHA" \
  --out "$RUN_DIR/round-1.json"
```

Exit 2 means `report.json` could not be read or did not make a valid record. Tell the user and run Step 5 with `--no-post` and without `--record`.

### Step 5 — Sink

```bash
$SCRIPTS/sink.sh \
  --report-md "$RUN_DIR/report.md" \
  --report-json "$RUN_DIR/report.json" \
  --mode "$MODE" \
  --record "$RUN_DIR/round-1.json" \
  [--pr "$PR"] \
  [--branch "$(git branch --show-current)"] \
  [--no-post]
```

Pass `--no-post` when the user asked for it. Relay `sink.sh`'s `pr-audit:` line to the user.

Model text is posted as written under your GitHub account, so @mentions and #refs in it will notify people and link issues.

- Exit 0: posted. In pr mode, each finding with a path has a thread on the PR. The opposing model's verdict is a reply in it. Refuted findings' threads are resolved. One summary review lists every finding; it is split into numbered parts if very long. Findings without a path, or that GitHub rejected twice, appear only in the summary.
- Exit 4: the report was delivered, but the audit trail is incomplete or went to the local file. See the `pr-audit:` lines and tell the user. Rerunning Step 5 with the same record posts only what is missing and updates the summary.
- Exit 1 or 2: `sink.sh` itself failed. Show the error.

The run directory (`$RUN_DIR`) keeps `round-1.json`. Give the user its path.

---

## Survivor Rule

A finding reaches the **Survivors** section only when the **opposing model** confirms it. Convergence is mechanical — no model adjudicates both sides.

| Finding origin | Survives when |
|---|---|
| Claude finding (C-NNN in r1-claude.json) | The adversary's verdict = `confirm` in r2-<adversary>-verdicts.json |
| Adversary finding (X-NNN Codex or G-NNN Gemini, in r1-<adversary>.json) | Claude verdict = `confirm` in r2-claude-verdicts.json |

- **Survivors** — confirmed by the opposing model; both models agree
- **Unconfirmed** — not judged by the opponent, or opponent abstained
- **Rejected** — opponent explicitly refuted; retained with refuter and reason

Nothing is ever silently discarded.

## Degradation Behavior

If the adversary's script (`codex-review.sh` or `gemini-review.sh`) exits 3 (not installed, not logged in, no credential, a network error, a timeout, or no valid JSON after one retry) at **either** the R1 find step or the R2 judge step, the skill degrades loudly to Claude-only mode, after the one Codex-to-Gemini switch allowed in Step 2:

```
╔══════════════════════════════════════════════════════════╗
║  ADVERSARY UNAVAILABLE — single-model review only        ║
║  The adversary (Codex or Gemini) did not respond.        ║
║  Showing Claude R1 findings.                              ║
║  Re-run after: codex login, or add GEMINI_API_KEY=<key>  ║
║  to ~/.gemini/.env (interactive login is NOT enough)      ║
╚══════════════════════════════════════════════════════════╝
```

Set `ADVERSARY="claude-only"`, then continue straight to Step 4 (there is nothing for R2 to cross-examine if it has not already run). Claude findings are reported as-is with `status=unconfirmed` — they cannot be cross-confirmed without an adversary. The skill exits 0 (not an error). See Step 4 for the empty-file `--adversary claude-only` call that keeps `report.json` and every downstream record labeled consistently.

## Same-Diff Invariant

Both Claude agents (R1) and the adversary (R1 find + R2 judge) receive the **byte-identical** `DIFF_FILE` path produced by `detect-mode.sh`. The orchestrator must not re-generate or alter the diff between steps.

## Output Locations

| Mode | Output |
|---|---|
| `pr` | Terminal report; one PR thread per finding with the verdict as a reply, and one summary review, via `pr-audit.py` (falls back to the local file when `gh` is unavailable) |
| `local` | Terminal report + `<branch>.adversarial-review.md` (gitignored) in repo root |

## See Also

- `scripts/ensure-gemini.sh` — Step 0 detection: emits Gemini install/auth status + hints; never installs or calls the network
- `scripts/ensure-codex.sh` — Step 0 detection for Codex: installed, version, and logged in (from the exit code of `codex login status`)
- `scripts/pick-adversary.sh` — Step 0: picks Codex, then Gemini, then Claude-only; `--adversary` forces one, with no fallback
- `scripts/codex-review.sh` — Codex's R1 find and R2 judge, plus `counter` and `find --prior` re-checks for deep-review, through a locked-down `codex exec` (see Codex sandbox); `--self-test` reruns the isolation canary
- `scripts/detect-mode.sh` — diff extraction and mode detection
- `scripts/gemini-review.sh` — R1 find + R2 judge Gemini calls
- `scripts/synthesize.py` — survivor rule application (4-file symmetric input)
- `scripts/sink.sh` — output routing: terminal + local file, and the PR audit trail via `pr-audit.py`
- `scripts/pr-audit.py` — posts a round record to the PR (`post`), writes it locally (`local`), builds it from `report.json` (`record`), or builds a re-check round from Codex's re-checks (`recheck`)
