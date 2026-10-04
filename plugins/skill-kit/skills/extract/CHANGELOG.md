# Changelog

All notable changes to the **extract** skill (was `claudeception`) are documented here.

## [1.0.0] - 2026-10-04

### Added

- `LICENSE`: the upstream MIT license and copyright notice of [blader/Claudeception](https://github.com/blader/Claudeception).

### Changed

- Moved into the `skill-kit` plugin as `skill-kit:extract` (#161). Same extraction workflow as `claudeception` 3.2.0. The old name and `/claudeception` still match as trigger phrases.
- Cross-references name `skill-kit:author`. `scripts/claudeception-activator.sh` tells Claude to use `Skill(skill-kit:extract)`. The hook stays opt-in: the plugin does not register it.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

### Fixed

- Step 1 searched all of `~/.claude/plugins/cache` and `~/.claude/plugins/marketplaces` (323 SKILL.md files on one machine, many of them old versions or plugins that are not installed). It now searches only active installs: each `installPath` in `~/.claude/plugins/installed_plugins.json` (read with python3), at user scope or this project's scope. A missing or unreadable file prints a note and skips plugin skills.
- A match inside an installed plugin is no longer "Update existing" in place: the install is a cache copy. Edit the plugin's source only when its marketplace is a `directory` source the user owns; otherwise create a new user skill and point to the plugin's source repo.

## History before 1.0.0 (as `claudeception`)

### claudeception 3.2.0 - 2026-02-24

Initial public release.

#### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`
