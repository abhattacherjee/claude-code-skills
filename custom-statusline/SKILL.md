---
name: install-statusline
description: Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage
version: 1.1.0
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
| <40 | iPhone portrait | `●●○○○○○○ 12% develop(ok)` |
| 40-59 | iPhone landscape | Model + git / context bar |
| 60-99 | SSH / small laptop | Model + dir / git + context bar |
| 100+ | Desktop / iPad | Everything on two clean lines |
