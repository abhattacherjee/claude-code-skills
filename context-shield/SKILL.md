---
name: context-shield
description: "Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Supports ralph-loop iterations for workloads too large for a single session. Use when: (1) task involves reading 3+ large external sources (URLs, Figma frames, wiki pages), (2) context is getting full from web fetches or file reads, (3) processing many Figma design frames, (4) analyzing competitor sites or design references in bulk, (5) reading a multi-page GitHub wiki or documentation site."
metadata:
  version: 1.1.0
---

# Context Shield

Prevents context overflow by delegating token-heavy content reads to isolated sub-agents. Each agent absorbs the full content in its own context and returns a compact summary (~500 tokens) to the parent. For large workloads, integrates with `/ralph-loop` to process content across multiple iterations.

## When to Use

| Signal | Action |
|--------|--------|
| Task needs 3+ large sources (URLs, Figma, files) | Use context-shield |
| Single source is very large but manageable | Just use a single Agent call — no manifest needed |
| You're about to `WebFetch` 5+ pages in the parent context | Stop — use context-shield instead |
| Figma design has 10+ frames to analyze | Use context-shield with figma sources |
| GitHub wiki has many pages | Use context-shield with wiki sources |

## Quick Check

```bash
SCRIPTS=~/.claude/skills/context-shield/scripts

# Create manifest from sources
$SCRIPTS/manage-manifest.sh create --task "Analyze competitor UIs" --output-dir /tmp/cs-run \
  "url:https://dribbble.com/shots/travel-app,label=Dribbble Travel" \
  "figma:fileKey=xYz,nodeId=5:42,label=Current Homepage"

# Check progress
$SCRIPTS/manage-manifest.sh status --manifest /tmp/cs-run/manifest.json

# Get next batch
$SCRIPTS/manage-manifest.sh next-batch --manifest /tmp/cs-run/manifest.json

# Collect all summaries
$SCRIPTS/manage-manifest.sh summaries --manifest /tmp/cs-run/manifest.json

# Visualize workflow (full animated demo)
$SCRIPTS/visualize.sh full-demo
```

## Visualization

Run `visualize.sh` at each workflow phase to show animated progress:

```bash
VIZ=~/.claude/skills/context-shield/scripts/visualize.sh

$VIZ manifest --task "Analyze designs" --count 8     # Phase: manifest created
$VIZ dispatch --batch 1 --labels "Home,Search,Results,Detail"  # Phase: agents leave
$VIZ working --labels "Home,Search,Results,Detail"    # Phase: agents working
$VIZ return --batch 1 --labels "Home,Search,Results,Detail"    # Phase: agents return
$VIZ ralph-iter --iteration 1 --remaining 4           # Phase: ralph boundary
$VIZ synthesize --done 8 --total 8                    # Phase: combining
$VIZ complete --task "Analyze designs"                 # Phase: done
```

**Call these at each workflow step** — they show agents being dispatched through the context boundary, working in isolation, and returning with distilled summaries. Use `--speed slow` for demos, `SPEED=instant` to skip in CI.

---

## Workflow

### Step 1: Identify Content Sources

List all content that needs reading. Classify each by type:

| Type | Example | Agent reads with |
|------|---------|-----------------|
| `url` | Web page, blog post, documentation | `WebFetch` |
| `figma` | Figma design frame | `get_design_context` |
| `file` | Large local file (spec, log, data) | `Read` |
| `wiki` | GitHub wiki page | `WebFetch` |
| `codebase` | Code directory or pattern | `Glob` + `Read` + `Grep` |

### Step 2: Create Manifest

```bash
SCRIPTS=~/.claude/skills/context-shield/scripts
OUTPUT_DIR="/tmp/cs-$(date +%s)"

$SCRIPTS/manage-manifest.sh create \
  --task "Brief description of what you're looking for" \
  --output-dir "$OUTPUT_DIR" \
  --batch-size 4 \
  "type:location,label=Name" \
  "type:location,label=Name" \
  ...
```

**Batch size guidance:**
- 3-4 for token-heavy sources (full web pages, Figma designs)
- 5-6 for lighter sources (short files, focused searches)
- Smaller batches = more iterations but less risk of agent context overflow

### Step 3: Process Current Batch

Get the next batch and spawn parallel agents — one per source:

```bash
BATCH=$($SCRIPTS/manage-manifest.sh next-batch --manifest "$OUTPUT_DIR/manifest.json")
```

For each item in the batch, launch a `content-distiller` agent in parallel (SINGLE message):

```
Agent({
  subagent_type: "general-purpose",
  model: "sonnet",
  description: "Distill [label]",
  prompt: `You are the content-distiller agent. Follow the instructions in ~/.claude/agents/content-distiller.md.

${JSON.stringify(item)}
`
})
```

**Launch all batch agents in ONE message** — they run in parallel.

After each agent returns, mark the item done:

```bash
$SCRIPTS/manage-manifest.sh mark-done \
  --manifest "$OUTPUT_DIR/manifest.json" \
  --index N \
  --summary "the agent's distilled summary"
```

### Step 4: Check Progress

```bash
$SCRIPTS/manage-manifest.sh status --manifest "$OUTPUT_DIR/manifest.json"
```

**If all done** → proceed to Step 5 (Synthesize).
**If items remain** → process the next batch (repeat Step 3), OR use ralph-loop for auto-iteration (Step 4b).

### Step 4b: Ralph-Loop for Multi-Batch Processing

When the workload is too large for a single session (>3 batches or context is getting full), hand off to `/ralph-loop`:

