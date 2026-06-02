# Adversarial PR Review (Claude ↔ Gemini refutation loop)

**Date:** 2026-06-01
**Status:** Approved design → ready for implementation plan
**Target:** new user-level skill `~/.claude/skills/adversarial-review/`; spec + plan + skill code developed in the `adversarial-review-skill` repo (this repo); runtime install to `~/.claude/skills/adversarial-review/`
**Context:** Copilot is no longer available as the PR reviewer that powered `pr-review-loop` Workflow A. This replaces that reviewer with a second, non-Claude model used adversarially.

---

## 1. Goal

Provide a local, on-demand code review in which **Claude and Gemini cross-examine each other's findings** on a diff, surfacing only the issues that *both* models confirm. The output is a high-precision findings report, posted to a PR when one exists or printed to the terminal otherwise.

## 2. Non-goals

- Not a CI/GitHub-Action reviewer (rejected approach C) and not a GitHub review bot (rejected approach B).
- Not a replacement for `/code-review`'s breadth — this is a precision-focused adversarial pass.
- Does not modify the OpenClaw runtime (`~/.openclaw/`); it is a Claude Code tool only.
- Does not auto-fix code. It reports; resolution is handed to `pr-review-loop` Workflow B (PR mode) or done manually (local mode).

## 3. Background

Current PR-review surface:

- **`pr-review-loop`** (v1.1.0, user-level) — Workflow A polled the Copilot bot and triaged its comments; Workflow B triages human/bot comments. Workflow A is now without an engine.
- **`/code-review`** built-in — all-Claude (Haiku/Sonnet/Opus); no external model.
- **CI (`ci.yml`)** — secret-scan / changelog / markdownlint only; no review automation.

Available second models on the machine: `gemini` CLI (v0.38.2, installed, **currently unauthenticated**), `OPENAI_API_KEY` set, `ollama`, DeepSeek provider. **Gemini** chosen as the adversary — strong reviewer, genuinely different model family from Claude, already installed.

Gemini CLI headless contract (verified): `gemini -p "<prompt>" -o json` runs non-interactively; `-m` selects the model; stdin is appended to the prompt. Auth is **not** configured yet (`GEMINI_API_KEY` / Google login / Vertex required) — a one-time prerequisite.

## 4. Design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **New skill** `adversarial-review`, not a new workflow inside `pr-review-loop` | Single clear purpose; composes with `pr-review-loop` rather than bloating it. |
| D2 | Adversary = **Gemini CLI**, model-pluggable internally | Already installed, distinct lineage; the adversary call is isolated to one script so it can be swapped. |
| D3 | Protocol = **3-round refutation loop** (R1 Claude → R2 Gemini → R3 Claude), bounded | True two-way cross-examination without unbounded looping. |
| D4 | **Survivor rule = both models must confirm** (symmetric) | High precision over recall — the user explicitly wants adversarial rigor, not maximal coverage. |
| D5 | Trigger = **auto-detect**: PR exists → post comments; else working-tree diff → terminal | One command, both modes; fits Git Flow. |
| D6 | Adversary-unavailable = **explicit loud degradation**, never silent | Matches `optional-runtime-dependency` + silent-failure discipline. |

## 5. Architecture

Pipeline:

```
detect-mode -> R1 Claude review -> R2 Gemini refute+augment -> R3 Claude refute -> synthesize -> sink
```

| Component | Type | Role |
|-----------|------|------|
| `scripts/detect-mode.sh` | script | Resolve base branch (`gh pr view <branch> --json baseRefName` if a PR exists, else `develop`/`main` by branch prefix). Emit `MODE=pr\|local`, PR number (if any), and the **unified diff + changed-file list** as the single shared review artifact both models consume. |
| **R1 — Claude review** | subagents | Opus bug-hunt + Sonnet convention/CLAUDE.md scan over the shared diff, grounded in actual source files. Emits findings JSON (schema below). |
| `scripts/gemini-review.sh` | script | **R2.** Feeds Gemini the *same diff* + Claude's findings JSON via `gemini -p … -o json -m <model>`. Robust extraction of the model's JSON payload from the CLI envelope; one retry with a stricter "JSON only" prompt on parse failure. |
| **R3 — Claude refute** | subagent | Adjudicates Gemini output against real source (reads files, not just diff hunks): per Gemini *refutation* → accept (drop) or defend; per Gemini *new* finding → confirm or refute. |
| **synthesize** | logic | Apply survivor rule (D4) → classify SURVIVORS / UNCONFIRMED (single-model) / REJECTED (with killer + reason). |
| **sink** | script | `local` → terminal report + write gitignored `<branch>.adversarial-review.md`. `pr` → post survivors as PR review comments via `pr-review-loop`'s `pr-review-cli.sh`; optionally chain into `pr-review-loop` Workflow B for resolution. |

