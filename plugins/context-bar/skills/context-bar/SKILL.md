---
name: context-bar
version: 1.0.0
description: Show a single-line context usage progress bar with color-coded statusline
user_invocable: true
---

Run this command. The Bash output IS the result — do NOT echo or repeat it in your response. Say nothing after the command runs.

```bash
bash ~/.claude/skills/context-bar/context-bar.sh
```

## Setup: Statusline with Context Bar

To always see context usage in your Claude Code statusline, copy `statusline-command.sh` to `~/.claude/` and add to your settings.json (user-level or project-level `.claude/settings.local.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

The statusline shows model, directory, git branch, and a color-coded context bar (green <50%, amber 50-79%, red 80%+).
