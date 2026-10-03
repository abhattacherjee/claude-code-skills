---
name: context-bar
description: "Shows a single-line, color-coded progress bar of how much of the context window the current Claude Code session has used, estimated from its transcript size. Use when: (1) the user asks how full the context is, (2) /context-bar, (3) deciding whether to compact or start a new session."
metadata:
  version: 1.0.0
---

Run this command. The Bash output IS the result — do NOT echo or repeat it in your response. Say nothing after the command runs.

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/context-bar.sh"
```

## Always-on context bar

For a context bar that is always visible, build a statusline with the `context-bar` item: `/statusline:create`. The bar is green below 50%, amber from 50% to 79%, and red from 80%.
