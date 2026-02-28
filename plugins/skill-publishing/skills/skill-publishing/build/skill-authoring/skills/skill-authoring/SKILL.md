---
name: skill-authoring
description: "Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism. Use when: (1) creating a new skill from scratch, (2) optimizing an existing skill that exceeds 500 lines or has poor discoverability, (3) extracting inline code into scripts/ or reference material into references/, (4) designing orchestrator + sub-agent architectures for complex skills, (5) restructuring a skill directory into SKILL.md + scripts/ + references/ layout, (6) auditing skill cross-references for stale links. Covers: agent-first orchestration, parallel sub-agent design, script-first determinism, frontmatter rules, progressive disclosure, directory layout, description writing, and quality checklist."
metadata:
  version: 2.2.0
---

# Skill Authoring

## Core Principles

1. **Decompose into agents** — break complex skills into an orchestrator + specialized
   sub-agents. Each sub-agent has a single focused responsibility. The orchestrator
   delegates, coordinates, and reports — it never does the work itself.
2. **Parallelize aggressively** — launch independent sub-agents in a SINGLE Task tool
   message. If 3 catalogs need processing, launch 3 agents simultaneously, not
   sequentially. Time savings compound: 3 parallel agents = ~1x latency, not 3x.
3. **Script-first for determinism** — if the skill's value can be captured in a
   deterministic script, write the script FIRST, then wrap SKILL.md around it. Scripts
   are testable, runnable outside Claude, and keep SKILL.md lean. Agents handle
   judgement; scripts handle procedure.
4. **Concise is key** — the context window is a shared resource. Only add what Claude
   doesn't already know. Challenge each paragraph: "Does this justify its token cost?"
5. **Progressive disclosure** — SKILL.md is the overview; reference files load on-demand.
   Keep SKILL.md body under 500 lines.
6. **Match freedom to fragility** — text instructions for flexible tasks, exact scripts
   for fragile operations, specialized agents for judgement-heavy tasks.
7. **Default assumption** — Claude is already very smart. Skip explanations of basic
   concepts, library purposes, or general programming knowledge.

## Frontmatter Rules

Supported fields: `name`, `description`, `metadata`, `compatibility`, `license`.

```yaml
---
name: kebab-case-name          # ≤64 chars, lowercase + hyphens only
description: "Third-person description. Use when: (1) ..., (2) ..."  # ≤1024 chars, single-line quoted
metadata:
  version: 1.0.0               # semver: patch=typos, minor=new content, major=breaking
---
```

**Do NOT include:** `author`, `date`, `tags`, `allowed-tools`, `category`, or
top-level `version` (use `metadata.version` instead). Use double-quoted single-line
strings for `description` — block scalars (`description: |`) cause VS Code linter errors.

**Description rules:**
- Write in **third person** ("Processes files..." not "I help you..." or "You can...")
- Include **both** what it does AND when to use it
- Add numbered trigger conditions: `Use when: (1) ..., (2) ..., (3) ...`
- Include specific symptoms, error messages, framework names
- Claude uses this to choose from 100+ skills — be specific enough to win selection

## Directory Layout

```
your-skill/
├── SKILL.md              # Required — decision workflow, when-to-use, key rules
├── scripts/              # Optional — executable automation
│   ├── extract.sh        # Pre-processing: deterministic data extraction
│   └── apply-fixes.sh    # Post-processing: apply agent results
└── references/           # Optional — lookup material loaded on-demand
    ├── field-tables.md   # Tables, matrices, lookup data
    └── examples.md       # Code examples, past case studies

# Agent definitions live alongside other agents (not inside the skill):
.claude/agents/
├── your-orchestrator.md       # Pure orchestrator — delegates everything
├── your-sub-agent-a.md        # Focused specialist (NOT user-invocable)
└── your-sub-agent-b.md        # Focused specialist (NOT user-invocable)
```

### What Goes Where

| Content Type | Location | Why |
|---|---|---|
| Decision workflow | SKILL.md | Always loaded — guides what to do |
| Trigger conditions | SKILL.md | Must be visible for skill activation |
| Quick-reference commands | SKILL.md | Frequently needed during use |
| Agent orchestration pattern | SKILL.md | Defines how agents coordinate |
| Agent definitions | `.claude/agents/` | Reusable across skills, standard location |
| Lookup tables, field refs | references/ | Consulted occasionally, not always |
| Code examples, case studies | references/ | Large blocks that dilute SKILL.md |
| Executable procedures | scripts/ | Predictable, testable, reusable |

### Reference Rules
- **One level deep** from SKILL.md — no references linking to other references
- **Descriptive filenames** — `api-field-reference.md` not `ref1.md`
- Files > 100 lines should have a **table of contents** at the top

## Script Extraction

