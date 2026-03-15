---
name: statusline-creator
description: "Creates and customizes Claude Code statusline scripts from composable items. Use when: (1) user wants to add or change their statusline, (2) user asks to show cost, git, context, or other info in the status bar, (3) user says 'customize my statusline' or 'add X to my statusline', (4) user wants to create a statusline from scratch, (5) debugging statusline display issues."
metadata:
  version: 1.0.0
---

# Statusline Creator

Creates Claude Code statusline scripts from composable items with full JSON schema awareness.

## Quick Generate

```bash
# List available items
~/.claude/skills/statusline-creator/scripts/generate-statusline.sh --list

# Generate 2-line statusline with common items
~/.claude/skills/statusline-creator/scripts/generate-statusline.sh \
  --items "model,dir,git,git-sync,context-bar,cost,duration" \
  --lines 2 --install

# Test with mock data
echo '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"/tmp/test"},"context_window":{"used_percentage":42,"context_window_size":200000},"cost":{"total_cost_usd":0.05,"total_duration_ms":120000}}' | bash ~/.claude/statusline-command.sh
```

## How Statuslines Work

1. Add `statusLine` to `~/.claude/settings.json`:
   ```json
   {"statusLine": {"type": "command", "command": "bash ~/.claude/statusline-command.sh"}}
   ```
2. Claude Code pipes JSON session data to your script via stdin after each assistant message
3. Your script reads JSON, extracts fields, prints formatted text to stdout
4. Each `echo`/`printf` = one row in the status bar

**Timing**: runs after each assistant message, debounced at 300ms. Cancelled if new update triggers while running.

## Available Items (20 composable blocks)

| Item | Category | Description |
|------|----------|-------------|
| `model` | Display | Model name ("Opus") |
| `model-full` | Display | Model + 1M context indicator |
| `dir` | Display | Working directory basename |
| `session-id` | Display | Short session ID (8 chars) |
| `style` | Display | Output style name |
| `vim-mode` | Display | Vim mode ([N]/[I]) |
| `agent` | Display | Agent name when using --agent |
| `worktree` | Display | Worktree name indicator |
| `context-bar` | Context | Progress bar with color thresholds |
| `context-pct` | Context | Percentage number only |
| `tokens` | Context | Detailed in/out token counts (K) |
| `warn-200k` | Context | Warning when >200K tokens |
| `cost` | Metrics | Session cost ($X.XX) |
| `cost-color` | Metrics | Cost with green/yellow/red thresholds |
| `duration` | Metrics | Wall-clock time (Xm Ys) |
| `api-duration` | Metrics | API response time only |
| `lines-changed` | Metrics | Lines +added -removed |
| `git` | Git | Branch + staged/modified (5s cache) |
| `git-sync` | Git | Upstream ahead/behind arrows |
| `git-link` | Git | Clickable OSC 8 repo link |

## Writing Custom Items

If the generator doesn't cover your use case, write items manually. See **[references/item-recipes.md](references/item-recipes.md)** for copy-paste bash snippets for each item.

For the complete JSON schema with all available fields, see **[references/json-schema.md](references/json-schema.md)**.

### Key patterns:
- Always handle null: `jq -r '.field // 0'` or `jq -r '.field // empty'`
- ANSI colors: `\033[32m` green, `\033[33m` yellow, `\033[31m` red, `\033[0m` reset
- OSC 8 links: `\033]8;;URL\aText\033]8;;\a` (iTerm2, Kitty, WezTerm only)
- Cache expensive ops: git commands in `/tmp/statusline-*` with 5s TTL
- Use `printf '%b'` over `echo -e` for reliable escape handling

## Presets

**Minimal** (1-line):
```bash
generate-statusline.sh --items "model,context-pct,cost" --lines 1
```

**Standard** (2-line, recommended):
```bash
generate-statusline.sh --items "model,dir,git,git-sync,context-bar,cost-color,duration" --lines 2
```

**Full** (3-line):
```bash
generate-statusline.sh --items "model-full,dir,git,git-sync,worktree,agent,context-bar,tokens,warn-200k,cost-color,duration,lines-changed" --lines 3
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Not appearing | `chmod +x` the script; check `disableAllHooks` isn't `true` |
| Shows `--` or empty | Fields null before first API call; use `// 0` fallbacks |
| Colors garbled | Use `printf '%b'` instead of `echo -e` |
| Links not clickable | Terminal must support OSC 8 (iTerm2, Kitty, WezTerm) |
| Stale values after edit | Changes appear on next assistant message, not immediately |
| Script errors → blank | Non-zero exit or no output = blank status bar |

## See Also

- `context-bar` skill — quick context usage display (subset of this skill)
- [Official docs](https://code.claude.com/docs/en/statusline) — Claude Code statusline reference
- [ccstatusline](https://github.com/sirmalloc/ccstatusline) — community powerline-style statusline
