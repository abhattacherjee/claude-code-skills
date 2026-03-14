# custom-statusline

4-tier adaptive statusline with icons for folder, git branch, and context usage

## What It Does

Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage

## Key Features

- **Install**
- **Layout Tiers**

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `install-statusline` — Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install custom-statusline@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/custom-statusline
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/custom-statusline/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall custom-statusline@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/custom-statusline
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
