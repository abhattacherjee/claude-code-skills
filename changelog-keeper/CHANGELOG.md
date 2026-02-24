# Changelog

All notable changes to this project will be documented in this file.

## [1.1.1] - 2026-02-24

### Fixed

- **Bash Newline Pitfall** — corrected the fix: `printf '%s\n\n'` inside `$()` also loses trailing newlines. The real fix is adding blank lines at the concatenation point, not in the variable assignment.

## [1.1.0] - 2026-02-24

### Added

- **Multi-Script CHANGELOG Coordination** section — patterns for when multiple scripts (sync + release) modify the same CHANGELOG
  - Format-aware detection to prevent sync entries from clobbering release entries
  - Bash newline pitfall with `printf` fix
  - Semver tag filtering (`git tag -l 'v[0-9]*'` vs `git describe --tags`)

## [1.0.0] - 2026-02-24

Initial public release.

### Included

- **SKILL.md** — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.
- **scripts/** — automation scripts:  - `update-changelog.sh`
