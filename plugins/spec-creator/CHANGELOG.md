# Changelog

All notable changes to spec-creator are documented here.

## [2.4.0] - 2026-03-17

### Added
- **Team Mode note** — Phase 2/3 agents can be persistent teammates when Agent Teams is enabled, allowing iterative refinement via SendMessage

## [2.3.0] - 2026-03-16

### Added
- **UX design gate** (Phase 4.4) — conditional Figma mockup step using `/figma-ui-designer` for stories touching frontend UI; auto-skipped for backend/API/config changes
- **Metrics Scout agent** (Phase 2, Agent 3) — parallel sub-agent discovers existing observability infrastructure, identifies success metrics, recommends capture methods (Sentry spans, custom metrics, Bruno assertions)
- **Success Metrics section** (template Section 7) — tabular format with metric/type/current/target/capture-method; existing instrumentation reuse + new instrumentation needed
- **Clarifying questions** (Phase 3.0) — 1-3 targeted questions about purpose, constraints, scope boundaries before proposing approaches
- **YAGNI and design-for-isolation rules** in brainstorming phase
- **Lead with recommendation** — present recommended option first with reasoning

## [2.0.0] - 2026-03-16

### Changed
- **BREAKING: Implementation Tasks replace Detailed Sub-Tasks** — specs now include bite-sized TDD steps with complete code, exact run commands, expected output, checkbox syntax, and commit points (inspired by superpowers:writing-plans)
- **File Structure Map** (template Section 8) — tabular overview of all files to create/modify with line numbers, listed before implementation tasks
- Section numbering: 7→Success Metrics, 8→File Structure Map, 9→Implementation Tasks, 10→Testing Checklist, 11→Definition of Done

## [1.5.0] - 2026-03-14

### Added
- Initial public version with 5-phase workflow
- Convention discovery script
- Parallel codebase research (Feature Scout + Convention Scanner)
- Brainstorming with vertical splitting triggers
- Codebase State verification gate
- Dependency upgrade pre-flight (CJS/ESM compatibility check)
- Post-creation review chaining to `/spec-review`
