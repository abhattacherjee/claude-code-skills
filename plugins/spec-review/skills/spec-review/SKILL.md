---
name: spec-review
description: "Reviews and enriches story specifications with codebase-verified technical sub-tasks, architecture alignment checks, design simplification suggestions, and API test plans. Dynamically discovers project architecture at runtime. Use when: (1) a new story spec needs review before implementation, (2) a spec has high-level tasks but lacks implementation-ready detail, (3) need to verify spec assumptions against actual codebase, (4) a spec references API changes but has no test plan, (5) reviewing specs that reference data shapes or pipeline ordering, (6) spec subtasks mention add field X to object Y or call function at line N."
metadata:
  version: 2.2.2
---

# Spec Review

> **Path convention:** `./scripts/…` and `./references/…` below are relative to this skill's own base directory — announced as "Base directory for this skill" when the skill is invoked. A Bash tool call's working directory is the user's project, not the skill directory, so prefix these with that base directory when running them. Paths written without the leading `./` (for example `scripts/` or `tests/` inside a search over the codebase) refer to the **target project** being worked on, not to this skill.

Comprehensive spec review combining codebase verification and implementation planning.
Discovers project architecture at runtime — works with any codebase structure.

1. **Codebase Verification** — 8-category checklist for verifying spec sub-tasks against code
2. **Full Planning Workflow** — 4-phase parallel analysis producing enriched specs

---

## Part 1: Codebase Verification Checklist

### Problem

Story specs with technical subtasks frequently contain incorrect assumptions about the
codebase — fields on the wrong object, wrong data shapes, incorrect pipeline ordering,
unnecessary wrapper functions. These look plausible but cause confusion during implementation.

### Pre-Commit Verification Checklist

For every spec subtask that references code, verify these 8 categories:

#### 1. Field Location — "Which object actually has this field?"
```bash
# Don't assume a field is on the object you expect
grep -rn "fieldName" <service-directory> --include="*.ts" --include="*.js"
```
**Common trap**: Enrichment/transform services copy SOME fields from source items but not ALL.

#### 2. Data Shape — "What type is this field really?"
```bash
grep -A5 "fieldName" <service-file>
# May reveal { value: number, unit: string } not just a number
```
**Common trap**: Duration/time fields are often objects `{value, unit}` not plain numbers.

#### 3. Pipeline Ordering — "What data is available at this point?"
```bash
# Trace the processing pipeline to verify what data exists at each stage
grep -n "extract\|enrich\|transform\|validate\|process" <orchestrator-file>
```
**Common trap**: Integration points may be BEFORE enrichment/transform runs.

#### 4. Function Signatures — "What params does this actually take?"
```bash
grep -A3 "function targetFunction\|const targetFunction" <file>
```
**Common trap**: Functions may infer values from their inputs rather than accepting explicit params.

#### 5. Conditional Fields — "Is this field always present?"
```bash
grep -B2 -A2 "fieldName =" <config-or-service-file>
# May reveal: field only set under certain conditions
```

#### 6. Existing Delegation — "Does a wrapper already handle this?"
```bash
grep -n "buildDynamic\|delegate\|dispatch\|forward" <relevant-files>
```

#### 7. Automation Integration — "Will this run during CI/maintenance?"
```bash
# Find pipeline agents/scripts that run build/enrichment steps
grep -rn "script-name\|task-name" .claude/agents/ scripts/ .github/
```

#### 8. ID/Data Contract Consistency — "Do producer and consumer use the same resolution?"
```bash
# When spec says "function A returns IDs that function B uses for lookup"
# Verify both use the same ID resolution/normalization
grep -A10 "function producer\|function consumer" <service-files>
```
**Common trap**: A producer resolves IDs to canonical form but the consumer expects raw values.

### Verification Output

After applying the checklist, the spec should have:
- Exact function signatures with parameter types and return types
- Correct file paths and line numbers (verified by reading the file)
- Accurate data shapes (object vs primitive, with field names)
- Correct pipeline ordering (verified by reading the orchestration code)
- Conditional field handling noted where fields may be absent
- No unnecessary wrapper functions
- ID resolution consistency verified between producer and consumer functions

