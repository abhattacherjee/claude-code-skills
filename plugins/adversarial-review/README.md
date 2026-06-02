# adversarial-review

Adversarial PR review — Claude and Gemini cross-examine each other's findings on a diff via a bounded 3-round refutation loop, surfacing only issues both models confirm

## What It Does

Runs a two-model adversarial review of a diff. Claude performs an initial review (R1), Gemini cross-examines Claude's findings and adds its own (R2), then Claude cross-examines Gemini's output against actual source files (R3). Only findings both models confirm survive to the report. Single-model findings land in an UNCONFIRMED bucket; rejected findings are retained with the killing model and its reason.

**Use when:**
- you want a high-precision code review before merging a PR, not maximal coverage,
- Copilot is unavailable and you want a non-Claude second opinion as the adversary,
- you are working in Git Flow and want a review of either a PR diff or your local working-tree changes,
- you want an auditable trail showing exactly which model killed each finding and why.

## How It Works

### Pipeline

```
detect-mode → R1 Claude review → R2 Gemini refute+augment → R3 Claude refute → synthesize → sink
```

### 3-Round Refutation Loop

1. **R1 — Claude review:** Two sub-agents (bug-hunter on Opus, convention-reviewer on Sonnet) review the diff grounded in actual source files. Each emits findings in a shared JSON schema.
2. **R2 — Gemini cross-examines:** `gemini-review.sh` feeds Gemini the same byte-identical diff plus Claude's R1 findings. Gemini either confirms or refutes each Claude finding (with reason + confidence) and adds any new findings of its own. JSON is extracted from the CLI envelope with one retry on parse failure.
3. **R3 — Claude cross-examines back:** The `adversarial-r3-adjudicator` (Opus) reads actual source files — not just diff hunks — to adjudicate: per Gemini refutation → accept (drop Claude's finding) or defend; per Gemini new finding → confirm or refute.

### Survivor Rule

- A Claude finding survives **if and only if Gemini confirmed it** in R2.
- A Gemini new finding survives **if and only if Claude confirmed it** in R3.
- All other findings → `UNCONFIRMED (single-model)` bucket, surfaced below survivors and never silently dropped.
- Rejected findings are retained with which model killed them and why.
- The loop is bounded to exactly 3 rounds — no tie-break round.

### Modes

- **PR mode** (auto-detected when a PR exists for the current branch): reviews `gh pr diff`, posts survivor findings as PR review comments via `pr-review-loop`'s `pr-review-cli.sh`.
- **Local mode** (no PR found): reviews `git diff <base>...HEAD` against the working tree, prints a terminal report, and writes a gitignored `<branch>.adversarial-review.md` file.

### Degradation

If Gemini is unauthenticated, errors, or returns unparseable JSON after one retry, the skill falls back to a **Claude-only review** and prints a loud `ADVERSARY UNAVAILABLE — single-model review only` banner. The second opinion is never silently skipped.

## Prerequisites

The skill now **auto-detects and guides Gemini setup** at the start of every run via `ensure-gemini.sh` + Step 0:

- **Not installed:** the orchestrator tells you what's missing, shows the install command (`npm install -g @google/gemini-cli`), and asks whether to run it. If you decline or install fails, the skill proceeds in Claude-only mode with a loud degradation banner.
- **Installed but unauthenticated:** the orchestrator shows auth options (set `GEMINI_API_KEY`, or run `gemini` once for interactive Google login) and asks you to complete auth before continuing. Declining → Claude-only mode.
- **Auth state unknown** (installed, no detectable key/creds): the skill proceeds and relies on the runtime guard in `gemini-review.sh` (exit 3) to catch failures.
- **Installed and authenticated:** no interaction — continues immediately.

No manual pre-flight is required. The `gemini` binary version 0.38.2+ supports `gemini -p "<prompt>" -o json` for headless use.

## Contents

- **1** skill(s), **0** command(s), **3** agent(s)

### Skills

- `adversarial-review` — Adversarial PR review via a bounded Claude↔Gemini 3-round refutation loop. Surfaces only findings both models confirm. Auto-detects PR vs local mode.

### Agents

- `adversarial-bug-hunter` (Opus) — R1 bug-hunt pass over the diff, grounded in actual source files. NOT user-invocable — spawned by the adversarial-review skill.
- `adversarial-convention-reviewer` (Sonnet) — R1 convention and CLAUDE.md compliance scan over the diff. NOT user-invocable — spawned by the adversarial-review skill.
- `adversarial-r3-adjudicator` (Opus) — R3 Claude cross-examination: reads actual source files to confirm or refute Gemini's R2 findings and rebuttals. NOT user-invocable — spawned by the adversarial-review skill.

### Scripts

- `ensure-gemini.sh` — Step 0 detection: emits `KEY=VALUE` status lines (installed, version, authed, install hint, auth hint); never installs or calls the network; used by the orchestrator to guide setup before the pipeline runs.
- `detect-mode.sh` — resolves PR vs local mode and emits the shared diff artifact both models consume.
- `gemini-review.sh` — feeds Gemini the diff + R1 findings; extracts JSON from the CLI envelope; retries once on parse failure.
- `synthesize.py` — applies the survivor rule to R1/R2/R3 outputs, classifying findings into SURVIVORS / UNCONFIRMED / REJECTED.
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
- `adversarial-r3-adjudicator` agent (`~/.claude/agents/adversarial-r3-adjudicator.md`) — R3 adjudicator sub-agent
- `code-review` skill — built-in all-Claude breadth review (no adversary; use for full coverage rather than precision)

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
