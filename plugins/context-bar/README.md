# context-bar

Color-coded context window usage bar for Claude Code statusline and `/context-bar` command.

## What You Get

- **Statusline**: Always-visible context usage bar at the bottom of Claude Code (green/amber/red)
- **`/context-bar` command**: Quick on-demand context check via slash command

```
[Opus 4.6 (1M context)] 📁 my-project | 🌿 feature/my-branch (3)
ctx:[███░░░░░░░░░░░░░░░░░] 16%
▸▸ accept edits on (shift+tab to cycle)
```

## Features

- Color-coded progress bar: **green** (<50%), **amber** (50-79%), **red** (80%+)
- Shows model, directory, git branch, and uncommitted file count
- Uses Claude Code's real `context_window.used_percentage` (not an estimate)
- Statusline updates after every assistant response

## Installation

### Via Claude Code Plugin (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugins marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugins install context-bar@abhattacherjee-claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/context-bar
rm -rf /tmp/ccs
```

### Manual

```bash
cp -r plugins/context-bar/skills/* ~/.claude/skills/
```

## Statusline Setup (Required After Install)

The plugin installs the `/context-bar` skill automatically. To get the **always-visible statusline**, you need to configure it manually:

**1. Copy the statusline script:**
```bash
cp ~/.claude/skills/context-bar/statusline-command.sh ~/.claude/statusline-command.sh
```

**2. Add to your settings.json** (`~/.claude/settings.json` or project-level `.claude/settings.local.json`):
```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

> **Important**: If you have a project-level `statusLine` in `.claude/settings.local.json`, it overrides the user-level one. Update whichever file takes precedence for your project.

## Uninstall

```bash
# Via Claude Code
/plugin uninstall context-bar@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/context-bar
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