---

## Part 2: Full Planning Workflow

### Quick Check

```bash
# Discover project architecture (layers, services, test tools)
./scripts/discover-project-architecture.sh "$(git rev-parse --show-toplevel)"
./scripts/discover-project-architecture.sh "$(git rev-parse --show-toplevel)" --json

# Extract spec sections for analysis
./scripts/extract-spec-sections.sh <spec-file>
./scripts/extract-spec-sections.sh <spec-file> --json

# Task checklist for full review
./scripts/task-manifest.sh full-review
```

### Progress Tracking (MANDATORY)

Before starting a full review, create the task checklist from `./scripts/task-manifest.sh full-review`:

| # | subject | activeForm |
|---|---------|------------|
| 1 | Discover architecture and extract spec | Discovering project architecture |
| 2 | Launch 4 parallel analysis agents | Analyzing spec with 4 parallel agents |
| 3 | Synthesize findings into enrichments | Synthesizing review findings |
| 4 | Calculate readiness score | Calculating implementation readiness |
| 5 | Present report and apply enrichments | Presenting review report |

**Update rules:**
- Mark each task `in_progress` (TaskUpdate) immediately before starting it
- Mark each task `completed` immediately after it succeeds
- Task 2 launches 4 parallel agents — mark `completed` after ALL agents return
- If any task fails, keep it as `in_progress` and report the error
- On abort, mark remaining tasks as `deleted`

### Phase 1: Discover and Extract (Scripts)

**1.1 Discover project architecture:**
```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
ARCH=$(./scripts/discover-project-architecture.sh "$PROJECT_ROOT" --json)
```

This returns: packages with layer classification (frontend/backend/mcp/tooling),
frameworks per package, test frameworks, API test tools, Bruno folders (if any),
E2E framework, data flow patterns, i18n approach, and security patterns.

**1.2 Extract spec sections:**
```bash
SPEC_DATA=$(./scripts/extract-spec-sections.sh "$SPEC_FILE" --json)
```

This returns: title, acceptance criteria counts, referenced files and endpoints,
sub-task count, and gap detection (missing codebase state, missing test plan).

**1.3 Read CLAUDE.md and architecture docs** from the project root. Look for:
- `CLAUDE.md` — project-level development rules and conventions
- `docs/development/ARCHITECTURE.md` or similar — architecture documentation
- `docs/development/TESTING.md` or similar — test strategy documentation

These provide project-specific context that the discovery script can't capture
(business rules, data flow conventions, layer responsibility definitions).

### Phase 2: Parallel Analysis (4 Agents)

Launch ALL four agents in a SINGLE Task tool message.

> The `feature-dev:*` agent types below require the separately-installed `feature-dev` plugin. If it is not available, dispatch `general-purpose` instead and note the substitution in your output.

| Agent | Type | Purpose | Key Output |
|-------|------|---------|------------|
| **Codebase Verifier** | `feature-dev:code-explorer` | Verify every file path, function name, and data shape | Verified/corrected paths, signatures, shapes |
| **Architecture Reviewer** | `feature-dev:code-explorer` | Map spec to discovered architecture, identify boundary violations | Architecture alignment report |
| **Design Simplifier** | `feature-dev:code-architect` | Analyze for over-engineering, suggest simpler approaches | Simplification recommendations |
| **Test Plan Extractor** | `general-purpose` | Extract testable scenarios, design API/E2E test plan | Test plan using project's discovered test tools |

#### Agent Prompt Templates

**Codebase Verifier** — Provide the spec's referenced files/functions/fields and ask:
```
You are verifying a story specification against the actual codebase.

SPEC TITLE: [title]
SPEC FILE: [path]

FILES REFERENCED IN SPEC:
[list from extraction]

FUNCTIONS REFERENCED:
[list of function names and claimed signatures]

YOUR TASK:
1. Verify each referenced file EXISTS at the claimed path
2. Verify each function has the claimed SIGNATURE
3. Verify each data shape matches reality (field names, types, nesting)
4. Check line number references are still accurate
5. Report DISCREPANCIES between spec claims and actual codebase

OUTPUT FORMAT:
- VERIFIED: [path/function] — matches spec
- CORRECTED: [path/function] — spec says X, actual is Y
- MISSING: [path/function] — does not exist in codebase
```

