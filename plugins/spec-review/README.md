# spec-review

Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans.

## What It Does

Reviews and enriches story specifications with codebase-verified technical sub-tasks, architecture alignment checks, design simplification suggestions, and API test plans. Dynamically discovers project architecture at runtime.

**Use when:**
- a new story spec needs review before implementation, 
- a spec has high-level tasks but lacks implementation-ready detail, 
- need to verify spec assumptions against actual codebase, 
- a spec references API changes but has no test plan, 
- reviewing specs that reference data shapes or pipeline ordering, 
- spec subtasks mention add field X to object Y or call function at line N.

## Key Features

- **Part 1: Codebase Verification Checklist**
- **Part 2: Full Planning Workflow**
- **API Test Plan**
- **Current Codebase State**
- **Design Simplification Notes**

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `spec-review` — Reviews and enriches story specifications with codebase-verified technical sub-tasks, architecture alignment checks, design simplification suggestions, and API test plans. Dynamically discovers project architecture at runtime.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install spec-review@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/spec-review
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/spec-review/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall spec-review@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/spec-review
rm -rf /tmp/ccs
```

## See Also

- `spec-creator` — generates story specs (this skill reviews them)
- `context-shield` — use when a spec references many external docs that need reading

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
