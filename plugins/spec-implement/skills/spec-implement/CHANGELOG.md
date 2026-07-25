# Changelog

All notable changes to spec-implement are documented here.

## [1.0.0] - 2026-07-25

Initial plugin release.

### Added

- `spec-implement` skill published as a marketplace plugin (#59).
- Bundled `references/delegated-verification.md` so the delegated-work
  verification step resolves without the `ship` skill installed.

### Fixed

- Script invocations use bare-relative `scripts/` paths rather than
  `~/.claude/skills/spec-implement/scripts/`.
- Prefixed skill-owned script invocations with `./` and added a "Path
  convention" note after the title clarifying they resolve against this
  skill's base directory, not the Bash tool's working directory (#59).
- Delegation matrix and Phase 3 now reference `Skill(superpowers:brainstorming)`
  (its real registered name) instead of the unqualified `Skill(brainstorming)`,
  and flag `Skill(ui-from-requirements)` as requiring a separately installed
  skill (#59).