**Architecture Reviewer** — Inject discovered architecture into the prompt:
```
You are reviewing a story specification for architecture alignment.

SPEC TITLE: [title]
SOLUTION OVERVIEW: [paste solution section]
SUB-TASKS: [paste sub-task list]

PROJECT ARCHITECTURE (discovered at runtime):
[Paste the ARCH JSON from Phase 1 — layers, services, frameworks]

PROJECT RULES (from CLAUDE.md):
[Paste relevant architecture rules from CLAUDE.md]

YOUR TASK:
1. Identify the project's layer boundaries from the discovered architecture
2. Check each sub-task respects layer boundaries
3. Map spec requirements to EXISTING services that already handle similar work
4. Flag missing cross-cutting concerns (CSRF, caching, i18n — based on discovered patterns)
5. Check if data flow follows the project's established direction

OUTPUT FORMAT:
- ALIGNED: [sub-task] — correctly uses [layer/service]
- VIOLATION: [sub-task] — [description of violation and fix]
- REUSE: [sub-task] — existing [service/function] already handles this
- MISSING: [concern] — spec should address [security/cache/i18n/etc.]
```

**Design Simplifier** — Provide the spec's technical design:
```
You are reviewing a story specification for over-engineering.

SPEC TITLE: [title]
TECHNICAL DESIGN: [paste design section]
SUB-TASKS: [paste all sub-tasks with details]
SUB-TASK COUNT: [N]
NEW FILES PROPOSED: [list]

SIMPLIFICATION PATTERNS:
[Paste the full contents of ./references/design-simplification-checklist.md here — inline the content; do not pass the file path to the sub-agent]

YOUR TASK:
1. For each sub-task, ask: "Can this be done more simply?"
2. Check for unnecessary abstractions (wrappers, managers, helpers used once)
3. Check for redundant infrastructure (new cache when upstream caches exist)
4. Check for over-scoped changes (refactoring, observability, feature flags)
5. Propose concrete simplifications with rationale

OUTPUT FORMAT:
- KEEP: [sub-task] — appropriately scoped
- SIMPLIFY: [sub-task] — [current approach] → [simpler approach] because [reason]
- REMOVE: [sub-task] — unnecessary because [reason]
- MERGE: [sub-tasks X+Y] → single sub-task because [reason]
```

**Test Plan Extractor** — Use discovered test tools:
```
You are extracting testable use cases from a story specification.

SPEC TITLE: [title]
ACCEPTANCE CRITERIA: [paste all ACs]
ENDPOINTS AFFECTED: [list of API routes/tools]

PROJECT TEST INFRASTRUCTURE (discovered):
- API Test Tool: [e.g., Bruno, Postman, HTTP Client, or none]
- API Test Folders: [list from discovery, or "none detected"]
- Unit Test Framework: [e.g., Jest, Vitest, pytest per package]
- E2E Framework: [e.g., Playwright, Cypress, or none]

SCENARIO CATEGORIES:
  HP (Happy Path, P0) | VAL (Validation, P0) | EDGE (Edge Cases, P1)
  DC (Data Contract, P0) | REG (Regression, P1) | LOC (Localization, P1) | PERF (Performance, P2)

YOUR TASK:
1. For each acceptance criterion, identify testable API scenarios
2. Classify each scenario (HP/VAL/EDGE/DC/REG/LOC/PERF)
3. Determine the correct test location based on discovered folder structure
4. Identify shared fixtures/sessions that can be reused
5. Define key assertions for each test
6. Check for existing tests that might already cover scenarios
7. Note scenarios better suited for unit tests or E2E

OUTPUT FORMAT:
## API Test Plan
### Test Summary
| ID | Scenario | Category | File | Folder | Priority |

### Coverage Matrix
| Acceptance Criterion | Test(s) | Gap? |

### Test Specifications
1. **TEST.1** Create [folder/file] — [description with key assertions]
```

