# Changelog

All notable changes to the **author** skill (was `skill-authoring`) are documented here.

## [1.0.2] - 2026-10-09

### Changed

- The supported frontmatter fields, in SKILL.md and the checklist, match `validate-skill.sh`: `name`, `description`, `metadata`, `model`, `disable-model-invocation` (#210).
- `references/quality-checklist.md` is now linked from the workflow (step 11) and the Quality Checklist section, which replaces the inline copy. The inline items it lacked (decomposition and agents, teams, dry-run testing) moved into it, and it starts with a Contents list. Its body-length, description-length and frontmatter commands now match the current rules (`metadata.version`, under 500 lines, a single-line description) (#210).
- Cut repeats: principle 7 merged into principle 4, the `set -e` pitfall list down to its rule and the two incident-backed pitfalls (`((var++))` at 0, `while read` at the end of a pipe), and the anti-patterns that restated a rule above (#210).
- `references/task-tracking-pattern.md` starts with a Contents list (#210).

## [1.0.1] - 2026-10-05

### Changed

- The bundled `scripts/validate-skill.sh` changed in comments and help text only: its usage example names a plugin skill path instead of the deleted `changelog-keeper/` directory, and its NOTE names the skills that ship a byte-identical copy and the frozen `skill-authoring` copy as the exception (#167).

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `skill-kit` plugin as `skill-kit:author` (#161). Same content as `skill-authoring` 2.6.1. The old name still matches as a trigger phrase.
- Cross-references name the new skills (`skill-kit:extract`, `skill-kit:publish`). The task-manifest command runs through `${CLAUDE_SKILL_DIR}`.
- `scripts/validate-skill.sh` is now a copy of the repo-root `scripts/validate-skill.sh`.

### Fixed

- `references/skill-templates.md`: the two skill templates sat in a three-backtick `markdown` fence that held three-backtick `bash` fences, so the first inner fence closed the template early and the rest rendered as plain text. They are now four-backtick fences. The templates write script calls as `<SKILL_SCRIPTS>/<name>.sh`, and SKILL.md says what to write in its place (`"${CLAUDE_SKILL_DIR}/scripts/<name>.sh"`). They used `./scripts/<name>.sh`, which fails from the user's project.
- The Paths note told you to call a new skill's scripts as the `${CLAUDE_SKILL_DIR}` path, written in prose. Claude Code replaces that token everywhere in a SKILL.md, so the model read (and copied) the author skill's own absolute path. SKILL.md now spells the variable out in parts outside code blocks, and `references/skill-templates.md` has a "Script paths" section that says what `<SKILL_SCRIPTS>` stands for. `references/task-tracking-pattern.md` says what `<SKILL_SCRIPTS>` and `<SCRIPTS_DIR>` stand for.
- `references/quality-checklist.md`: the cross-reference check read `$f` through a `while read f` at the end of a pipe. It is now a `for` loop.

## History before 1.0.0 (as `skill-authoring`)

### skill-authoring 2.6.1 - 2026-10-02

#### Changed

- **SKILL.md is back under the 500-line limit** (621 → 474 lines). Two whole sections moved verbatim into references, each replaced by a one-line pointer: "Agent Teams Orchestration" → `references/agent-teams.md`, "Skill Template" → `references/skill-templates.md`. No content was rewritten. `validate-skill.sh` passes again, which unblocks edits to this skill.
- Examples name `triage-issues` (github-board plugin), the new name of `github-issue-triage` (#146). This resolves the skill-authoring part of #17.

### skill-authoring 2.6.0 - 2026-03-20

#### Added

- **MCP Tool Constraint section** under Agent & Orchestration Design — documents that Agent Teams teammates and sub-agents cannot call MCP tools (permission deadlock). Provides the "Lead Reads, Agents Analyze" workaround pattern. Applies to all MCP servers (Figma, Sentry, Railway, etc.). Discovered during prd-creator skill development where team agents deadlocked on Figma MCP permission requests.

### skill-authoring 2.5.0 - 2026-03-17

#### Added

- **Agent Teams Orchestration section** — when to use Teams (persistent, inter-agent communication) vs Sub-Agents (one-shot, parallel fan-out). Includes team orchestration pattern (TeamCreate → TaskCreate → named teammates → SendMessage → TeamDelete), conditional usage pattern for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, and complex skill template (teams variant).
- **"Teams?" column** in "When to Use Agents" table — indicates which signals warrant team-based orchestration
- **Teams quality checklist** — 4 items covering team mode evaluation, conditional feature flag check, and TeamDelete cleanup
- **Anti-pattern** — "Using teams for one-shot parallel work" warns that teams add overhead vs sub-agents for independent fan-out

### skill-authoring 2.4.0 - 2026-03-06

#### Added

- **Dry-run testing phase (Step 12)** — every skill with scripts must be dry-run tested against real project data before release. Documents common failure patterns: regex mismatches, `grep` pipe chains where `head` causes SIGPIPE, `find` including coverage/build artifacts, and classification heuristics that misfire on edge cases.
- **Quality checklist item** — "Scripts dry-run tested against real project data (2-3 varied inputs)"
- **Anti-pattern** — "Untested scripts shipped as done" warns against scripts that pass code review but fail on real data; bugs cluster, so test adjacent heuristics when one fails.

### skill-authoring 2.3.0 - 2026-03-05

#### Added

- **Progress tracking for long-running workflows** — skills with 3+ sequential phases now get a task manifest script (`scripts/task-manifest.sh`) that emits TaskCreate-compatible JSON per workflow
- **`scripts/generate-task-manifest.sh`** — scaffolding tool that generates task-manifest.sh with placeholder tasks for each workflow (`--skill-dir`, `--workflows "name:count"`)
- **`references/task-tracking-pattern.md`** — full reference with task manifest template, field table, update patterns (sequential, sub-agent, abort), and real-world examples (dependabot 8 tasks, issue-triage 5 tasks, catalog-maintainer 6 tasks)
- **Core Principle #8** — "Track progress for long workflows" requiring task manifest for skills with 3+ phases
- **Progress Tracking Evaluation (Step 5)** in the new-skill creation workflow
- **Progress tracking section** in quality checklist (`references/quality-checklist.md`)
- **Anti-pattern** — "Silent long-running workflows" warns against skills without task visibility

### skill-authoring 2.2.0 - 2026-02-27

#### Added

- **Incomplete CLI templates anti-pattern** — warns that agents improvise missing fields (labels, assignees, milestones) with plausible-but-wrong values; include ALL metadata flags explicitly in agent prompt templates

### skill-authoring 2.1.0 - 2026-02-24

#### Added

- **`((var++))` bash arithmetic pitfall** — documents how `set -e` causes `((var++))` to exit when var is 0 (returns exit code 1), with fix: use `var=$((var + 1))` instead

### skill-authoring 2.0.0 - 2026-02-18

Initial public release.

#### Included

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
