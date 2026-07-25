# Changelog

## [1.0.0] - 2026-07-25

Initial plugin release.

### Added

- `spec-implement` skill published as a marketplace plugin (#59).
- Bundled `references/delegated-verification.md` so the delegated-work
  verification step resolves without the `ship` skill installed.

### Fixed

- Script invocations use bare-relative `scripts/` paths rather than
  `~/.claude/skills/spec-implement/scripts/`.
