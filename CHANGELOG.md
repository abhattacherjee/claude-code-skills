# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own `CHANGELOG.md` within its directory.

Format: Monorepo-level events only. For per-skill change details, see `<skill>/CHANGELOG.md`.

## [1.5.2] - 2026-02-27

### Fixed

- preserve plugin CHANGELOG.md during sync, bash 3.2 compat

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.2 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.1] - 2026-02-27

### Fixed

- preserve plugin READMEs during --add-plugin sync

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.1 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.5.0] - 2026-02-27

### Changes

- Sync skill-publishing v3.2.0: auto-sync on publish

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.2.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.1] - 2026-02-27

### Changed

- enrich plugin READMEs with detailed feature descriptions and usage

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.4.0] - 2026-02-27

### Added

- add skill-authoring and skill-publishing as plugins

### Changed

- remove stale individual repo links for skill-authoring and skill-publishing

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (3 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo, and plugin assembly/distribution

## [1.3.0] - 2026-02-27

### Added

- add interactive publishing flow with target selection

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.1] - 2026-02-27

### Added

- add plugin marketplace support

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.2.0] - 2026-02-27

### Added

- add plugin support + git-flow plugin (skill-publishing v3.0.0)

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.2.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v3.0.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

### Plugin Inventory (1 plugins)

- `git-flow` v2.0.0 — Git Flow branching workflow with slash commands and diagnostic tools

## [1.1.2] - 2026-02-24

### Fixed

- sync changelog-keeper v1.1.1 + release-monorepo.sh newline fix

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.1 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.1] - 2026-02-24

### Added

- sync validate-skill.sh with version-mismatch check

### Changed

- sync skill-authoring v2.1.0 CHANGELOG entry
- sync changelog-keeper v1.1.0 — multi-script CHANGELOG coordination

### Skill Inventory (6 skills)

- `changelog-keeper` v1.1.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [1.1.0] - 2026-02-24

### Added

- `worktree` v1.0.0 — creates isolated git worktrees for parallel Claude Code sessions
- `claudeception` v3.2.0 — extracts reusable knowledge from work sessions into skills
- `changelog-keeper` v1.0.0 — keeps CHANGELOG.md up to date from git commit history
- `release-monorepo.sh` — versioned release workflow with semver tags (patch/minor/major)
- Contribution workflow for all repos: CONTRIBUTING.md, PR template, CI validation, branch protection rulesets
- "Install all skills" section in monorepo README

### Changed

- CHANGELOG rewritten as audit log (was duplicating per-skill changelogs on every sync)
- `sync-monorepo.sh` generates compact skill inventory instead of dumping full per-skill changelogs
- `sync-individual-repos.sh` skips READMEs with custom sections (preserves claudeception fork attribution)
- `skill-authoring` v2.0.0 → v2.1.0 (added `((var++))` bash pitfall docs)
- `skill-publishing` v2.0.0 → v2.1.0 (added release-monorepo.sh, Workflow D)

### Fixed

- `validate-skill.sh` — `((var++))` arithmetic bug with `set -e`, missing `--help` flags
- `sync-monorepo.sh` — copy local READMEs instead of generating generic ones
- Restored `claudeception/README.md` with original fork attribution and research references

### Skill Inventory (7 skills)

- `changelog-keeper` v1.0.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history by topic, date, branch, or project
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices
- `skill-publishing` v2.1.0 — Publishes skills to GitHub repos and monorepo with versioned releases
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions

## [1.0.0] - 2026-02-24

### Added

- Initial monorepo with 3 skills:
  - `conversation-search` v1.1.0 — searches Claude Code conversation history
  - `skill-authoring` v2.0.0 — creates and optimizes Claude Code skills
  - `skill-publishing` v2.0.0 — publishes skills to GitHub repos and monorepo
- Auto-generated root README with skill catalog table
- MIT license
