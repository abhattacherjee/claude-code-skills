---
name: spec-creator
description: "Creates detailed story specification files from various inputs (Claude plan, requirement file, prompt, GitHub issue). Discovers project spec conventions at runtime, brainstorms approaches with vertical splitting recommendations for large stories, generates template-compliant specs, checks for over-engineering, and optionally chains to spec-review. Use when: (1) user wants to write a new story spec, (2) converting a plan or requirements into a formal spec, (3) creating specs from GitHub issues, (4) breaking a large feature into shippable vertical slices."
metadata:
  version: 2.4.0
---

# Spec Creator

## Problem

Writing story specs from scratch is error-prone: incorrect file paths, wrong function
signatures, missed existing infrastructure, over-engineered designs, and inconsistent
formatting. Each project has its own spec conventions that must be discovered and followed.

## Quick Check

```bash
# Discover project spec conventions
~/.claude/skills/spec-creator/scripts/discover-conventions.sh .           # Report
~/.claude/skills/spec-creator/scripts/discover-conventions.sh . --json    # JSON
```

## Progress Tracking (MANDATORY)

Before starting, determine the workflow and create the task checklist:

```bash
~/.claude/skills/spec-creator/scripts/task-manifest.sh single-story    # Default
~/.claude/skills/spec-creator/scripts/task-manifest.sh vertical-split   # If splitting
```

**Single-story workflow (default):**

| # | subject | activeForm |
|---|---------|------------|
| 1 | Parse input and discover conventions | Discovering project conventions |
| 2 | Research codebase | Researching codebase |
| 3 | Brainstorm approaches with user | Brainstorming approaches |
| 4 | Generate spec file | Generating spec file |
| 5 | Post-creation review | Running post-creation review |

**Vertical-split workflow** (chosen in Phase 3 if splitting triggers fire):

| # | subject | activeForm |
|---|---------|------------|
| 1 | Parse input and discover conventions | Discovering project conventions |
| 2 | Research codebase | Researching codebase |
| 3 | Brainstorm approaches with user | Brainstorming approaches |
| 4 | Generate spec files for all slices | Generating spec files |
| 5 | Update tracking file | Updating tracking file |
| 6 | Post-creation review | Running post-creation review |

**Update rules:**
- Create all tasks from `single-story` manifest at start (TaskCreate)
- Mark each task `in_progress` (TaskUpdate) immediately before starting it
- Mark each task `completed` immediately after it succeeds
- If user selects vertical split in Phase 3, delete task 4-5 and create tasks 4-6 from `vertical-split` manifest
- If user selects "Done" in Phase 5, mark the post-creation task `completed` immediately
- On error, keep current task as `in_progress` and report

## Workflow (5 Phases)

### Phase 1: Parse Input and Discover Conventions

**→ TaskUpdate: task 1 `in_progress`**

**1.1 Detect input type** from the user's arguments:

| Input Type | Detection | Action |
|-----------|-----------|--------|
| **Prompt** | Plain text describing the feature | Extract requirements directly |
| **File path** | `@path/to/file.md` or file extension | Read file, extract requirements |
| **GitHub issue** | `#123` or GitHub URL | Fetch via `gh issue view` |
| **Claude plan** | References a plan or plan output | Parse plan steps into requirements |

**1.2 Discover project conventions** by running the discovery script:

```bash
CONVENTIONS=$(~/.claude/skills/spec-creator/scripts/discover-conventions.sh "$(git rev-parse --show-toplevel)" --json)
```

This returns: spec directory, naming pattern, epic structure, next available story
numbers, tracking files, and common sections across existing specs.

**1.3 Read a recent spec** from the project as a style reference. Use the `sampleSpec`
path from the discovery output. This ensures the generated spec matches the project's
actual voice and formatting — not just the template structure.

**1.4 Determine epic and story number.** If the user specified an epic, use it. Otherwise,
infer from the requirement's domain or ask. Use the `nextStory` value from discovery.

**→ TaskUpdate: task 1 `completed`**

### Phase 2: Research Codebase (Parallel Agents)

**→ TaskUpdate: task 2 `in_progress`**

Launch 3 agents in a SINGLE Task tool message:

