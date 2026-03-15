# Changelog

## [1.2.0] - 2026-03-15

### Changed
- Git sync indicators: `⇡⇣` double arrows with color coding (cyan=synced, green=ahead, yellow=behind, red=diverged, dim=no remote)
- Replaced `ok`/`+N`/`-N`/`local` with `⇡⇣`/`⇡N`/`⇣N`/`?`

## [1.1.0] - 2026-03-14

### Added
- Dynamic single/two-line layout based on content width (no fixed breakpoints)
- tmux window width detection via `tmux display-message -p '#{window_width}'`
- Parent process TTY detection via `ps -o tty= -p $PPID` + `stty size`
- Folder name shown in narrow tier (was previously hidden)

### Fixed
- Terminal width detection in Claude Code pipe context (no /dev/tty access)
- Width detection in tmux sessions (adapts when switching iPhone/iPad/Mac)
- `${#MODEL}` vs `${#DISPLAY_MODEL}` mismatch in width calculation

## [1.0.0] - 2026-03-14

### Added
- 4-tier adaptive statusline (ultra-narrow, narrow, medium, wide)
- Icons: folder, git branch, context usage
- Git info: branch name with compact sync status
- Context bar with color-coded progress (green/yellow/red)
- Robust terminal width detection for SSH/pipe contexts
- Install script that copies statusline and updates settings.json
