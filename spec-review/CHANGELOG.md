# Changelog

All notable changes to spec-review are documented here.

## [2.2.1] - 2026-07-25

### Fixed

- Replaced hardcoded `~/.claude/skills/spec-review/scripts/` invocations with
  bare-relative `scripts/` paths so the skill resolves from the plugin cache (#59).
- README install step no longer instructs copying from `~/.claude/skills/`.

### Changed

- Authoring source now lives in the monorepo at `spec-review/`.

## [2.2.0] - 2026-03-17

### Added
- **Team Mode (Optional)** — Phase 2 can use Agent Teams instead of parallel sub-agents when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is enabled; enables cross-pollination between reviewers (e.g., Codebase Verifier alerts Architecture Reviewer about missing files mid-review)

## [2.1.0] - 2026-03-14

### Added
- **Bruno API test plan generation** — parallel sub-agent designs AC-to-Bruno test mappings with folder placement following project conventions
- **Architecture alignment verification** — checks specs against MCP/backend/frontend boundary rules
- **Design simplification checklist** — reference file with common over-engineering patterns to flag

## [2.0.0] - 2026-02-24

### Changed
- **BREAKING: 4-agent parallel review** replaces sequential single-pass review
- Codebase Verifier, Architecture Checker, Simplification Advisor, and Bruno Test Planner run simultaneously
- Dynamic project architecture discovery via `discover-project-architecture.sh`
- Section extraction via `extract-spec-sections.sh` for targeted agent prompts

## [1.0.0] - 2026-02-20

### Added
- Initial version with single-pass spec review
- Sub-task verification against codebase (grep for file paths, function names)
- Acceptance criteria completeness check
