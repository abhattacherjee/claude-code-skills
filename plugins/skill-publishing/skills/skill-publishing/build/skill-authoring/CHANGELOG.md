# Changelog

All notable changes to this project will be documented in this file.

## [2.2.0] - 2026-02-27

### Added

- **Incomplete CLI templates anti-pattern** — warns that agents improvise missing fields (labels, assignees, milestones) with plausible-but-wrong values; include ALL metadata flags explicitly in agent prompt templates

## [2.1.0] - 2026-02-24

### Added

- **`((var++))` bash arithmetic pitfall** — documents how `set -e` causes `((var++))` to exit when var is 0 (returns exit code 1), with fix: use `var=$((var + 1))` instead

## [2.0.0] - 2026-02-18

Initial public release.

### Included

- **SKILL.md** — full skill definition covering the complete skill authoring lifecycle:
  - Core principles (decompose, parallelize, script-first, concise, progressive disclosure)
  - Frontmatter rules and description writing
  - Directory layout conventions (`SKILL.md + scripts/ + references/`)
  - Script extraction guidelines with `set` flag pitfalls
  - Agent and orchestration design (orchestrator pattern, sub-agent specialization, parallelization)
  - New skill creation workflow with decomposition and script-first evaluation
  - Skill templates (simple script-only and complex orchestrator + agents)
  - Quality checklist (inline summary)
  - Anti-patterns to avoid
  - Optimization workflow for existing skills
- **references/quality-checklist.md** — detailed pre-publish verification checklist with verification commands
