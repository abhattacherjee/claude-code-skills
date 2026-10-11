---
name: create
description: "Creates and customizes Claude Code statusline scripts from 20 composable items (model, dir, git, git-sync, context-bar, cost, duration and more). Use when: (1) user wants to add or change their statusline, (2) user asks to show cost, git, context, or other info in the status bar, (3) user says 'customize my statusline' or 'add X to my statusline', (4) user wants to create a statusline from scratch, (5) debugging statusline display issues, (6) statusline-creator (the old name of this skill)."
metadata:
  version: 1.0.1
---

# Create a statusline

Creates Claude Code statusline scripts from composable items with full JSON schema awareness.

## Quick Generate

List the available items:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/generate-statusline.sh" --list
```

Generate a 2-line statusline with common items and point settings.json at it:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/generate-statusline.sh" --items "model,dir,git,git-sync,context-bar,cost,duration" --lines 2 --install
```

The script writes `~/.claude/statusline-command.sh` (or `--output PATH`). If that file exists and this plugin did not write it, the script leaves it alone and exits 3: ask the user before re-running with `--force`, which backs the old file up to `<file>.bak-<UTC time>` first. Exit codes: 0 written, 1 failed (a write failed, `jq` is missing, or `settings.json` cannot be read; a file that was not written is unchanged), 2 bad input (unknown flag or item, `--lines` not 1-3, `settings.json` not one JSON object), 3 refused.

Test it with mock data:

```bash
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

`--list` (above) prints each item with a one-line description, grouped as Display, Context, Cost & Time and Git. `git` caches its status for 5s; `git-sync` works with or without `git`, in any order.

## Writing Custom Items

If the generator doesn't cover your use case, write items manually. See **[references/item-recipes.md](references/item-recipes.md)** for copy-paste bash snippets for each item.

For the complete JSON schema with all available fields, see **[references/json-schema.md](references/json-schema.md)**.

### Key patterns:
- Always handle null: `jq -r '.field // 0'` or `jq -r '.field // empty'`
- ANSI colors: `\033[32m` green, `\033[33m` yellow, `\033[31m` red, `\033[0m` reset
- OSC 8 links: `\033]8;;URL\aText\033]8;;\a` (iTerm2, Kitty, WezTerm only), for http(s) URLs only
- Cache expensive ops: git results in `${XDG_CACHE_HOME:-~/.cache}/claude-statusline/` (mode 700, one file per directory, never through a symlink) with a 5s TTL, not in a shared temp dir
- Treat names as untrusted: strip control characters and backslashes before `echo -e` or `printf '%b'`, keep values out of printf format strings (`printf '%s'`), and pass numbers through a digits-only filter before `$(( ))`
- Run git as `git -c core.fsmonitor=false -c core.untrackedCache=false --no-optional-locks ...` so a repo's config cannot run a program on every prompt
- The recipes file starts with `clean`, `num`, `_git` and `unsafe_repo` helpers; every recipe below uses them, and a recipe you write yourself must too

## Presets

**Minimal** (1-line):
```bash
bash "${CLAUDE_SKILL_DIR}/scripts/generate-statusline.sh" --items "model,context-pct,cost" --lines 1
```

**Standard** (2-line, recommended):
```bash
bash "${CLAUDE_SKILL_DIR}/scripts/generate-statusline.sh" --items "model,dir,git,git-sync,context-bar,cost-color,duration" --lines 2
```

**Full** (3-line):
```bash
bash "${CLAUDE_SKILL_DIR}/scripts/generate-statusline.sh" --items "model-full,dir,git,git-sync,worktree,agent,context-bar,tokens,warn-200k,cost-color,duration,lines-changed" --lines 3
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

- `/statusline:context-bar` — one-off context usage check; the `context-bar` item here is the always-on version
- `/statusline:install` — the ready-made 3-tier adaptive statusline
- [Official docs](https://code.claude.com/docs/en/statusline) — Claude Code statusline reference
- [ccstatusline](https://github.com/sirmalloc/ccstatusline) — community powerline-style statusline
