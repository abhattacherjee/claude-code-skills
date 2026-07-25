# Changelog

All notable changes to spec-review are documented here.

## [2.2.2] - 2026-07-25

### Fixed

- `discover-project-architecture.sh`: 13 detectors in `detect_data_flow`, `detect_i18n`,
  and `detect_security_patterns` combined `grep -rlq` (where `-q` suppresses the `-l`
  output) with a `| head -1 > /dev/null &&` guard that tests `head`'s exit status — always
  zero. Every data-flow, i18n and security pattern was reported as present for every
  project. This repository, which is markdown-only, reported `i18next, vue-i18n, CSRF,
  Helmet/CSP, GraphQL, REST-API` among others. The fabricated JSON is pasted verbatim into
  the Architecture Reviewer's prompt, so reviewers were being fed invented architecture on
  every run. (#62)
- `detect_data_flow`'s `Dev-proxy` guard was the only one without a `node_modules` filter,
  so a project whose sole `vite.config.*` was a vendored one under `node_modules/` reported
  `Dev-proxy`. It now filters vendored matches like the other twelve guards. (#62)

## [2.2.1] - 2026-07-25

### Fixed

- Replaced hardcoded `~/.claude/skills/spec-review/scripts/` invocations with
  skill-relative `./scripts/` paths, and added a "Path convention" note
  recording that a leading `./` means this skill's base directory while a
  bare path means the target project — including the bare `scripts/`
  reference in the Automation Integration checklist item (#59).
- README install step no longer instructs copying from `~/.claude/skills/`.
- Corrected the stale `implement-story` companion-skill name to
  `spec-implement` and dropped the non-working `/review-spec` alias in favor
  of `/spec-review` in the README (#59).
- Tightened the "Path convention" note to also cover `./references/…` paths
  explicitly (previously only `./scripts/…` was called out, leaving bare
  `references/...` ambiguous between skill-relative and target-project
  meanings); prefixed the README's `scripts/…` invocations with `./` to match (#60).
- The Design Simplifier agent prompt template referenced
  `references/design-simplification-checklist.md` by path, but a spawned
  sub-agent cannot resolve a path relative to the parent skill's base
  directory — replaced with an instruction to inline the file's full contents
  into the prompt instead of passing the path (#60).
- Added a blockquote noting the Phase 2 `feature-dev:code-explorer` /
  `feature-dev:code-architect` agent types require the separately-installed
  `feature-dev` plugin, with `general-purpose` as the documented fallback;
  softened the "Notes" section's unconditional claim that feature-dev's
  agents are reused into a conditional statement covering that fallback (#59).
- README's `### Manual` install heading contained only a marketplace
  one-liner, contradicting its own title; retitled to `### Via Marketplace`
  and reordered ahead of the monorepo clone steps so the simpler
  marketplace path reads as the recommended install method (#59).

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
