# Changelog

All notable changes to this project will be documented in this file.

## [2.6.3] - 2026-10-06

### Changed

- The plugin version jumps from 2.3.2 to 2.6.3, so it matches the version line of this CHANGELOG. The skill stays at 2.6.2.
- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).
- plugin.json carries the "Deprecated: …" description that only marketplace.json had (#190).

## [2.6.2] - 2026-10-05

### Changed

- The "Companion Skills" link and the GitHub link now point at the `skill-kit` plugin, which replaced this one. They named the bare `claudeception/` and `skill-authoring/` directories, which are deleted (#167).
- The bundled `validate-skill.sh` usage example no longer names the deleted `changelog-keeper/` directory.

## [2.6.1] - 2026-10-02

### Changed

- **SKILL.md is back under the 500-line limit** (621 → 474 lines). Two whole sections moved verbatim into references, each replaced by a one-line pointer: "Agent Teams Orchestration" → `references/agent-teams.md`, "Skill Template" → `references/skill-templates.md`. No content was rewritten. `validate-skill.sh` passes again, which unblocks edits to this skill.
- Examples name `triage-issues` (github-board plugin), the new name of `github-issue-triage` (#146). This resolves the skill-authoring part of #17.

## [2.6.0] - 2026-03-20

### Added

- **MCP Tool Constraint section** under Agent & Orchestration Design — documents that Agent Teams teammates and sub-agents cannot call MCP tools (permission deadlock). Provides the "Lead Reads, Agents Analyze" workaround pattern. Applies to all MCP servers (Figma, Sentry, Railway, etc.). Discovered during prd-creator skill development where team agents deadlocked on Figma MCP permission requests.

## [2.5.0] - 2026-03-17

### Added

- **Agent Teams Orchestration section** — when to use Teams (persistent, inter-agent communication) vs Sub-Agents (one-shot, parallel fan-out). Includes team orchestration pattern (TeamCreate → TaskCreate → named teammates → SendMessage → TeamDelete), conditional usage pattern for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, and complex skill template (teams variant).
- **"Teams?" column** in "When to Use Agents" table — indicates which signals warrant team-based orchestration
- **Teams quality checklist** — 4 items covering team mode evaluation, conditional feature flag check, and TeamDelete cleanup
- **Anti-pattern** — "Using teams for one-shot parallel work" warns that teams add overhead vs sub-agents for independent fan-out

## [2.4.0] - 2026-03-06

### Added

- **Dry-run testing phase (Step 12)** — every skill with scripts must be dry-run tested against real project data before release. Documents common failure patterns: regex mismatches, `grep` pipe chains where `head` causes SIGPIPE, `find` including coverage/build artifacts, and classification heuristics that misfire on edge cases.
- **Quality checklist item** — "Scripts dry-run tested against real project data (2-3 varied inputs)"
- **Anti-pattern** — "Untested scripts shipped as done" warns against scripts that pass code review but fail on real data; bugs cluster, so test adjacent heuristics when one fails.

## [2.3.0] - 2026-03-05

### Added

- **Progress tracking for long-running workflows** — skills with 3+ sequential phases now get a task manifest script (`scripts/task-manifest.sh`) that emits TaskCreate-compatible JSON per workflow
- **`scripts/generate-task-manifest.sh`** — scaffolding tool that generates task-manifest.sh with placeholder tasks for each workflow (`--skill-dir`, `--workflows "name:count"`)
- **`references/task-tracking-pattern.md`** — full reference with task manifest template, field table, update patterns (sequential, sub-agent, abort), and real-world examples (dependabot 8 tasks, issue-triage 5 tasks, catalog-maintainer 6 tasks)
- **Core Principle #8** — "Track progress for long workflows" requiring task manifest for skills with 3+ phases
- **Progress Tracking Evaluation (Step 5)** in the new-skill creation workflow
- **Progress tracking section** in quality checklist (`references/quality-checklist.md`)
- **Anti-pattern** — "Silent long-running workflows" warns against skills without task visibility

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