**Default: extract a script.** Only skip if the skill is purely decision guidance
with no deterministic steps.

Extract into `scripts/` when ANY apply:
- The skill checks, validates, or detects something (staleness, sync, coverage)
- The code handles error conditions (missing deps, wrong directory, invalid args)
- The same code block appears in multiple skills
- The script composes with other scripts or CI/hooks
- Users may run it standalone outside the skill context

**Script requirements:**
- Always support `--help` / `-h` with usage examples
- Validate inputs before operating (check files exist, directories writable)
- Use meaningful exit codes (0 = success, 1 = error, 2 = usage)
- Include a `--fix` mode where applicable (detect + auto-remediate)
- Make executable: `chmod +x scripts/*.sh`
- Use `#!/usr/bin/env bash` shebang (portable)
- **Choose `set` flags by script purpose** (see Pitfall below)

**Pitfall: `set -e` interacts badly with bash arithmetic and pipes.**
Common triggers: (1) `find | sort | head -N` — `head` closes the pipe causing SIGPIPE
(exit 141) with `pipefail`, (2) `grep -c` returns exit 1 when count is 0,
(3) `echo "$var" | while read` in subshells, (4) **`((var++))` when var=0** — `((0))`
evaluates to false, causing `set -e` to terminate the script. Fix: use
`VAR=$((VAR + 1))` instead of `((VAR++))`. Use `set -euo pipefail` for **validation**
scripts; use `set -eu` (without pipefail) for **context-gathering** scripts.

**After writing the script, slim SKILL.md:**
- Replace procedural prose with a Quick Check section pointing to the script
- Keep SKILL.md focused on when/why/context, not how (the script handles that)
- Move lookup tables (field mappings, inventories) into the script or references/

**Reference from SKILL.md:**
````markdown
## Quick Check
```bash
./scripts/validate.sh /tmp/data.json           # Report only
./scripts/validate.sh /tmp/data.json --fix     # Auto-remediate
./scripts/validate.sh --help                   # Usage
```
````

## Agent & Orchestration Design

**Default: decompose into agents.** Only skip if the skill is a single-step check or
pure decision guidance. Every skill with 2+ independent subtasks should use parallel agents.

### When to Use Agents

| Signal | Agent Approach |
|--------|---------------|
| Task has 2+ independent subtasks | Parallel sub-agents for each |
| Task requires web search, content reading, or AI judgement | Dedicated agent per domain |
| Task processes N items of the same type | Fan-out: one agent per item (or per batch) |
| Task has sequential phases with parallel work within | Orchestrator coordinates phase gates |
| Task is a single deterministic check | **No agent** — use a script instead |

### Orchestrator Pattern

The **pure orchestrator** pattern is the gold standard for complex skills:

```
Orchestrator (coordinates, decides, reports)
├── Sub-agent A (focused task 1) ─── launched in parallel ──┐
├── Sub-agent B (focused task 2) ─── launched in parallel ──┤ SINGLE message
├── Sub-agent C (focused task 3) ─── launched in parallel ──┘
└── Script (deterministic pre/post-processing)
```

**Orchestrator rules:**
- **Pure delegation** — the orchestrator NEVER does the work itself. It launches agents,
  collects results, makes phase-gate decisions, and generates the final report.
- **Parallel by default** — launch all independent agents in a SINGLE Task tool message.
  Only sequence agents when one depends on another's output.
- **Progress reporting** — output status updates between tool calls so the user is never
  left wondering what's happening.

### Sub-Agent Design

Each sub-agent should be **maximally specialized**:

