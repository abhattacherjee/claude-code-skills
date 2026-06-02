# adversarial-review

Adversarial PR review — Claude and Gemini discover findings independently then cross-examine each other symmetrically, surfacing only issues both models confirm

## What It Does

Runs a symmetric two-model adversarial review of a diff. Both Claude and Gemini independently discover findings in R1 (neither sees the other's output). In R2, each model cross-examines the other's findings against actual source code. Only findings confirmed by the opposing model survive to the report. Single-model findings land in an UNCONFIRMED bucket; rejected findings are retained with the refuting model and its reason.

**Use when:**
- you want a high-precision code review before merging a PR, not maximal coverage,
- Copilot is unavailable and you want a non-Claude second opinion as the adversary,
- you are working in Git Flow and want a review of either a PR diff or your local working-tree changes,
- you want an auditable trail showing exactly which model rejected each finding and why.

## How It Works

### Pipeline

```
detect-mode → R1 parallel independent discovery → R2 parallel symmetric cross-examination → synthesize → sink
```

### Symmetric 2-Round Pipeline

1. **R1 — Independent discovery (parallel, blind):** Two Claude sub-agents (bug-hunter on Opus, convention-reviewer on Sonnet) review the diff grounded in actual source files — their findings become `r1-claude.json`. Simultaneously, `gemini-review.sh --mode find` runs Gemini's independent pass — findings become `r1-gemini.json`. Neither side sees the other's output.
2. **R2 — Symmetric cross-examination (parallel):** The `adversarial-cross-examiner` (Opus) reads Gemini's R1 findings against actual source and returns confirm/refute verdicts (`r2-claude-verdicts.json`). Simultaneously, `gemini-review.sh --mode judge` cross-examines Claude's R1 findings and returns verdicts (`r2-gemini-verdicts.json`).

### Survivor Rule

- A Claude finding (C-NNN) survives **if and only if Gemini confirmed it** in R2.
- A Gemini finding (G-NNN) survives **if and only if Claude confirmed it** in R2.
- All other findings → `UNCONFIRMED (single-model)` bucket, surfaced below survivors and never silently dropped.
- Rejected findings are retained with which model refuted them and why.
- Convergence is purely mechanical — `synthesize.py` applies the rule with no further adjudication.

### Modes

- **PR mode** (auto-detected when a PR exists for the current branch): reviews `gh pr diff`, posts survivor findings as PR review comments via `pr-review-loop`'s `pr-review-cli.sh`.
- **Local mode** (no PR found): reviews `git diff <base>...HEAD` against the working tree, prints a terminal report, and writes a gitignored `<branch>.adversarial-review.md` file.

### Degradation

If Gemini is unauthenticated, errors, or returns unparseable JSON after one retry, the skill falls back to a **Claude-only review** and prints a loud `ADVERSARY UNAVAILABLE — single-model review only` banner. The second opinion is never silently skipped.

## Prerequisites

The skill now **auto-detects and guides Gemini setup** at the start of every run via `ensure-gemini.sh` + Step 0:

- **Not installed:** the orchestrator tells you what's missing, shows the install command (`npm install -g @google/gemini-cli`), and asks whether to run it. If you decline or install fails, the skill proceeds in Claude-only mode with a loud degradation banner.
- **Installed but unauthenticated:** the orchestrator prompts you to supply a headless-capable credential. **Interactive `gemini` Google login is NOT sufficient** — the skill's headless calls (`gemini -p ... -o json`) require a `GEMINI_API_KEY` or Vertex AI credentials. Recommended: add `GEMINI_API_KEY=<key>` to `~/.gemini/.env` (auto-loaded by all shells, including sub-agent/tool contexts; get a key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)). `export GEMINI_API_KEY=<key>` in your shell also works for the current session. Declining → Claude-only mode.
- **Auth state unknown** (installed, no detectable headless credential): the skill proceeds and relies on the runtime guard in `gemini-review.sh` (exit 3) to catch failures.
- **Installed and authenticated:** no interaction — continues immediately.

No manual pre-flight is required. The `gemini` binary version 0.38.2+ supports `gemini -p "<prompt>" -o json` for headless use.

## Contents

- **1** skill(s), **0** command(s), **3** agent(s)

### Skills

- `adversarial-review` — Adversarial PR review via symmetric Claude↔Gemini independent discovery and cross-examination. Surfaces only findings both models confirm. Auto-detects PR vs local mode.

### Agents

- `adversarial-bug-hunter` (Opus) — R1 bug-hunt pass over the diff, grounded in actual source files. NOT user-invocable — spawned by the adversarial-review skill.
- `adversarial-convention-reviewer` (Sonnet) — R1 convention and CLAUDE.md compliance scan over the diff. NOT user-invocable — spawned by the adversarial-review skill.
- `adversarial-cross-examiner` (Opus) — R2 symmetric cross-examiner: reads Gemini's R1 findings against actual source files and returns confirm/refute verdicts. NOT user-invocable — spawned by the adversarial-review skill.

### Scripts

- `ensure-gemini.sh` — Step 0 detection: emits `KEY=VALUE` status lines (installed, version, authed, install hint, auth hint); never installs or calls the network; used by the orchestrator to guide setup before the pipeline runs.
- `detect-mode.sh` — resolves PR vs local mode and emits the shared diff artifact both models consume.
- `gemini-review.sh` — `--mode find`: Gemini's independent R1 discovery pass; `--mode judge`: Gemini's R2 cross-examination of Claude's findings; extracts JSON from the CLI envelope; retries once on parse failure.
- `synthesize.py` — applies the survivor rule to the 4 symmetric inputs (claude-findings, gemini-findings, gemini-verdicts, claude-verdicts), classifying findings into SURVIVORS / UNCONFIRMED / REJECTED.
- `sink.sh` — delivers the report: posts PR review comments in PR mode; writes terminal report + markdown file in local mode.
- `run-tests.sh` — script-level tests covering mode detection, diff extraction, Gemini parse/retry/degradation, the classification partition, and ensure-gemini.sh detection logic.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install adversarial-review@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/adversarial-review
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills and agents
cp -r plugins/adversarial-review/skills/* ~/.claude/skills/
cp -r plugins/adversarial-review/agents/* ~/.claude/agents/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall adversarial-review@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/adversarial-review
rm -rf /tmp/ccs
```

## See Also

- `pr-review-loop` plugin — Workflow B for posting and resolving PR comments from the adversarial review's survivor output
- `adversarial-bug-hunter` agent (`~/.claude/agents/adversarial-bug-hunter.md`) — R1 bug-hunt sub-agent
- `adversarial-convention-reviewer` agent (`~/.claude/agents/adversarial-convention-reviewer.md`) — R1 convention sub-agent
- `adversarial-cross-examiner` agent (`~/.claude/agents/adversarial-cross-examiner.md`) — R2 cross-examiner sub-agent
- `code-review` skill — built-in all-Claude breadth review (no adversary; use for full coverage rather than precision)

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
