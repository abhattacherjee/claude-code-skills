# Changelog — move-card

All notable changes to the **move-card** skill (was `github-board-move`) are documented here.

## [2.1.0] - 2026-10-07

### Added
- An `--issue` moved to a post-merge column also gets the next-release milestone: `milestones.next_release["owner/repo"]` from the github-board config, else the open milestone with the lowest version (`vX.Y` or `vX.Y.Z`, sorted by version, not number). It prints `milestone: <current|none> -> <title>` or `milestone: unchanged (<title>)`; `--dry-run` prints `would set milestone: …` and writes nothing. A post-merge column's resolved name is "Development Complete", "Dev Complete" or "Done in develop" (any case), or one in `move_card.post_merge_columns`, which replaces those names (an empty list turns this off). `--pr` moves and other columns make no milestone call. The card moves first. No candidate, a wrong configured title, an unreadable milestone list, a failed write, or a reply naming another milestone prints a warning and keeps the move's exit code. The write is `gh api -X PATCH repos/O/R/issues/N -F milestone=<number>`, and the current milestone comes from the item lookup, not an extra call. (#204)

## [2.0.0] - 2026-10-02

### Added
- `board-move.sh` caches the board list and Status options for 7 days. A failed move, a `--to` column missing from the cached options, or a card not found on the cached board (checked before `--add` adds it anywhere), or a cached board number that no longer resolves (the board was deleted) triggers one refetch; a rate-limit or missing-scope error never does. `--no-cache` skips the cache. Cache keys are `(owner, repo[, board])` tuples, so `a-b/c` and `a/b-c` never share an entry. (#146)

### Fixed
- Owner, repo and node ids go to GraphQL with `-f` (string), not `-F`, which sent an all-numeric owner or repo as an Int. (#146)

### Changed
- **Renamed to `move-card`** and moved into the `github-board` plugin (#146). Invoke it as `/github-board:move-card`. The old name still matches as a trigger phrase.

## [1.0.0] - 2026-06-03

### Added

- Initial release. `scripts/board-move.sh` moves a GitHub issue/PR's Project (v2) card to a target Status column — board discovery, Status field/option lookup, fuzzy (exact → unique-substring) column matching, `--list-status`, `--dry-run`, `--add` (adds the card if missing), and a `project` auth-scope check. Reuses the proven GraphQL patterns from `github-release-board-promote`. (#28)
