# Changelog

All notable changes to this project will be documented in this file.

## [3.2.3] - 2026-02-28

### Added

- **Agent cross-reference validation** — `validate-plugin.sh` now scans SKILL.md files for agent path references (e.g., `agents/figma-ux-expert.md`) and warns if the referenced agent is not included in the plugin's `agents/` directory. Prevents silent omission of associated agents during plugin assembly.

## [3.2.2] - 2026-02-27

### Fixed

- **Plugin CHANGELOG preservation** — `sync-monorepo.sh --add-plugin` now preserves both README.md and CHANGELOG.md (previously only README was preserved)
- **Bash 3.2 compatibility** — replaced `declare -A` associative array with temp files for macOS default bash

## [3.2.1] - 2026-02-27

### Fixed

- **Plugin README preservation** — `sync-monorepo.sh --add-plugin` now preserves hand-written README.md files instead of overwriting them with the auto-generated template

## [3.2.0] - 2026-02-27

### Added

- **Auto-sync on publish** — when Monorepo or Plugin targets are selected in the Interactive Publishing Flow, the skill now automatically runs `sync-monorepo.sh`, commits, and pushes instead of leaving it as a manual step
- **Build artifact cleanup** — Post-Publish step now cleans up `build/` directories after publishing
- **Push-blocked fallback** — documents workaround when `prevent-direct-push` hook blocks monorepo pushes

### Changed

- **Interactive Publishing Flow** — Step 4 renamed from "Post-Publish" to "Auto-Sync to Monorepo", Step 5 is now "Post-Publish"
- **SKILL.md** — version bumped to 3.2.0

## [3.1.0] - 2026-02-27

### Added

- **Interactive Publishing Flow** — when invoked, detects current publishing state and presents a multiSelect prompt for target selection (individual repo, monorepo, plugin)
  - Dynamic labels show current state (e.g., "Monorepo (synced)", "Individual repo (published)")
  - Deselecting a published target triggers removal with confirmation
  - Post-publish step offers versioned release if monorepo was modified

### Changed

- **SKILL.md** — added "Interactive Publishing Flow" section before individual workflows
  - Version bumped to 3.1.0

## [3.0.0] - 2026-02-27

### Added

- **Plugin distribution support** — assemble, validate, and publish Claude Code plugins
- **scripts/prepare-plugin.sh** — assembles plugin from a JSON build manifest (`plugin-manifest.json`)
- **scripts/validate-plugin.sh** — validates assembled plugin structure (plugin.json, commands, skills)
- **scripts/install-plugin.sh** — consumer-facing installer/uninstaller for plugins
- **scripts/_lib.sh** — shared library extracted from all scripts (extract_field, extract_version, write_file, etc.)
- **Workflow E** in SKILL.md — full plugin publishing workflow (manifest → assemble → validate → sync → install)
- **Monorepo marketplace support** — auto-generates `.claude-plugin/marketplace.json` during sync
- **`/plugin` install instructions** — README shows `/plugin marketplace add` as recommended install method
- **Plugin section in monorepo README** — auto-generated table with plugin inventory
- **Plugin inventory in releases** — release script includes plugin count and inventory in CHANGELOG, tag, and summary
- **CI validation for plugins** — `validate-plugins` job in GitHub Actions workflow
- **PR template plugin checkboxes** — plugin.json validation, bundled skills, command frontmatter checks

### Changed

- **scripts/sync-monorepo.sh** — added `--add-plugin` flag, plugin discovery, README plugin section, marketplace.json generation
- **scripts/release-monorepo.sh** — includes plugin inventory in CHANGELOG entry, commit message, tag annotation
- **All existing scripts** — refactored to source `_lib.sh` shared library, removed duplicated helpers
- **SKILL.md** — version bumped to 3.0.0, description updated for plugin triggers

## [2.1.0] - 2026-02-24

### Added

- **scripts/release-monorepo.sh** — creates versioned releases of the monorepo with semver tags
  - `patch`, `minor`, `major` bump levels
  - `--dry-run` to preview without changes
  - `--github-user` override (auto-detects via `gh api`)
  - Reads current version from latest `v*` tag, calculates next version
  - Updates CHANGELOG top entry from "Monorepo sync" to versioned section
  - Creates annotated tag with skill inventory
  - Pushes branch + tag to origin

### Changed

- **SKILL.md** — added Workflow D (monorepo release) with bump level table
  - Updated Quick Reference with release commands
  - Updated description to mention versioned releases
  - Version bumped to 2.1.0

### Fixed

- **scripts/sync-monorepo.sh** — CHANGELOG generation now produces audit-style entries instead of duplicating per-skill changelogs
- **scripts/release-monorepo.sh** — version detection uses `git tag -l 'v[0-9]*'` instead of `git describe --tags` to avoid non-semver tags

## [2.0.0] - 2026-02-24

Monorepo support: publish skills to both individual repos and a shared `claude-code-skills` monorepo.

### Added

- **scripts/sync-monorepo.sh** — syncs skills from local source into a monorepo directory
  - `--init` flag to create and push the monorepo for the first time
  - `--add` flag to add new skills to an existing monorepo
  - `--dry-run`, `--skills`, `--github-user` flags
  - Auto-generates root README with catalog table from SKILL.md frontmatter
  - Auto-generates per-skill README with monorepo + individual install options
  - Detects individual repos via `gh repo view` and links them in the catalog
- **scripts/sync-individual-repos.sh** — syncs skills into their individual GitHub repos
  - `--all` flag to sync all skills with `.git` directories
  - `--push` flag to auto-commit and push changes
  - Updates README.md with monorepo install option
- **references/monorepo-readme-template.md** — template for the monorepo root README
  - Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`

### Changed

- **SKILL.md** — added Workflow B (monorepo sync) and Workflow C (individual repo sync)
  - Updated Quick Reference with new commands
  - Added architecture diagram showing source-of-truth flow
  - Updated description to mention monorepo support
- **references/readme-template.md** — added "Via monorepo" installation section
- **scripts/prepare-skill-repo.sh** — generated READMEs now include monorepo install option

## [1.0.0] - 2026-02-22

Initial public release.

### Included

- **SKILL.md** — workflow for converting any skill directory into a GitHub repo
  - Step-by-step guide: prepare files, review, init git, create repo, push
  - Key decisions table (why `.claude/` is gitignored, why MIT, etc.)
  - Known gotchas (`gh repo create` remote conflict, username discovery)
- **scripts/prepare-skill-repo.sh** — generates `.gitignore`, `LICENSE`, `CHANGELOG.md`, `README.md` from `SKILL.md` frontmatter
  - Dry-run mode, skip-existing safety, `--github-user` flag
- **references/readme-template.md** — template with install/update/uninstall/compatibility sections
