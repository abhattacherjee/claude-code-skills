# git-flow

Git Flow branching workflow with slash commands and diagnostic tools

## Contents

- **1** skill(s)
- **5** command(s)

### Commands

- `/feature`
- `/release`
- `/hotfix`
- `/finish`
- `/flow-status`

## Installation

### From monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/git-flow
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/git-flow/skills/* ~/.claude/skills/

# Copy commands
cp plugins/git-flow/commands/*.md ~/.claude/commands/
```

## Uninstall

```bash
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/git-flow
```

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
