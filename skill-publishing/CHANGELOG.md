# Changelog

All notable changes to this project will be documented in this file.

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
