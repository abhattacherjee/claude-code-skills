# deep-review

Two-phase convergence harness for high-assurance review of a changeset (PR or working-tree diff). Phase 1 loops iterative multi-reviewer fix->re-review until a round finds zero actionable issues; Phase 2 runs a Gemini-primary adversarial cross-examination (Gemini finds -> Claude judges -> Gemini counters), fixing every confirmed finding. Soft-depends on pr-review-toolkit and adversarial-review plugins with documented fallbacks.

## What It Does

Runs two convergence phases on a PR or working-tree diff. Phase 1 dispatches specialized reviewers (general code, test coverage, silent-failure, type design, comments) in fix→re-review rounds until a full round finds zero actionable issues. Phase 2 runs a Gemini-primary adversarial cross-examination — Gemini finds, Claude judges, Gemini counters — so only findings the opposing model confirms survive, and every survivor is fixed and verified. The result is a changeset that passed both a depth gauntlet and a cross-model gauntlet.

## Key Features

- **Two-phase convergence** — an iterative multi-reviewer depth pass followed by an adversarial cross-model pass; the changeset must clear both gauntlets.
- **Iterative review to zero issues** — specialized reviewers (code, tests, silent-failure, types, comments) run in fix→re-review rounds until a full round finds nothing actionable.
- **Claude↔Gemini adversarial cross-examination** — both models discover findings independently, then judge each other's; only findings the opposing model confirms survive.
- **Evidence-settled disputes** — refuted findings go to a counter-round where direct source evidence (not opinion) decides, and genuine judgment calls are escalated to you.
- **Graceful degradation** — if Gemini isn't available it falls back to a second independent Claude reviewer as the adversary, with a loud banner that cross-model confirmation was skipped.
- **PR or working-tree mode** — auto-targets an open PR's diff or local changes, with flags for phase selection (`--phase1-only`/`--phase2-only`) and `--max-rounds`.

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `deep-review` — Two-phase iterative + adversarial review harness that converges a changeset to zero actionable, cross-model-confirmed issues.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install deep-review@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/deep-review
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/deep-review/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall deep-review@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/deep-review
rm -rf /tmp/ccs
```

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