**Agent 1: Feature Scout** (`feature-dev:code-explorer`)
> Research the codebase to find: (1) existing code related to [requirement],
> (2) services, utilities, and patterns that should be reused, (3) relevant file
> paths with function signatures and line numbers, (4) existing tests that cover
> related functionality. **CRITICAL: Use `ls` and `grep` to verify every module
> name, file path, and directory structure — do NOT guess names based on conventions.
> List actual exports with `grep -r "export" dir/` instead of assuming names like
> `apiService.ts` or `LanguageContext.tsx`.**
>
> **For dependency upgrade stories**, ALSO: (5) check the target package's module
> system compatibility: `npm view <pkg>@<target> exports type --json` — if the
> project uses CJS (`require()`) and the target version has no `require`/`node.require`
> entry in `exports`, the upgrade is **infeasible** without an ESM migration.
> (6) Search for existing compatibility guard scripts:
> `grep -rl "verify.*compat\|ERR_REQUIRE_ESM\|require.*<pkg>" scripts/ tests/`.
> (7) Check if Jest/Babel masks the breakage — `require()` calls that fail in
> production Node.js can pass in Jest because Babel transpiles ESM→CJS at test time.
>
> Return a structured report of what EXISTS (with verified paths), what needs
> MODIFICATION, and what needs CREATION. **For dep upgrades, include a
> "Module Compatibility" section with the `exports` field analysis.**

**Agent 2: Convention Scanner** (`general-purpose`, model: `haiku`)
> Read the sample spec file at [sampleSpec] and extract: (1) the exact markdown
> formatting style (header levels, bold patterns, code block usage), (2) how
> sub-tasks are numbered and structured, (3) how acceptance criteria are written,
> (4) any project-specific sections not in the standard template. Return a concise
> style guide.

**Agent 3: Metrics Scout** (`general-purpose`, model: `sonnet`)
> Analyze the requirement and codebase to identify success metrics for this story.
>
> **Research:**
> 1. What user-facing or system behavior does this story change? What would prove
>    it's working? (e.g., error rate drops, latency improves, feature adoption grows)
> 2. Search for existing observability infrastructure:
>    `grep -rn "metrics\.\|setAttribute\|Sentry\.\|captureMessage\|console\.log.*metric" src/`
> 3. Identify which metrics already exist that this story should move, and which
>    new metrics need to be created
> 4. For each metric, recommend the capture mechanism:
>    - Sentry span attributes (`setAttribute()`) — queryable in Explore
>    - Sentry custom metrics (`metrics.count/gauge/distribution`) — for dashboards
>    - Structured console logs — for Railway/CloudWatch
>    - Bruno API test assertions — for contract validation
>    - Existing feasibility codes — if story affects recommendation quality
>
> **Return a structured report:**
> ```
> ## Success Metrics
> | Metric | Type | Current Value | Target | Capture Method |
> | "Share link crash rate" | error_rate | ~22 events/week | 0 | Sentry error count |
> | "Tips field present" | boolean | false after restart | always true | Bruno assertion |
>
> ## Existing Instrumentation to Reuse
> - [list of existing metrics/spans relevant to this story]
>
> ## New Instrumentation Needed
> - [list of new setAttribute/metrics calls to add]
> ```

**→ TaskUpdate: task 2 `completed`**

### Phase 3: Brainstorm Approaches (with Vertical Splitting)

**→ TaskUpdate: task 3 `in_progress`**

**3.0 Clarify intent before designing** — before proposing approaches, ask 1-3 clarifying
questions (one at a time via `AskUserQuestion`) to fill gaps the codebase research
couldn't answer:
- **Purpose**: What user-facing problem does this solve? What does success look like?
- **Constraints**: Performance targets? Backward compatibility? Timeline pressure?
- **Scope boundaries**: What's explicitly out of scope? What adjacent features should NOT change?
- **Design preference**: Minimal fix vs comprehensive solution? TDD methodology?

Skip clarifying questions if the input (spec file or detailed issue) already answers these.
Prefer multiple-choice questions when possible. Never ask more than 3 questions total.

