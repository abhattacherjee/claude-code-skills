# Changelog

All notable changes to the **extract** skill (was `claudeception`) are documented here.

## [1.2.0] - 2026-10-09

### Changed

- The bundled `scripts/validate-skill.sh` (a byte-identical copy of the repo-root validator) has new checks. It fails a SKILL.md body of 500 lines or more (it passed exactly 500, and missed a last line with no newline); a name containing `anthropic` or `claude`; a `.md` file that SKILL.md does not name and no script in `scripts/` reads; and a `.md` file over 100 lines with no `## Contents` heading in its first 30 lines. CONTRIBUTING.md and files under a dot-directory such as `.github/` are not checked (#214).

## [1.1.0] - 2026-10-09

### Added

- `find-skills.sh` exits 3 when `rg` itself fails (a bad pattern or an unreadable file), so that is never read as "nothing found" (1) or a missing tool (2) (#210).
- `scripts/find-skills.sh` runs Step 1, the search for existing skills: it lists or searches (`rg` arguments) the project, user and active plugin-install skill directories, and `--dirs` prints them. It exits 2 when `rg` or `python3` is missing or no skill directory exists. It replaces the ~50-line inline script in SKILL.md (#210).

## [1.0.1] - 2026-10-05

### Changed

- The bundled `scripts/validate-skill.sh` changed in comments and help text only: its usage example names a plugin skill path instead of the deleted `changelog-keeper/` directory, and its NOTE names the skills that ship a byte-identical copy and the frozen `skill-authoring` copy as the exception (#167).

## [1.0.0] - 2026-10-04

### Added

- `LICENSE`: the upstream MIT license and copyright notice of [blader/Claudeception](https://github.com/blader/Claudeception).

### Changed

- Moved into the `skill-kit` plugin as `skill-kit:extract` (#161). Same extraction workflow as `claudeception` 3.2.0. The old name and `/claudeception` still match as trigger phrases.
- Cross-references name `skill-kit:author`. `scripts/claudeception-activator.sh` tells Claude to use `Skill(skill-kit:extract)`. The hook stays opt-in: the plugin does not register it.
- `scripts/validate-skill.sh` is a copy of the repo-root `scripts/validate-skill.sh`.

### Fixed

- Step 1 searched all of `~/.claude/plugins/cache` and `~/.claude/plugins/marketplaces` (323 SKILL.md files on one machine, many of them old versions or plugins that are not installed). It now searches only active installs: each `installPath` in `~/.claude/plugins/installed_plugins.json` (read with python3), at user scope or this project's scope. A missing or unreadable file prints a note and skips plugin skills.
- Step 1 keeps a project-scope install when the current directory is the project or inside it. It used to match only the project root, so a search from a subdirectory such as `<project>/src` missed the project's installs and could lead to a duplicate skill.
- A match inside an installed plugin is no longer "Update existing" in place: the install is a cache copy. Edit the plugin's source only when its marketplace is a `directory` source the user owns; otherwise create a new user skill and point to the plugin's source repo.

## History before 1.0.0 (as `claudeception`)

### claudeception 3.2.0 - 2026-02-24

Initial public release.

#### Included

- **SKILL.md** — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills.
- **scripts/** — automation scripts:  - `claudeception-activator.sh`