### Refutation protocol (the core)

- **R1 (Claude finds):** N findings, each grounded in source.
- **R2 (Gemini cross-examines):** for each Claude finding → `confirm | refute` + reason + confidence; **plus** any NEW findings (same schema). Gemini sees only the diff + Claude's findings.
- **R3 (Claude cross-examines back):** for each Gemini refutation → accept (drop Claude's finding) or defend; for each Gemini new finding → `confirm | refute` by reading the actual code.
- **Survivor rule (D4 — both must confirm):**
  - A Claude finding survives **iff Gemini confirmed it** in R2.
  - A Gemini new finding survives **iff Claude confirmed it** in R3.
  - All other findings → `UNCONFIRMED (single-model)` bucket (surfaced below survivors, never silently dropped).
  - Rejected findings retained with *which model killed it and why*.
- **Bounded:** exactly 3 rounds. No tie-break round (both-confirm rule makes unresolved disagreement simply land in UNCONFIRMED).

### Finding schema (shared across rounds)

```json
{
  "id": "f1",
  "path": "src/foo.ts",
  "line": 42,
  "severity": "critical|important|minor",
  "category": "bug|security|convention|perf|maintainability",
  "title": "one-line summary",
  "rationale": "why this is a problem, grounded in the code",
  "origin": "claude|gemini",
  "claude_verdict": "confirm|refute|null",
  "gemini_verdict": "confirm|refute|null",
  "status": "survivor|unconfirmed|rejected",
  "killed_by": "claude|gemini|null",
  "kill_reason": "string|null"
}
```

## 6. Modes & failure handling

- **Auto-detect (D5):** PR for branch → review `gh pr diff`, post survivors as review comments. No PR → review `git diff <base>...HEAD`, terminal + gitignored markdown.
- **Adversary-unavailable degradation (D6):** if Gemini is unauthenticated / errors / returns unparseable JSON after one retry → fall back to **Claude-only review** with a loud `ADVERSARY UNAVAILABLE — single-model review only` banner. The second opinion is never silently skipped.
- **Same-diff invariant:** both models review the byte-identical diff artifact produced by `detect-mode.sh`.
- **Large-diff cap:** above a threshold, warn and require explicit continue rather than truncating quietly.

## 7. Verification plan

Script-level tests with fixture JSON (model output is not unit-testable; plumbing and classification are):

- `detect-mode.sh`: PR-present vs PR-absent; base-branch resolution by branch prefix.
- diff extraction: correct artifact for both modes.
- `gemini-review.sh`: parse well-formed JSON; recover via retry on malformed; surface failure after retry.
- **synthesis/classification:** given fixed R1/R2/R3 inputs, assert correct SURVIVOR / UNCONFIRMED / REJECTED partition under the both-confirm rule.
- **degradation path:** Gemini unavailable → Claude-only report with banner, exit 0.

Manual acceptance: run against a real openclaw PR and a real working-tree diff; confirm survivor precision and the audit trail (killed findings show reason).

## 8. Risks & follow-ups

- **Precision/recall trade:** both-confirm suppresses single-model true positives. Mitigated by the visible UNCONFIRMED bucket.
- **Gemini JSON reliability:** CLI may wrap or chat around JSON; mitigated by `-o json` + extraction + retry, then graceful degradation.
- **Auth prerequisite:** Gemini CLI must be authenticated once before first real run.
- **Follow-up:** make the adversary model pluggable to GPT-5 / DeepSeek (the R2 script already isolates this).

## 9. Acceptance criteria

- [ ] `/adversarial-review` runs end-to-end in both PR and local modes.
- [ ] 3-round refutation produces SURVIVORS / UNCONFIRMED / REJECTED with both-confirm semantics.
- [ ] Killed findings show killer model + reason.
- [ ] Gemini-unavailable path degrades to Claude-only with a loud banner and exit 0.
- [ ] Script-level tests cover mode detection, diff extraction, Gemini parse/retry, classification, and degradation.
- [ ] In PR mode, survivors post as PR review comments via `pr-review-cli.sh`.

## 10. Tracking

GitHub issue: *TBD (pending user decision on issue creation).*
