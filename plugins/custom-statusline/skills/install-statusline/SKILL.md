---
name: install-statusline
description: "Deprecated: use statusline:install. Installs a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage. Use when: (1) the user asks to install the custom statusline, (2) the statusline went missing after a settings change."
metadata:
  version: 1.3.2
---

# Custom Statusline Installer

Installs a custom Claude Code statusline with:
- 📁 Project directory
- 🌿 Git branch with sync status: `develop(ok)`, `feat/foo(~2|+1)`
- 🧠 Context usage with color-coded progress bar (green/yellow/red)
- 4-tier adaptive layout for any screen size

## Install

Run the install script — it copies the statusline and updates settings.json:

```bash
bash ~/.claude/skills/custom-statusline/scripts/install.sh
```

Then restart Claude Code.

## Layout Tiers

| Width | Device | Layout |
|-------|--------|--------|
| <40 | iPhone portrait | 3 lines: model / branch / bar |
| 40-59 | iPhone landscape | 2-3 lines: model+dir / branch(+bar) / (bar) |
| 60+ | Desktop / iPad | 1-3 lines: auto-adapts to branch length |
