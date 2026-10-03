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

If `~/.claude/statusline-command.sh` already exists and this plugin did not write it (its line 2 is not `# managed-by: statusline-plugin`), the script leaves it alone and exits 3. Tell the user, and re-run with `--force` only if they want it replaced. `--force` backs the old file up to `statusline-command.sh.bak-<UTC time>` first:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/install.sh" --force
```

Exit codes: 0 installed; 1 a write failed (old files unchanged); 2 bad input, such as a `settings.json` that is not one JSON object (fix it by hand; it was not changed); 3 refused, as above. Any file it replaces is backed up next to it first.

## Layout tiers

| Width | Device | Layout |
|-------|--------|--------|
| <40 | iPhone portrait | 3 lines: model / branch / bar |
| 40-59 | iPhone landscape | 2-3 lines: model+dir / branch(+bar) / (bar) |
| 60+ | Desktop / iPad | 1-3 lines: auto-adapts to branch length |

To build a different statusline from parts, use `/statusline:create`.