**3.1 Assess scope** from Phase 2 research. Count estimated sub-tasks, files affected,
and layers touched. If **any** splitting trigger fires (see below), include a vertical
split option alongside the single-story approaches.

**3.2 Splitting triggers** — recommend splitting when ANY of these apply:

| Trigger | Threshold | Why |
|---------|-----------|-----|
| Sub-task count | > 8 estimated | Too many moving parts for one PR |
| Files affected | > 8 files | Review burden, merge conflict risk |
| Layers touched | 3+ (MCP + Backend + Frontend) | Cross-layer stories hide integration bugs |
| Independent user values | 2+ distinct outcomes | Each value deserves its own validation |
| Testable hypotheses | 2+ assumptions to validate | Ship one, learn, then decide on next |
| Estimate | > 6 hours | Diminishing returns on large stories |

**3.3 Vertical slice rules** — each slice must be:
- **End-to-end**: Touches all layers needed to deliver ONE user-visible behavior
- **Independently deployable**: Can merge to develop without waiting for sibling slices
- **Independently testable**: Has its own acceptance criteria and tests
- **Valuable alone**: Delivers customer value or validates a hypothesis even if
  other slices are never built

**Anti-pattern**: Horizontal slicing (Story A = backend, Story B = frontend, Story C =
tests). This creates integration risk and blocks deployment until all slices merge.

**3.4 Present options** via `AskUserQuestion`. Structure depends on scope assessment:

**If splitting triggers fired — include a split option:**

```
Option 1: Single Story (Minimal)
- Scope: [reduced scope that fits under thresholds]
- Complexity: S/M
- Files: N
- Tradeoff: Leaves out [X, Y]

Option 2: Single Story (Full Scope)
- Scope: [everything requested]
- Complexity: L
- Files: N (⚠️ exceeds 8)
- Tradeoff: Large PR, harder to review

Option 3: Vertical Split into N Stories (Recommended)
- Slice A: "[User-facing behavior 1]" — [layers], ~Xh
- Slice B: "[User-facing behavior 2]" — [layers], ~Xh
- Slice C: "[Hypothesis to validate]" — [layers], ~Xh
- Tradeoff: More specs to write, but each is focused and shippable
```

**If no splitting triggers — standard options:**

```
Option 1: Minimal
- Scope: [fewest changes]
- Complexity: S
- Key tradeoff: [what's excluded]

Option 2: Recommended
- Scope: [balanced]
- Complexity: M
- Key tradeoff: [balance point]

Option 3: Ambitious (optional)
- Scope: [comprehensive]
- Complexity: L
- Key tradeoff: [effort vs completeness]
```

**Team Mode (Optional):** When `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is enabled, Phase 2
research agents and Phase 3 brainstorming agents can be persistent teammates that iterate
on user feedback via `SendMessage` rather than running as one-shot sub-agents. This allows
the Feature Scout to refine its research based on real-time Convention Scanner findings.

**Brainstorming rules:**
- **YAGNI ruthlessly** — strip unnecessary features from all approaches before presenting.
  If a feature isn't needed for the stated success criteria, don't include it.
- **Design for isolation** — break into units with clear boundaries. For each unit:
  can someone understand it without reading internals? Can you change internals without
  breaking consumers? If not, the boundaries need work.
- Apply the simplification decision tree before presenting:
  - Does this need a new file, or can existing code absorb it?
  - Does this need a new abstraction, or can it be inline?
  - Does this need backward compatibility, or can it replace directly?
  - Does this touch 3+ layers — can it be contained in fewer?
- When presenting a split, name each slice by its **customer value**, not its
  technical layer ("Show hours badge" not "Add businessHours field")
- Order slices by dependency: foundational slices first, enhancement slices later
- **Lead with your recommendation** — present the recommended option first with
  reasoning, then alternatives. Don't force the user to evaluate all options equally.

**→ TaskUpdate: task 3 `completed`**

**→ If user selected vertical split: delete tasks 4-5, create tasks 4-6 from `vertical-split` manifest**

### Phase 4: Generate Spec(s)

**→ TaskUpdate: task 4 `in_progress`**

After user selects an approach, generate the spec file(s).

#### Path A: Single Story (user chose a single-story option)

**4.1 Build spec content** using:
- The template structure from **[references/spec-template.md](references/spec-template.md)**
- The formatting style extracted by Convention Scanner (Phase 2)
- The codebase facts from Feature Scout (Phase 2)
- The scope/approach from user selection (Phase 3)

**4.2 Populate each section:**

| Section | Source |
|---------|--------|
| Title & Metadata | Discovery script (epic, story number) + user input |
| User Story | Extracted from requirements |
| Context | From requirements + codebase research |
| Solution Overview | From selected approach |
| Current Codebase State | From Feature Scout agent (verified paths + signatures) |
| Acceptance Criteria | Derived from requirements, one per testable behavior |
| Success Metrics | From Metrics Scout agent — what to measure, targets, capture method |
| File Structure Map | Aggregated from codebase research — all files to create/modify |
| Implementation Tasks | TDD steps with complete code, run commands, expected output |
| Testing Checklist | Inferred from tasks (unit, Bruno, E2E as applicable) |
| Definition of Done | Standard template + project-specific items |

**4.3 Codebase State verification gate** (MANDATORY):

Before writing the spec, verify every name in the "Current Codebase State" section against
the actual codebase. This prevents the #1 spec quality issue: **fabricated module names**.

**What to verify:**
```bash
# Every file path listed under "What EXISTS" — must return a result
ls -la path/to/claimed/file.ts

