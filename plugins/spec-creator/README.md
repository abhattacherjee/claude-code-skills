# spec-creator

Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues).

## What It Does

Creates detailed story specification files from various inputs (Claude plan, requirement file, prompt, GitHub issue). Discovers project spec conventions at runtime, brainstorms approaches with vertical splitting recommendations for large stories, generates template-compliant specs, checks for over-engineering, and optionally chains to spec-review.

**Use when:**
- user wants to write a new story spec, 
- converting a plan or requirements into a formal spec, 
- creating specs from GitHub issues, 
- breaking a large feature into shippable vertical slices.

## Key Features

- **Problem**
- **Progress Tracking (MANDATORY)**
- **Workflow (5 Phases)**
- **Epic {NEXT_EPIC}: {Feature Name}**
- **Input Examples**
- **Integration with Other Skills**

## Usage

```bash
# Discover project spec conventions
~/.claude/skills/spec-creator/scripts/discover-conventions.sh .           # Report
~/.claude/skills/spec-creator/scripts/discover-conventions.sh . --json    # JSON
```

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `spec-creator` — Creates detailed story specification files from various inputs (Claude plan, requirement file, prompt, GitHub issue). Discovers project spec conventions at runtime, brainstorms approaches with vertical splitting recommendations for large stories, generates template-compliant specs, checks for over-engineering, and optionally chains to spec-review.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install spec-creator@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/spec-creator
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/spec-creator/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall spec-creator@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/spec-creator
rm -rf /tmp/ccs
```

## See Also

- `spec-review` — reviews and enriches existing specs (post-creation step)
- `skill-authoring` — how this skill was built
- `implement-story` — implements a spec (the next step after creation + review)

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
