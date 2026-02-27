# skill-publishing

Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## Contents

- **1** skill(s)
- **0** command(s)

### Commands

- `/null`
- `/null`

## Installation

### From monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/skill-publishing
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/skill-publishing/skills/* ~/.claude/skills/

# Copy commands
cp plugins/skill-publishing/commands/*.md ~/.claude/commands/
```

## Uninstall

```bash
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/skill-publishing
```

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