- **Single responsibility** — one agent per focused task (e.g., "validate curated catalog
  URLs" not "validate all URLs across all catalogs")
- **Self-contained prompt** — include all context the agent needs in its Task prompt.
  Don't rely on the agent inferring context from the conversation.
- **Structured output** — define the exact JSON/report format the agent should return.
  The orchestrator parses this to make decisions.
- **Appropriate model** — use `haiku` for fast/simple tasks (data extraction, formatting),
  `sonnet` for moderate judgement (code review, validation), `opus` only when deep
  reasoning is essential.

### Parallelization Patterns

**Fan-out by item** — one agent per catalog, per PR, per test folder:
```
# 3 catalogs → 3 parallel agents (SINGLE message)
Task(agent=general-purpose, prompt="Validate curated catalog URLs...")
Task(agent=general-purpose, prompt="Validate google-places catalog URLs...")
Task(agent=general-purpose, prompt="Validate experiences catalog URLs...")
```

**Fan-out by concern** — one agent per review dimension:
```
# 3 review concerns → 3 parallel agents (SINGLE message)
Task(agent=code-reviewer, prompt="Review for bugs/correctness...")
Task(agent=code-reviewer, prompt="Review for simplicity/DRY...")
Task(agent=code-reviewer, prompt="Review for project conventions...")
```

**Phased parallelism** — sequential phases, parallel within each:
```
Phase 1: Script extracts data (deterministic)
Phase 2: 3 parallel agents process data (judgement)
Phase 3: Script applies fixes (deterministic)
Phase 4: 1 agent validates results (judgement)
```

### Agent + Script Composition

The most powerful pattern combines both:
- **Scripts** handle deterministic pre-processing (extraction, transformation, validation)
- **Agents** handle judgement-heavy work (content verification, research, code review)
- **Scripts** handle deterministic post-processing (applying fixes, generating reports)

Example flow: `extract-urls.sh` → 3 parallel verification agents → `apply-fixes.sh`

### Defining Agent Files

For skills that spawn agents, create `.claude/agents/<agent-name>.md`:

```markdown
---
name: agent-name
description: "Single-purpose description. NOT user-invocable — spawned by <orchestrator>."
model: sonnet  # or haiku for simple tasks
---

You are a **<Role Name>**. Your mission is to <focused task>.

## Input (provided by orchestrator)
[What the orchestrator passes in the Task prompt]

## Output Format
[Exact JSON/report structure to return]

## Workflow
[Step-by-step procedure]
```

**Agent registration:** If the skill uses an orchestrator, include a Sub-Agent Registry
table in the orchestrator's agent file listing all sub-agents, their concurrency model
(parallel/sequential), purpose, and model tier.

## Creating a New Skill — Workflow

1. **Check existing skills** — search project + user-level directories
2. **Decide**: create new vs update existing (see decision table below)
3. **Evaluate decomposition** — can this be split into parallel agents? (see below)
4. **Evaluate script-first** — can deterministic parts be captured in scripts? (see below)
5. **Write agents** (if applicable) — orchestrator + sub-agent definitions
6. **Write scripts** (if applicable) — with `--help`, error handling, exit codes
7. **Write SKILL.md** — frontmatter + body; reference agents and scripts
8. **Extract references/** — if lookup material exceeds ~30 lines
9. **Validate** — run the quality checklist
10. **Version** — start at `1.0.0`

### Decomposition Evaluation (Step 3)

Ask: "Can this task be split into independent subtasks that run in parallel?"

| Answer | Approach | Example |
|--------|----------|---------|
| **Yes — N independent items** | Fan-out: one agent per item, orchestrator collects | `catalog-url-validator`: 3 parallel agents, one per catalog |
| **Yes — N independent concerns** | Fan-out by concern: one agent per dimension | `pr-review-toolkit`: parallel reviewers for code, tests, errors, types |
| **Partially — phases with parallel steps** | Phased: script → parallel agents → script | `catalog-maintainer`: backup → fetch → enrich → validate → embed |
| **No — single sequential task** | No orchestrator needed; single agent or script | `catalog-embedding-sync`: one script checks all |

### Script-First Evaluation (Step 4)

Ask: "Can the skill's core action be expressed as a deterministic check or procedure?"

| Answer | Approach | Example |
|--------|----------|---------|
| **Yes — fully deterministic** | Write script first, SKILL.md is thin wrapper | `catalog-embedding-sync`: script checks timestamps + counts |
| **Mostly — with some judgement** | Script handles the deterministic parts, agents handle judgement | `catalog-url-validator`: script extracts URLs, agents verify content |
| **No — primarily decision guidance** | Prose-first SKILL.md, no script needed | `catalog-field-lifecycle`: decision tree for field preservation |

**Why script-first wins:** A 140-line script replaces ~60 lines of prose in SKILL.md while being
testable, runnable standalone, and composable with CI/hooks. The SKILL.md drops from "explain
everything" to "explain when/why + point to script".

### Create vs Update Decision

| Found | Action |
|---|---|
| Nothing related | Create new |
| Same trigger + same fix | Update existing (minor version bump) |
| Same trigger, different root cause | Create new, add `See Also` links both ways |
| Same domain, different trigger | Update existing with new variant subsection |
| Stale or wrong | Deprecate in Notes, create replacement |

## Skill Template

### Simple Skill (script-only, no agents)

```markdown
---
name: descriptive-kebab-name
description: "Third-person description. Use when: (1) ..., (2) ..., (3) .... Covers: topic1, topic2."
metadata:
  version: 1.0.0
---

# Skill Title

## Problem
[2-3 sentences max.]

## Quick Check
```bash
./scripts/check.sh              # Report only
./scripts/check.sh --fix        # Auto-remediate
```

## Solution
[Decision guidance for non-scripted parts.]

## See Also
[Cross-references to related skills.]
```

### Complex Skill (orchestrator + parallel agents + scripts)

```markdown
---
name: descriptive-kebab-name
description: "Third-person description. Use when: (1) ..., (2) .... Covers: orchestration, parallel agents, topic."
metadata:
  version: 1.0.0
---

# Skill Title

## Problem
[2-3 sentences max.]

## Quick Check
```bash
./scripts/extract.sh --summary          # Pre-processing (deterministic)
./scripts/apply-fixes.sh --all --dry-run  # Post-processing (deterministic)
```

## Full Workflow (Orchestration Pattern)

### Step 1: Extract Data (Script)
```bash
MANIFEST=$(./scripts/extract.sh --json)
```

### Step 2: Launch Parallel Agents
Launch N parallel `general-purpose` agents via the Task tool — one per <domain>.
Each agent receives its slice of data and saves results to `/tmp/<skill>-report-<domain>.json`.

### Step 3: Apply Fixes (Script)
```bash
./scripts/apply-fixes.sh --all --dry-run    # Preview
./scripts/apply-fixes.sh --all              # Apply
```

### Step 4: Validate
```bash
npm run validate  # Or whatever validation command applies
```

## Agent Definitions
- `orchestrator-agent.md` — pure orchestrator, delegates everything
- `specialist-agent.md` — focused sub-agent, NOT user-invocable

## See Also
[Cross-references to related skills.]
```

## Quality Checklist

**Decomposition & agents:**
- [ ] Decomposition evaluated: can this be split into parallel sub-agents?
- [ ] If yes: orchestrator defined as pure delegator (never does the work itself)
- [ ] Independent agents launched in SINGLE Task tool message (not sequentially)
- [ ] Each sub-agent has single focused responsibility
- [ ] Sub-agents use appropriate model tier (haiku/sonnet/opus)
- [ ] Agent definitions include structured output format

**Scripts & determinism:**
- [ ] Script-first evaluated: can deterministic parts be captured in scripts?
- [ ] If yes: script written first, SKILL.md references it (not duplicates it)
- [ ] Scripts have `--help` and `--fix`/`--dry-run` support and are executable

**Structure & content:**
- [ ] SKILL.md body ≤ 500 lines
- [ ] Description ≤ 1024 chars, third person, with trigger conditions, double-quoted single-line
- [ ] Frontmatter has only `name`, `description`, `metadata`
- [ ] References are one level deep from SKILL.md
- [ ] All cross-reference links resolve to existing files

## Anti-Patterns

- **Sequential when parallel is possible** — if agents don't depend on each other's
  output, launch them in a SINGLE message. Sequential = N x latency for no reason.
- **Monolithic agent** — one agent doing 5 things. Split into 5 focused agents.
- **Orchestrator doing work** — the orchestrator should delegate, not fetch/validate/enrich.
- **Missing structured output** — agents returning prose instead of parseable JSON/reports
  forces the orchestrator to guess at results.
- **Verbose explanations** — Claude knows what PDFs are. Skip the intro paragraph.
- **Too many options** — provide a default with escape hatch, not 5 alternatives.
- **Deeply nested references** — SKILL.md → ref.md → detail.md causes partial reads.
- **Time-sensitive info** — "After August 2025, use X" becomes stale. Use "Current method" / "Legacy" sections.
- **Inconsistent terminology** — pick one term ("endpoint" not alternating "URL/route/path").
- **Non-standard frontmatter** — `author`, `date`, `tags` waste tokens and aren't used.
- **Incomplete CLI templates in agents** — when agents create GitHub artifacts (`gh issue
  create`, `gh pr create`), include ALL metadata flags (`--label`, `--assignee`,
  `--milestone`) explicitly in the template. Agents improvise missing fields with
  plausible-but-wrong values (e.g., `dependencies` label instead of project's `dependabot`
  label). Include a selection guide for dynamic fields like priority labels.

## Optimizing Existing Skills

When a skill exceeds 500 lines, has poor structure, or runs slowly:

1. **Audit for parallelization** — identify independent subtasks that could be agents
2. **Decompose monolithic agents** — split "does everything" agents into focused specialists
3. **Extract scripts/** — move deterministic procedures out of agent prompts
4. **Extract references/** — move lookup tables and code examples
5. **Replace inline content** with links:
   `See **[references/your-file.md](references/your-file.md)** for the full lookup table.`
6. **Validate cross-references** — grep for `references/` and `scripts/` links, verify all exist
7. **Fix stale cross-references** — search for skill names that no longer exist
8. **Bump version** — minor for content reorganization, major for agent architecture changes

## See Also
- `claudeception` — when to extract knowledge into skills (the WHY/WHEN)
- Anthropic docs: [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- GitHub: [skill-authoring](https://github.com/abhattacherjee/claude-code-skills/tree/main/skill-authoring) — install instructions, changelog, and releases
