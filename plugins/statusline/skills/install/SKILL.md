---
name: install
description: "Installs a ready-made 3-tier adaptive Claude Code statusline (model, folder, git branch with sync status, color-coded context bar) and points ~/.claude/settings.json at it. Use when: (1) the user wants a good statusline without designing one, (2) the user asks to install or reinstall the custom statusline, (3) /install-statusline or custom-statusline (the old names of this skill), (4) the statusline went missing after a settings change."
metadata:
  version: 1.0.0
---

# Install the statusline

Installs a Claude Code statusline with:
- 📁 Project directory
- 🌿 Git branch with sync status: `develop(⇡⇣)`, `feat/foo(~2|⇡1)`
- 🧠 Context usage with a color-coded progress bar (green/yellow/red)
- A 3-tier adaptive layout (<40, 40-59 and 60+ columns) that picks 1, 2 or 3 lines

## Install

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/install.sh"
```

It copies `references/statusline-command.sh` to `~/.claude/statusline-command.sh` and sets `statusLine` in `~/.claude/settings.json`. Then restart Claude Code.

## Layout tiers

| Width | Device | Layout |
|-------|--------|--------|
| <40 | iPhone portrait | 3 lines: model / branch / bar |
| 40-59 | iPhone landscape | 2-3 lines: model+dir / branch(+bar) / (bar) |
| 60+ | Desktop / iPad | 1-3 lines: auto-adapts to branch length |

To build a different statusline from parts, use `/statusline:create`.
