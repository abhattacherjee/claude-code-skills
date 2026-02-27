# skill-authoring

Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism.

## What It Does

This skill is your guide to writing high-quality Claude Code skills. When you invoke it (or when Claude detects you're creating a skill), it provides:

- **Structured authoring workflow** — from checking for existing skills to validation
- **Frontmatter rules** — exactly which fields to use (`name`, `description`, `metadata.version`) and which to avoid
- **Directory layout conventions** — where to put SKILL.md, scripts/, references/, and agent definitions
- **Script-first methodology** — when to extract deterministic logic into bash scripts vs. keeping it in SKILL.md prose
- **Agent decomposition patterns** — how to split complex skills into parallel sub-agents with an orchestrator
- **Quality checklist** — verify your skill meets all requirements before publishing
- **Anti-patterns** — common mistakes like sequential agents, monolithic prompts, and verbose explanations

## Key Features

### Decomposition Framework

Evaluates whether your skill should use parallel agents:

| Signal | Approach |
|--------|----------|
| 2+ independent subtasks | Parallel sub-agents |
| Web search or AI judgement needed | Dedicated agent per domain |
| N items of the same type | Fan-out: one agent per item |
| Single deterministic check | Script only, no agent |

### Script Extraction

Decides when to extract bash scripts from SKILL.md:

- Skill checks/validates/detects something — extract
- Same code block in multiple skills — extract
- Users may run it standalone — extract

Scripts follow conventions: `--help`, `--fix`, `--dry-run`, meaningful exit codes, `#!/usr/bin/env bash`.

### Templates

Provides two ready-to-use templates:

1. **Simple skill** — script-only, no agents (for validation/detection tasks)
2. **Complex skill** — orchestrator + parallel agents + scripts (for multi-phase workflows)

## Contents

- **1** skill(s)
- **0** command(s)

### Skills

- `skill-authoring` — SKILL.md with authoring guidelines + `validate-skill.sh` validation script

## Usage

The skill activates automatically when Claude detects you're creating or optimizing a skill. You can also invoke it explicitly:

```
# Ask Claude to create a skill
"Create a skill for validating catalog URLs"

# Ask Claude to optimize an existing skill
"Optimize my deployment skill — it's over 600 lines"

# Reference the skill directly
"Following skill-authoring best practices, write a SKILL.md for..."
```

### Included Validation Script

```bash
# Validate a skill directory
~/.claude/skills/skill-authoring/scripts/validate-skill.sh /path/to/your-skill

# Checks: frontmatter fields, description format, body length, script conventions
```

## Prerequisites

- Claude Code CLI (or compatible AI coding tool)
- No external dependencies — this is a knowledge skill (SKILL.md + validation script)

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install skill-authoring@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/skill-authoring
rm -rf /tmp/ccs
```

### Manual

```bash
cp -r plugins/skill-authoring/skills/* ~/.claude/skills/
```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall skill-authoring@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/skill-authoring
rm -rf /tmp/ccs
```

## Companion Skills

- **[skill-publishing](../skill-publishing/)** — package and distribute skills as plugins to GitHub
- **[claudeception](../../claudeception/)** — extracts reusable knowledge from work sessions into skills (uses skill-authoring for structure)

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
