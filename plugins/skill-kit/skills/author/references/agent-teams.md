<!-- Moved verbatim from SKILL.md (2.6.1) so SKILL.md stays under the 500-line limit. -->

### Agent Teams Orchestration

Use Agent Teams when teammates need to **communicate with each other** across phases —
not just report back to an orchestrator.

#### When to Use Teams vs Sub-Agents

| Signal | Use Teams | Use Sub-Agents |
|--------|-----------|----------------|
| Multi-phase workflow with feedback loops | ✓ | |
| Independent parallel tasks (fan-out) | | ✓ |
| Teammates need each other's findings | ✓ | |
| One-shot parallel analysis | | ✓ |
| Iterative creative workflow (design, video) | ✓ | |
| Quick research/validation | | ✓ |

#### Team Orchestration Pattern

```
TeamCreate("my-workflow")
├── TaskCreate tasks for each work item
├── Spawn teammates (Agent tool with team_name + name)
│   ├── Teammate A claims + works tasks
│   ├── Teammate B claims + works tasks
│   └── Teammates communicate via SendMessage
├── Lead monitors progress via TaskList
├── Lead synthesizes results
└── TeamDelete (cleanup)
```

#### Conditional Team Usage

Skills should support both modes — teams when available, sub-agents as fallback:

```markdown
## Orchestration Mode

Check `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`:
- **If enabled**: Use TeamCreate for persistent multi-phase coordination
- **If disabled** (default): Use parallel Agent tool calls (existing pattern)

Both modes produce identical results. Teams add inter-agent communication.
```

#### Complex Skill Template (Teams Variant)

When using teams instead of anonymous sub-agents:

```markdown
## Full Workflow (Team Orchestration)

### Step 1: Create Team
TeamCreate("my-workflow") → spawns shared task list.

### Step 2: Define Tasks
TaskCreate for each work item (extraction, validation, enrichment, etc.)

### Step 3: Spawn Named Teammates
Launch via Agent tool with `team_name` + `name` parameters.
Each teammate claims tasks from the shared list.

### Step 4: Monitor & Synthesize
Lead polls TaskList, teammates SendMessage findings to each other.
Lead collects completed results and generates final report.

### Step 5: Cleanup
TeamDelete("my-workflow")
```
