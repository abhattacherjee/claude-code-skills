# Changelog — github-board-move

All notable changes to the **github-board-move** skill are documented here.

## [1.0.0] - 2026-06-03

### Added

- Initial release. `scripts/board-move.sh` moves a GitHub issue/PR's Project (v2) card to a target Status column — board discovery, Status field/option lookup, fuzzy (exact → unique-substring) column matching, `--list-status`, `--dry-run`, `--add` (adds the card if missing), and a `project` auth-scope check. Reuses the proven GraphQL patterns from `github-release-board-promote`. (#28)