### Team Mode (Optional)

When `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is enabled, Phase 2 can use a team instead
of 4 parallel Agent calls. Benefits:
- **Cross-pollination**: Codebase Verifier can alert Architecture Reviewer about missing
  files mid-review (via SendMessage), rather than discovering mismatches only during synthesis
- **Iterative refinement**: If Design Simplifier identifies a simplification that affects
  the Test Plan, the Test Plan Extractor adjusts in real-time

**Team workflow:**
1. `TeamCreate("spec-review-{spec-name}")`
2. Create 4 tasks (one per analysis dimension)
3. Spawn 4 teammates with specialized prompts
4. Teammates claim tasks, work independently, message each other with findings
5. Lead synthesizes all findings in Phase 3
6. `TeamDelete` cleanup

**Default**: Sub-agent mode (no teams). Teams are opt-in when enabled.

### Phase 3: Synthesize and Generate Enrichments

After all agents return, synthesize findings into spec enrichments.

#### 3.1 Current Codebase State Section
```markdown
## Current Codebase State
**What EXISTS (verified):**
- `exact/path/to/file.ext` — functionName(params): ReturnType (line XX)

**What needs to be MODIFIED:**
- `exact/path/to/file.ext` — [specific change description]

**What needs to be CREATED:**
- `exact/path/to/new-file.ext` — [purpose and responsibility]
```

#### 3.2 Design Simplification Notes
```markdown
## Design Simplification Notes
1. **[Sub-task X]**: [Current approach] → [Simpler approach] — [rationale]
```

#### 3.3 Detailed Technical Sub-Tasks
Each sub-task must have: File, Function, Change, Verification command, Dependencies,
Estimated complexity (S/M/L).

#### 3.4 API Test Plan
Formatted using the project's discovered test tool conventions (Bruno `.bru` files,
Postman collections, plain HTTP files, or unit test specifications).

#### 3.5 Implementation Readiness Score

| Dimension | Score (1-5) | Notes |
|-----------|-------------|-------|
| Codebase Accuracy | X | How many refs were correct vs corrected |
| Architecture Alignment | X | How many violations found |
| Design Simplicity | X | Complexity score from simplifier |
| Test Coverage | X | % of ACs mapped to tests |
| Sub-Task Completeness | X | Are all sub-tasks implementation-ready? |
| **Overall Readiness** | **X/25** | |

**Readiness levels:**
- 20-25: Ready for implementation
- 15-19: Minor gaps, review enrichments and proceed
- 10-14: Significant gaps, iterate on spec before implementing
- Below 10: Major rework needed

### Phase 4: Present Report

Present findings as a structured report with:
1. Summary of issues found (Critical / Important / Suggestions)
2. Enriched sections ready to insert into the spec
3. Implementation readiness score
4. Recommended next steps

Ask the user whether to:
- **Update the spec file** with enrichments (recommended)
- **Save as a companion document** (e.g., `specs/reviews/review-X.Y.md`)
- **Just report** without modifying files

---

## Notes

- This skill is a PRE-implementation review. It enriches specs, not code.
- Feature-dev's code-explorer agents are reused for codebase verification when the `feature-dev` plugin is installed; otherwise `general-purpose` agents are substituted.
- Feature-dev's code-architect agents are reused for design analysis when the `feature-dev` plugin is installed; otherwise `general-purpose` agents are substituted.
- The test plan produced here is a SPECIFICATION — use appropriate tooling
  during implementation to create actual test files.
- Always verify spec claims with `grep`/`read` — never trust assumed file paths.
- The most common failure mode is field-on-wrong-object: a field exists in the codebase but
  on a different layer's object than the spec assumes.
- For multi-path systems (e.g., sync + async + streaming code paths), ensure the spec
  addresses ALL paths consistently.

## See Also

- `spec-creator` — generates story specs (this skill reviews them)
- `context-shield` — use when a spec references many external docs that need reading
