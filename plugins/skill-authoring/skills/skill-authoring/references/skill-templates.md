<!-- Moved verbatim from SKILL.md (2.6.1) so SKILL.md stays under the 500-line limit. -->

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

### Complex Skill (orchestrator + parallel agents + scripts + task tracking)

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
./scripts/task-manifest.sh full-run     # Task checklist for full workflow
```

## Progress Tracking (MANDATORY)

Create task checklist from `scripts/task-manifest.sh full-run` before starting.
Mark `in_progress` → `completed` per phase. On abort, mark remaining `deleted`.

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
