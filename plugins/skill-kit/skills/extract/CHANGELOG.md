# Changelog

All notable changes to the **extract** skill (was `claudeception`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `skill-kit` plugin as `skill-kit:extract` (#161). Same extraction workflow as `claudeception` 3.2.0. The old name and `/claudeception` still match as trigger phrases.
- Cross-references name `skill-kit:author`. `scripts/claudeception-activator.sh` tells Claude to use `Skill(skill-kit:extract)`. The hook stays opt-in: the plugin does not register it.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

## History before 1.0.0 (as `claudeception`)

### claudeception 3.2.0 - 2026-02-24

Initial public release.

#### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`
