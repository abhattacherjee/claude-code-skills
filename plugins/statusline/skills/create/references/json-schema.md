# Statusline JSON Schema Reference

Claude Code pipes this JSON to your statusline script via stdin after each assistant message.

## Full JSON Structure

```json
{
  "cwd": "/current/working/directory",
  "session_id": "abc123...",
  "transcript_path": "/path/to/transcript.jsonl",
  "model": {
    "id": "claude-opus-4-6",
    "display_name": "Opus"
  },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/original/project/directory"
  },
  "version": "2.1.75",
  "output_style": {
    "name": "default"
  },
  "cost": {
    "total_cost_usd": 0.01234,
    "total_duration_ms": 45000,
    "total_api_duration_ms": 2300,
    "total_lines_added": 156,
    "total_lines_removed": 23
  },
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "used_percentage": 8,
    "remaining_percentage": 92,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  },
  "exceeds_200k_tokens": false,
  "vim": { "mode": "NORMAL" },
  "agent": { "name": "security-reviewer" },
  "worktree": {
    "name": "my-feature",
    "path": "/path/to/.claude/worktrees/my-feature",
    "branch": "worktree-my-feature",
    "original_cwd": "/path/to/project",
    "original_branch": "main"
  }
}
```

## Field Reference

| Field | Type | Description | Null/Absent? |
|-------|------|-------------|--------------|
| `model.id` | string | Model identifier (e.g., `claude-opus-4-6`) | Never |
| `model.display_name` | string | Short name (e.g., `Opus`) | Never |
| `cwd` | string | Current working directory | Never |
| `workspace.current_dir` | string | Same as `cwd` (preferred) | Never |
| `workspace.project_dir` | string | Directory where Claude Code launched | Never |
| `workspace.added_dirs` | string[] | Additional added directories | May be empty |
| `session_id` | string | Unique session ID | Never |
| `transcript_path` | string | Path to conversation transcript | Never |
| `version` | string | Claude Code version | Never |
| `output_style.name` | string | Current output style name | Never |
| `cost.total_cost_usd` | number | Session cost in USD | Never |
| `cost.total_duration_ms` | number | Wall-clock time since session start | Never |
| `cost.total_api_duration_ms` | number | Time waiting for API responses | Never |
| `cost.total_lines_added` | number | Lines of code added | Never |
| `cost.total_lines_removed` | number | Lines of code removed | Never |
| `context_window.total_input_tokens` | number | Cumulative input tokens (all calls) | Never |
| `context_window.total_output_tokens` | number | Cumulative output tokens (all calls) | Never |
| `context_window.context_window_size` | number | Max context (200000 or 1000000) | Never |
| `context_window.used_percentage` | number | Pre-calculated % used | **May be null** early |
| `context_window.remaining_percentage` | number | Pre-calculated % remaining | **May be null** early |
| `context_window.current_usage` | object | Token counts from last API call | **null** before first call |
| `exceeds_200k_tokens` | boolean | Whether last response exceeded 200k tokens | Never |
| `vim.mode` | string | `NORMAL` or `INSERT` | **Absent** unless vim mode enabled |
| `agent.name` | string | Agent name | **Absent** unless `--agent` flag |
| `worktree.name` | string | Worktree name | **Absent** unless `--worktree` |
| `worktree.path` | string | Worktree directory path | **Absent** unless `--worktree` |
| `worktree.branch` | string | Worktree git branch | **Absent** for hook-based worktrees |
| `worktree.original_cwd` | string | Pre-worktree directory | **Absent** unless `--worktree` |
| `worktree.original_branch` | string | Pre-worktree branch | **Absent** for hook-based worktrees |

## Context Window Details

- `used_percentage` = `(input_tokens + cache_creation_input_tokens + cache_read_input_tokens) / context_window_size * 100`
- Does NOT include `output_tokens`
- `current_usage` is null before first API call — always use `// 0` or `or 0` fallbacks
- `total_input_tokens` / `total_output_tokens` are cumulative across session (may exceed context_window_size)

## Timing

- Runs after each assistant message, permission mode change, or vim mode toggle
- Debounced at 300ms
- If a new update triggers while script is running, in-flight execution is cancelled
- Script changes don't take effect until next assistant message

## Output Capabilities

- **Multiple lines**: each `echo`/`print` = separate row
- **ANSI colors**: `\033[32m` (green), `\033[33m` (yellow), `\033[31m` (red), `\033[0m` (reset)
- **Bold/dim**: `\033[1m` (bold), `\033[2m` (dim)
- **OSC 8 links**: `\033]8;;URL\aText\033]8;;\a` (clickable in iTerm2, Kitty, WezTerm)
- **Padding**: `"padding": N` in settings.json adds N chars of horizontal spacing