```
/ralph-loop Process content sources using context-shield.

Read manifest: $OUTPUT_DIR/manifest.json
Check status: $SCRIPTS/manage-manifest.sh status --manifest $OUTPUT_DIR/manifest.json

For each iteration:
1. Get next batch: $SCRIPTS/manage-manifest.sh next-batch --manifest $OUTPUT_DIR/manifest.json
2. For each item in batch, spawn a content-distiller agent (parallel)
3. Mark each done with its summary
4. Check status — if COMPLETE, synthesize and output <promise>DONE</promise>

--completion-promise "DONE" --max-iterations 10
```

Each ralph-loop iteration:
- Gets a fresh context (no accumulated token debt)
- Reads manifest from disk to find remaining items
- Processes one batch of parallel agents
- Marks items done and saves summaries to manifest
- Exits → stop hook feeds the prompt back for next iteration
- When all items are done, outputs `<promise>DONE</promise>` to end the loop

### Step 5: Synthesize

Collect all distilled summaries:

```bash
$SCRIPTS/manage-manifest.sh summaries --manifest "$OUTPUT_DIR/manifest.json"
```

The summaries output is compact — each source compressed to ~500 tokens. Use this to:
- Write a synthesis report
- Make design decisions
- Feed into another skill (e.g., `figma-ui-designer`, `spec-review`)
- Answer the user's original question

---

## Architecture

```
Parent Orchestrator (lean — never reads raw content)
│
├── manage-manifest.sh          (deterministic: create, track, collect)
│
├── content-distiller agent 1   (isolated context: reads URL, returns ~500 tokens)
├── content-distiller agent 2   (isolated context: reads Figma, returns ~500 tokens)
├── content-distiller agent 3   (isolated context: reads file, returns ~500 tokens)
├── content-distiller agent 4   (isolated context: reads wiki, returns ~500 tokens)
│   └── (batch 1 — parallel)
│
├── [ralph-loop iteration boundary — fresh context]
│
├── content-distiller agent 5   (isolated context)
├── content-distiller agent 6   (isolated context)
│   └── (batch 2 — parallel)
│
└── Synthesis (all summaries fit in parent context)
```

**Token math example:**
- 10 web pages at ~50K tokens each = 500K tokens (impossible in parent)
- 10 agent summaries at ~500 tokens each = 5K tokens (easily fits)
- 2 ralph-loop iterations of 5 agents each = fresh context per iteration

## Content Source Format

```
type:key1=value1,key2=value2,label=Human Name
```

| Type | Required Fields | Example |
|------|----------------|---------|
| `url` | URL as location | `url:https://example.com/page,label=Docs` |
| `figma` | `fileKey`, `nodeId` | `figma:fileKey=abc,nodeId=1:2,label=Hero` |
| `file` | File path as location | `file:/path/to/spec.md,label=Story Spec` |
| `wiki` | Wiki URL as location | `wiki:https://github.com/org/repo/wiki/Page,label=Architecture` |
| `codebase` | Glob pattern as location | `codebase:src/services/**/*.ts,label=Services` |

## Agent Definition

- **`content-distiller`** (`~/.claude/agents/content-distiller.md`) — reads one source, returns distilled summary. Model: `sonnet`. NOT user-invocable.

## Common Patterns

### Figma Design Analysis (10+ frames)

```bash
$SCRIPTS/manage-manifest.sh create --task "Analyze all Figma frames for design system" \
  --output-dir /tmp/cs-figma --batch-size 3 \
  "figma:fileKey=abc,nodeId=1:2,label=Homepage" \
  "figma:fileKey=abc,nodeId=3:4,label=Search" \
  "figma:fileKey=abc,nodeId=5:6,label=Results" \
  "figma:fileKey=abc,nodeId=7:8,label=Detail" \
  "figma:fileKey=abc,nodeId=9:10,label=Checkout" \
  "figma:fileKey=abc,nodeId=11:12,label=Profile" \
  "figma:fileKey=abc,nodeId=13:14,label=Settings" \
  "figma:fileKey=abc,nodeId=15:16,label=Mobile Home" \
  "figma:fileKey=abc,nodeId=17:18,label=Mobile Search" \
  "figma:fileKey=abc,nodeId=19:20,label=Mobile Detail"
```

### Competitor Research (many URLs)

```bash
$SCRIPTS/manage-manifest.sh create --task "Analyze competitor booking UIs" \
  --output-dir /tmp/cs-competitors --batch-size 4 \
  "url:https://booking.com,label=Booking.com" \
  "url:https://airbnb.com,label=Airbnb" \
  "url:https://vrbo.com,label=VRBO" \
  "url:https://tripadvisor.com,label=TripAdvisor" \
  "url:https://expedia.com,label=Expedia" \
  "url:https://hotels.com,label=Hotels.com"
```

### GitHub Wiki Crawl

```bash
$SCRIPTS/manage-manifest.sh create --task "Extract architecture decisions from wiki" \
  --output-dir /tmp/cs-wiki --batch-size 5 \
  "wiki:https://github.com/org/repo/wiki/Architecture,label=Architecture" \
  "wiki:https://github.com/org/repo/wiki/API-Reference,label=API Ref" \
  "wiki:https://github.com/org/repo/wiki/Data-Model,label=Data Model" \
  "wiki:https://github.com/org/repo/wiki/Deployment,label=Deployment" \
  "wiki:https://github.com/org/repo/wiki/Security,label=Security"
```

## See Also

- `figma-ui-designer` — spawns this skill's pattern when processing many Figma frames
- `ralph-loop` plugin — provides the iteration mechanism for multi-batch processing
- `content-distiller` agent (`~/.claude/agents/content-distiller.md`) — the isolated reader
- `conversation-summarizer` agent — similar distillation pattern for conversation content
