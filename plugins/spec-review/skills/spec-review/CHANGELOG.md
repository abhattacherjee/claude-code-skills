# Changelog

All notable changes to spec-review are documented here.

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
