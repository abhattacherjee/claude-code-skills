# Changelog

## [1.0.0] - 2026-03-13

### Added
- `/context-bar` slash command — shows a quick context usage progress bar
- `statusline-command.sh` — color-coded statusline with context bar, model, dir, git branch
- `context-bar.sh` — standalone context estimator from JSONL transcript
- Color thresholds: green (<50%), amber (50-79%), red (80%+)
- Uses `context_window.used_percentage` from Claude Code's statusline JSON
