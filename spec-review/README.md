# spec-review

Reviews and enriches story specifications with codebase-verified technical sub-tasks, architecture alignment checks, design simplification suggestions, and API test plans.

## What It Does

When you have a story spec that needs validation before implementation, `spec-review` launches **4 parallel review agents** that each focus on a different quality dimension:

| Agent | Focus | What It Catches |
|-------|-------|----------------|
| **Codebase Verifier** | File paths, function signatures, types | Fabricated module names, wrong line numbers, missing exports |
| **Architecture Checker** | MCP/Backend/Frontend boundaries | Layer violations, wrong data flow direction, missing enrichment steps |
| **Simplification Advisor** | Over-engineering, unnecessary abstractions | YAGNI violations, premature optimization, redundant wrappers |
| **Bruno Test Planner** | API contract coverage | Missing test scenarios, wrong folder placement, incomplete assertions |

All 4 agents run simultaneously in ~30 seconds total.

## When to Use

- After creating a new story spec with `/spec-creator`
- When a spec has high-level tasks but lacks implementation-ready detail
- Before starting implementation to catch spec-vs-code drift
- When acceptance criteria reference API changes without test coverage
- When sub-tasks mention specific file paths or function names that need verification

## Usage

```
/spec-review specs/stories/epic-16/story-16.10-feature-name.md
```

## How It Works

### Phase 1: Extract Context (Script)

```bash
# Auto-discovers project architecture
scripts/discover-project-architecture.sh .

# Extracts spec sections for targeted agent prompts
scripts/extract-spec-sections.sh specs/stories/epic-16/story-16.10-feature-name.md
```

### Phase 2: Parallel 4-Agent Review

All agents launch in a single message for maximum parallelism:

1. **Codebase Verifier** — greps for every file path, function name, and type referenced in the spec. Flags fabricated names with the correct alternative.
2. **Architecture Checker** — validates that the spec follows the project's layer boundaries (e.g., MCP is authoritative for catalog data, backend orchestrates, frontend displays).
3. **Simplification Advisor** — applies a checklist of common over-engineering patterns and suggests simpler alternatives.
4. **Bruno Test Planner** — maps acceptance criteria to Bruno API test scenarios with folder placement, shared session reuse, and assertion patterns.

### Phase 3: Consolidate & Apply

Agent results are consolidated into a unified report. Changes are applied directly to the spec file:
- Sub-tasks get verified file paths and function signatures
- Architecture violations get flagged with recommended fixes
- Over-engineered patterns get simplified alternatives
- A new "Bruno API Test Plan" section is added (if API changes are involved)

## What Gets Added to the Spec

After review, your spec may include new sections:

```markdown
## Bruno API Test Plan

### Suitability Assessment
Bruno **can** validate: [list of testable API contracts]
Bruno **cannot** simulate: [list of non-API scenarios]

### Recommended Tests
| AC | Test | Folder | Assertion |
|----|------|--------|-----------|
| AC1 | Field presence | 08-Privacy-Data | `expect(rec.tips).to.be.an('array')` |

## Design Simplification Notes
1. Task 3 creates a new helper — can be inlined into existing service
2. New cache layer is unnecessary — existing cache covers this path
```

## Scripts

| Script | Purpose |
|--------|---------|
| `discover-project-architecture.sh` | Detects project structure, test frameworks, layer boundaries at runtime |
| `extract-spec-sections.sh` | Parses spec markdown into structured sections for targeted agent prompts |
| `task-manifest.sh` | Generates TaskCreate checklist for progress tracking |

## References

| File | Purpose |
|------|---------|
| `design-simplification-checklist.md` | Common over-engineering patterns the Simplification Advisor checks against |

## Companion Skills

| Skill | Relationship |
|-------|-------------|
| `spec-creator` | Creates specs → `spec-review` validates them (upstream) |
| `spec-implement` | Implements reviewed specs (downstream) |
| `project-code-review` | Reviews code after implementation (post-implementation) |

## Install

### From Monorepo (Recommended)

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/spec-review
rm -rf /tmp/ccs
```

### Manual

Install via the marketplace: `/plugin install spec-review@claude-code-skills`.

## License

MIT
