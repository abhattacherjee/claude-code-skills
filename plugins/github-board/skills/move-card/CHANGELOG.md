# Changelog — move-card

All notable changes to the **move-card** skill (was `github-board-move`) are documented here.

## [2.0.0] - 2026-10-02

### Added
- `board-move.sh` caches the board list and Status options for 7 days. A failed move or a `--to` column missing from the cached options triggers one refetch; `--no-cache` skips the cache. (#146)

### Changed
- **Renamed to `move-card`** and moved into the `github-board` plugin (#146). Invoke it as `/github-board:move-card`. The old name still matches as a trigger phrase.

## [1.0.0] - 2026-06-03

### Added

- Initial release. `scripts/board-move.sh` moves a GitHub issue/PR's Project (v2) card to a target Status column — board discovery, Status field/option lookup, fuzzy (exact → unique-substring) column matching, `--list-status`, `--dry-run`, `--add` (adds the card if missing), and a `project` auth-scope check. Reuses the proven GraphQL patterns from `github-release-board-promote`. (#28)
