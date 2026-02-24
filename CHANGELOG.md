# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own `CHANGELOG.md` within its directory.

Format: Monorepo-level events only. For per-skill change details, see `<skill>/CHANGELOG.md`.## [1.1.0] - 2026-02-24

Synced 6 skills from local source.

- `changelog-keeper` v1.0.0 — Keeps CHANGELOG.md up to date by generating categorized entries from git commit history
- `claudeception` v3.2.0 — Extracts reusable knowledge from work sessions and codifies it into Claude Code skills
- `conversation-search` v1.1.0 — Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries
- `skill-authoring` v2.1.0 — Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism
- `skill-publishing` v2.1.0 — Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags
- `worktree` v1.0.0 — Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch

## [2026-02-24] — Add worktree skill

- **Added** `worktree` v1.0.0 — creates isolated git worktrees for parallel Claude Code sessions
- Synced all 7 skills from local source
- Total skills: 7

## [2026-02-24] — Contribution workflow + sync fixes

- **Added** contribution workflow to all skills and monorepo root:
  - `CONTRIBUTING.md` — fork → branch → PR guidelines
  - `.github/PULL_REQUEST_TEMPLATE.md` — standardized PR checklist
  - `.github/workflows/validate-skill.yml` — CI validation on PRs
  - `scripts/validate-skill.sh` — portable skill quality checker
- **Applied** GitHub branch protection rulesets to all 7 repos (monorepo + 6 individual)
- **Fixed** `sync-individual-repos.sh` to skip READMEs with custom sections (preserves claudeception fork attribution)
- **Fixed** `validate-skill.sh` — `((var++))` arithmetic bug with `set -e`, missing `--help` flags
- **Synced** `skill-authoring` v2.0.0 → v2.1.0 (added `((var++))` bash pitfall to docs)
- **Restored** `claudeception/README.md` with original fork attribution and research references

## [2026-02-24] — Add claudeception and changelog-keeper

- **Added** `claudeception` v3.2.0 — extracts reusable knowledge from work sessions into skills
- **Added** `changelog-keeper` v1.0.0 — keeps CHANGELOG.md up to date from git commit history
- **Fixed** sync script to copy local READMEs instead of generating generic ones
- **Added** "Install all skills" section to monorepo README
- Total skills: 5

## [2026-02-24] — Initial monorepo release

- **Created** `claude-code-skills` monorepo with 3 skills:
  - `conversation-search` v1.1.0 — searches Claude Code conversation history
  - `skill-authoring` v2.0.0 — creates and optimizes Claude Code skills
  - `skill-publishing` v2.0.0 — publishes skills to GitHub repos and monorepo
- Auto-generated root README with skill catalog table
- MIT license
