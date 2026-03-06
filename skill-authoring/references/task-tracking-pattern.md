# Task Tracking Pattern

Full reference for adding progress tracking to Claude Code skills with long-running
workflows (3+ phases or >2 minutes).

## Task Manifest Script Template

Every skill with tracking should include `scripts/task-manifest.sh`:

```bash
#!/usr/bin/env bash
# task-manifest.sh — Emit task definitions for each workflow
# Usage: ./scripts/task-manifest.sh <workflow-name>

case "${1:-}" in
  full-audit)
    cat <<'JSON'
[
  {"subject":"Inventory open issues","activeForm":"Scanning open issues","description":"Fetch all open issues and detect duplicates"},
  {"subject":"Verify against codebase","activeForm":"Verifying issues against codebase","description":"Launch parallel agents to check each issue"},
  {"subject":"Close resolved issues","activeForm":"Closing resolved issues","description":"Close issues with evidence comments"},
  {"subject":"Update descriptions","activeForm":"Updating issue descriptions","description":"Add Current Codebase State sections"},
  {"subject":"Apply labels","activeForm":"Labeling and prioritizing","description":"Apply priority and category labels"}
]
JSON
    ;;
  quick-check)
    cat <<'JSON'
[
  {"subject":"Scan issues","activeForm":"Scanning issues","description":"Quick inventory of open issues"},
  {"subject":"Spot-check top 10","activeForm":"Spot-checking issues","description":"Verify the 10 highest-priority issues"}
]
JSON
    ;;
  --list)
    echo "full-audit quick-check"
    ;;
  -h|--help)
    echo "Usage: task-manifest.sh <workflow>"
    echo "Workflows: full-audit, quick-check"
    echo "Use --list for machine-readable workflow names"
    ;;
  *)
    echo "Error: unknown workflow '${1:-}'. Use --list or --help." >&2
    exit 1
    ;;
esac
```

## Task Fields

| Field | Purpose | Style |
|-------|---------|-------|
| `subject` | Task title in imperative form | "Run tests", "Apply fixes" |
| `activeForm` | Present continuous shown in spinner | "Running tests", "Applying fixes" |
| `description` | Detailed context for the task | What inputs, what outputs, acceptance criteria |

## Using the Manifest in SKILL.md

Add a "Progress Tracking (MANDATORY)" section:

````markdown
## Progress Tracking (MANDATORY)

Before starting, create the task checklist:
```bash
./scripts/task-manifest.sh full-audit
```

| # | subject | activeForm |
|---|---------|------------|
| 1 | Inventory open issues | Scanning open issues |
| 2 | Verify against codebase | Verifying issues against codebase |
| 3 | Close resolved issues | Closing resolved issues |
| 4 | Update descriptions | Updating issue descriptions |
| 5 | Apply labels | Labeling and prioritizing |

**Update rules:**
- Mark each task `in_progress` (TaskUpdate) immediately before starting it
- Mark each task `completed` immediately after it succeeds
- If a sub-agent handles multiple tasks, mark them all as `completed` after return
- If any task fails, keep it as `in_progress` and report the error
- On abort, mark remaining tasks as `deleted`
````

## Task Update Patterns

### Sequential phases
```
TaskUpdate(taskId=1, status="in_progress")
  → do work
TaskUpdate(taskId=1, status="completed")
TaskUpdate(taskId=2, status="in_progress")
  → do work
TaskUpdate(taskId=2, status="completed")
```

### Sub-agent handling multiple phases
```
TaskUpdate(taskId=5, status="in_progress")
  → launch sub-agent that handles phases 5-7
TaskUpdate(taskId=5, status="completed")
TaskUpdate(taskId=6, status="completed")
TaskUpdate(taskId=7, status="completed")
```

### Abort on failure
```
TaskUpdate(taskId=3, status="in_progress")
  → work fails
  # Keep task 3 as in_progress (not completed!)
TaskUpdate(taskId=4, status="deleted")
TaskUpdate(taskId=5, status="deleted")
  → report error to user
```

## Real-World Examples

### review-dependabot-prs (8 tasks)
```
1. Triage Dependabot PRs
2. Create hotfix branch from main
3. Apply safe dependencies
4. Run test suite on hotfix
5. Close Dependabot PRs
6. Prepare release artifacts
7. Deploy to production (merge + tag)
8. Sync develop and bump version
```
Tasks 6-8 are handled by the `release-pipeline` sub-agent.
Gate at task 4: if tests fail, tasks 4-8 are `deleted`.

### github-issue-triage (5 tasks)
```
1. Inventory open issues
2. Verify against codebase
3. Close resolved issues
4. Update descriptions
5. Apply labels
```
Task 2 launches parallel verification agents.
No abort gates — all phases always run.

### catalog-maintainer (6 tasks)
```
1. Backup catalogs
2. Fetch new content
3. Enrich with Google Places
4. Validate catalogs
5. Generate embeddings
6. Run tests
```
Gate at task 4: validation failure blocks embedding generation.

## Scaffolding a New Manifest

Use the generator script:

```bash
~/.claude/skills/skill-authoring/scripts/generate-task-manifest.sh \
  --skill-dir /path/to/my-skill \
  --workflows "full-audit:5,quick-check:2"
```

This creates `scripts/task-manifest.sh` with placeholder tasks. Edit the placeholders
to match your actual workflow steps.
