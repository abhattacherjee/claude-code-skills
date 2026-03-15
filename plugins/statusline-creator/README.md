# statusline-creator

Creates and customizes Claude Code statusline scripts from composable items

## What It Does

Creates and customizes Claude Code statusline scripts from composable items.

**Use when:**
- user wants to add or change their statusline, 
- user asks to show cost, git, context, or other info in the status bar, 
- user says 'customize my statusline' or 'add X to my statusline', 
- user wants to create a statusline from scratch, 
- debugging statusline display issues.

## Key Features

- **Quick Generate**
- **How Statuslines Work**
- **Available Items (20 composable blocks)**
- **Writing Custom Items**
- **Presets**
- **Troubleshooting**

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `statusline-creator` — Creates and customizes Claude Code statusline scripts from composable items.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install statusline-creator@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/statusline-creator
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/statusline-creator/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall statusline-creator@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/statusline-creator
rm -rf /tmp/ccs
```

## See Also

- `context-bar` skill — quick context usage display (subset of this skill)
- [Official docs](https://code.claude.com/docs/en/statusline) — Claude Code statusline reference
- [ccstatusline](https://github.com/sirmalloc/ccstatusline) — community powerline-style statusline

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
