---
name: context-bar
description: "Shows a single-line, color-coded progress bar of how much of the context window the current Claude Code session has used, estimated from its transcript size. Use when: (1) the user asks how full the context is, (2) /context-bar, (3) deciding whether to compact or start a new session."
metadata:
  version: 1.0.0
---

Run this command. On exit 0 the Bash output IS the result: do not echo or repeat it, and say nothing after it.

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/context-bar.sh"
```

The bar is an estimate from the size of this session's transcript in `~/.claude/projects/<working dir with non-alphanumerics as ->/` (under `$CLAUDE_CONFIG_DIR` instead of `~/.claude` when that is set), measured against a fixed 1M-token window, so on a 200K-context model it reads low. If the script exits 1, it found no transcript for the current directory (for example after a `cd`); say that in one line instead of guessing a number.

## Always-on context bar

For a context bar that is always visible, build a statusline with the `context-bar` item: `/statusline:create`. The bar is green below 50%, amber from 50% to 79%, and red from 80%.