# Every module/hook/context/service name — must exist as an export
grep -r "export.*ClaimedName" frontend/src/ backend/src/

# Every directory structure claim — must match reality
ls frontend/src/components/screens/    # Does this dir exist?

# Every type definition — must match actual values
grep -A5 "type ClaimedType" frontend/src/App.tsx

# Item counts — must be accurate
ls frontend/src/components/*.tsx | wc -l
```

**Common fabrication patterns to catch** (from Epic 15 post-mortems):

| Pattern | Example (fabricated → actual) | How to catch |
|---------|-------------------------------|--------------|
| Plausible module names | `apiService.ts` → `api.ts`, `mcpClient.js` → `mcpEventsClient.js` | `ls` + `grep` the actual directory |
| Assumed directory structure | `components/screens/` → screens are flat in `components/` | `ls` the parent dir |
| Wrong file extensions | `locales/en.json` → `en.ts` | `ls` the directory |
| Guessed type values | `'long'` → `'extended'`, `'first_time'` → month abbreviations | `grep -A5 "type TypeName"` |
| Inflated counts | "10+ screens" → 5 screens, "10+ MCP endpoints" → 0 | Count with `ls | wc -l` |
| Assumed endpoints/routes | `/api/mcp/*` proxy routes → no such routes exist | `grep -r "router\." src/routes/` |

**Rule: If you cannot verify a claim with a command, do NOT include it in the spec.**
Write "TBD — verify during implementation" instead of guessing.

**4.3b Dependency Upgrade Pre-Flight** (MANDATORY for dependency upgrade stories):

When the story involves upgrading a package to a new major version, verify module
system compatibility BEFORE writing the spec. This catches the #2 spec quality issue:
**assuming a major version bump is a drop-in replacement when it actually changes
the module system (CJS→ESM).**

```bash
# 1. Check project's module system
grep '"type"' package.json  # "module" = ESM, absent = CJS

# 2. Check how the package is imported
grep -rn "require.*<pkg>\|from ['\"]<pkg>" src/ --include="*.ts" --include="*.js"
# If require() is used → project NEEDS CJS support from the package

# 3. Check target version's exports field
npm view <pkg>@<target> exports type --json
# Look for "require" or "node.require" entry — if missing, CJS is NOT supported

# 4. Search for existing compatibility scripts
grep -rl "verify.*compat\|ERR_REQUIRE_ESM\|require.*<pkg>" scripts/ tests/
```

**Decision matrix:**

| Project uses | Target has `require` entry | Action |
|-------------|--------------------------|--------|
| `require()` | Yes | Safe to upgrade |
| `require()` | No (ESM-only) | **STOP** — upgrade infeasible without ESM migration |
| `import` (ESM) | N/A | Safe to upgrade |

**Common ESM-only packages** (post-2024): `chalk` v5+, `ora` v6+, `got` v12+,
`node-fetch` v3+, `execa` v6+, `uuid` v12+.

**Jest/Babel trap:** `require()` calls that fail in production Node.js can PASS in
Jest because Babel transpiles ESM→CJS at test time. If you find existing
compatibility guard scripts (step 4), they exist for a reason — read them.

If the target version is ESM-only and the project uses CJS, **do not write the spec**.
Instead, recommend closing the issue with a technical explanation and suggest the
prerequisite ESM migration scope.

**4.4 UX design gate** — if the story touches frontend UI (new screens, layout changes,
visual components), the first implementation task MUST be a Figma mockup step:

```markdown
### Task X.Y.0: Create Figma Mockups (UX Design)

**Prerequisite:** None (runs before any code)
**Skill:** `/figma-ui-designer` (workflow C: enhancement mockup)

- [ ] **Step 1: Create mockup** — invoke `/figma-ui-designer` with the story's
      user-facing behavior description and acceptance criteria
- [ ] **Step 2: User reviews mockup** — present Figma link, get approval or iteration
- [ ] **Step 3: Extract design tokens** — capture colors, spacing, component structure
      from approved mockup for implementation tasks
```

**Skip this step if:** the story is backend-only, API-only, config changes, prompt
changes, or modifies existing UI without visual redesign (e.g., adding `?? []` guards).

**4.5 Implementation task decomposition** — for each sub-task from the approach:

Break into **bite-sized TDD steps** (2-5 minutes each) following this pattern:
1. Write the failing test (complete code, not pseudocode)
2. Run command with expected FAIL output
3. Write minimal implementation (complete code)
4. Run command with expected PASS output
5. Commit with conventional commit message

**Rules for implementation steps:**
- **Complete code** — never write "add validation here"; include the actual code
- **Exact run commands** — with `cd` into the right directory
- **Expected output** — what success/failure looks like (error messages, pass counts)
- **Checkbox syntax** (`- [ ]`) for each step so implementers track progress
- **TDD sequence** — test first, run to confirm fail, implement, run to confirm pass

See **[references/spec-template.md](references/spec-template.md)** Section 8 for the
full task structure template with examples.

**4.6 Simplification self-check** before writing:

Run through these red flags (from the design simplification checklist):
- Task count > 10? → Consider splitting the story
- New files > 3? → Can any logic live in existing files?
- "For future extensibility" language? → Remove (YAGNI)
- Wrapper/Manager/Helper for single use? → Inline it
- New cache/endpoint/tool when existing one suffices? → Reuse

**4.7 Write the spec file** to the project's spec directory:
```
{specDir}/epic-{N}/story-{N}.{M}-{kebab-name}.md
```

Create the epic subdirectory if it doesn't exist.

**→ TaskUpdate: task 4 `completed`**

**→ Skip to Phase 5 (task 5 is post-creation review)**

#### Path B: Vertical Split (user chose the split option)

A split creates a **new epic** grouping all slices, following the project's existing
epic/story structure.

**4.1 Create a new epic.** Discover the next epic number from conventions:
```bash
# From discovery script output, find highest epic number and increment
NEXT_EPIC=$((highest_epic + 1))
```

Create the epic directory and assign sequential story numbers:
```
{specDir}/epic-{NEXT_EPIC}/
├── story-{NEXT_EPIC}.1-{slice-a-name}.md
├── story-{NEXT_EPIC}.2-{slice-b-name}.md
└── story-{NEXT_EPIC}.3-{slice-c-name}.md
```

**4.2 Add epic metadata** to each story spec. The `**Epic:**` line references the
new epic with a descriptive title:
```markdown
**Epic:** {NEXT_EPIC} — {Feature Name}
```

**4.3 Add cross-references** between slices. Each spec includes sibling links
in its metadata section:
```markdown
**Part of:** Epic {NEXT_EPIC} — {Feature Name} (vertical split)
**Siblings:** Story {NEXT_EPIC}.1 (this) · [Story {NEXT_EPIC}.2](story-{NEXT_EPIC}.2-name.md) · [Story {NEXT_EPIC}.3](story-{NEXT_EPIC}.3-name.md)
**Depends On:** Story {NEXT_EPIC}.1 (if Slice B depends on Slice A)
```

**4.4 Define dependency order.** Earlier slices should NOT depend on later ones.
Typical patterns:
```
Foundation slice → Enhancement slice → Polish slice
Data layer slice → Display slice → Analytics slice
Core behavior slice → Edge case slice → Performance slice
```

**4.5 Each slice gets its own:**
- User Story (describing its specific customer value or hypothesis)
- Acceptance Criteria (independently verifiable)
- Sub-Tasks (only what's needed for this slice)
- Testing Checklist (tests that prove this slice works alone)
- Definition of Done (completable without sibling slices)

**4.6 Simplification self-check per slice** — if any slice still triggers splitting
thresholds (> 8 sub-tasks), it's too big. Re-slice.

**4.7 Update the tracking file.** Discover which tracking file to use from
conventions (e.g., `post-mvp-tracking.md` for later epics). Add a new epic section
following the project's tracking format:

```markdown
## Epic {NEXT_EPIC}: {Feature Name}

{1-2 sentence description of the epic's goal and why it was split.}

> **Origin:** Vertical split from original requirement: "{original requirement summary}"

| Story | Status | Est | Actual |
|-------|--------|-----|--------|
| [{NEXT_EPIC}.1: {Slice A Title}](stories/epic-{NEXT_EPIC}/story-{NEXT_EPIC}.1-name.md) | ⬜ | Xh | - |
| [{NEXT_EPIC}.2: {Slice B Title}](stories/epic-{NEXT_EPIC}/story-{NEXT_EPIC}.2-name.md) | ⬜ | Xh | - |
| [{NEXT_EPIC}.3: {Slice C Title}](stories/epic-{NEXT_EPIC}/story-{NEXT_EPIC}.3-name.md) | ⬜ | Xh | - |

**Dependencies:** {List any cross-epic dependencies}
```

Also update the summary table at the top of the tracking file with the new epic row.

**→ TaskUpdate: task 5 `completed`** (vertical-split only — tracking file update)

**4.8 Write all files:**
1. Create `{specDir}/epic-{NEXT_EPIC}/` directory
2. Write each story spec file
3. Update the tracking file with the new epic section + summary row

**→ TaskUpdate: task 4 `completed`** (vertical-split: spec generation task)

### Phase 5: Post-Creation (Optional)

**→ TaskUpdate: last task `in_progress`** (task 5 for single-story, task 6 for vertical-split)

After writing the spec, ask the user:

1. **Run `/review-spec`** — Full 4-agent review (codebase verification, architecture,
   simplification, Bruno test plan). Recommended for complex stories (M/L).
2. **Run `/simplify`** — Quick simplification pass on the spec's design.
3. **Done** — Spec is ready as-is.

If user selects option 1 or 2, invoke the corresponding skill with the spec file path.

**→ TaskUpdate: last task `completed`**

## Input Examples

```
# From a prompt
/spec-creator Add rate limiting to the recommendation endpoint

# From a file
/spec-creator @requirements/rate-limiting.md

# From a GitHub issue
/spec-creator #42

# From a plan (after /plan output)
/spec-creator Based on the plan above, create a spec for the caching feature

# With explicit epic
/spec-creator epic:12 Add winter mountain safety warnings
```

## Integration with Other Skills

| Skill | Integration Point |
|-------|------------------|
| `spec-review` | Phase 5 — optional post-creation review and enrichment |
| `simplify` | Phase 5 — optional simplification pass |
| `feature-dev:code-explorer` | Phase 2 — codebase research for accurate paths |
| `figma-ui-designer` | Phase 4.4 — Figma mockup as Task 0 for UI-touching stories |
| `excursion-pipeline` | Referenced in sub-tasks if spec touches the pipeline |
| `test-engineering` | Bruno test plan conventions used in Testing Checklist |

## See Also

- `spec-review` — reviews and enriches existing specs (post-creation step)
- `skill-authoring` — how this skill was built
- `implement-story` — implements a spec (the next step after creation + review)
