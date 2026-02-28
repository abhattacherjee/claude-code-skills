---
name: context-shield
description: "Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently. Use when: (1) task involves reading 3+ large external sources (URLs, Figma frames, wiki pages), (2) context is getting full from web fetches or file reads, (3) processing many Figma design frames, (4) analyzing competitor sites or design references in bulk, (5) reading a multi-page GitHub wiki or documentation site, (6) reading a large website by breaking it into section URLs."
metadata:
  version: 1.2.0
---

# Context Shield

Prevents context overflow by delegating token-heavy content reads to isolated sub-agents. Each agent absorbs the full content in its own context and returns a compact summary (~500 tokens) to the parent. For large workloads, integrates with `/ralph-loop` to process content across multiple iterations.

## When to Use

| Signal | Action |
|--------|--------|
| Task needs 3+ large sources (URLs, Figma, files) | Use context-shield (auto-detects mode) |
| Single source is very large but manageable | Just use a single Agent call — no manifest needed |
| You're about to `WebFetch` 5+ pages in the parent context | Stop — use context-shield instead |
| Figma design has 10+ frames to analyze | Use context-shield (likely auto-ralph) |
| GitHub wiki has many pages | Use context-shield (likely auto-ralph) |
| Large documentation site (10+ pages) | Break into section URLs, context-shield auto-ralphs |
| >6 sources at batch-size 3 | Auto-ralph activates (>2 batches) |

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
  --batch-size 3 \
  "type:location,label=Name" \
  "type:location,label=Name" \
  ...
```

**Batch size guidance:**
- 3 for token-heavy sources (full web pages, Figma designs) — **default**
- 4-5 for lighter sources (short files, focused searches)
- Smaller batches = more iterations but less risk of agent context overflow

### Step 3: Auto-Detect Processing Mode

Calculate total batches and **automatically choose** the processing mode:

```
TOTAL_SOURCES = number of sources in manifest
BATCH_SIZE = batch size from manifest
TOTAL_BATCHES = ceil(TOTAL_SOURCES / BATCH_SIZE)

if TOTAL_BATCHES <= 2:  → DIRECT MODE (process in current session)
if TOTAL_BATCHES > 2:   → RALPH MODE  (delegate to ralph-loop)
```

| Sources | Batch Size | Batches | Mode | Why |
|---------|-----------|---------|------|-----|
| 3-6 | 3 | 1-2 | Direct | Fits in single session context |
| 7-9 | 3 | 3 | Ralph | Context accumulates across 3+ batch cycles |
| 10+ | 3 | 4+ | Ralph | Would overflow single session context |
| 5-10 | 5 | 1-2 | Direct | Lighter sources, larger batches |

**This is automatic — do NOT ask the user which mode to use.**

### Step 3a: Direct Mode (≤2 batches)

Process all batches in the current session. For each batch:

1. Get next batch:
```bash
BATCH=$($SCRIPTS/manage-manifest.sh next-batch --manifest "$OUTPUT_DIR/manifest.json")
```

2. For each item in the batch, launch a `content-distiller` agent in parallel (SINGLE message):
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

3. After agents return, mark each done:
```bash
$SCRIPTS/manage-manifest.sh mark-done \
  --manifest "$OUTPUT_DIR/manifest.json" \
  --index N \
  --summary "the agent's distilled summary"
```

4. Check status — if items remain, repeat for the next batch. Then proceed to Step 4 (Synthesize).

### Step 3b: Ralph Mode (>2 batches)

Delegate the entire batch-processing loop to `/ralph-loop`. Each iteration gets a fresh context, processes one batch, and exits. The manifest on disk is the only shared state.

**Invoke ralph-loop with this pattern:**

```
/ralph-loop Process one batch per iteration from context-shield manifest OUTPUT_DIR/manifest.json then exit. Scripts at SCRIPTS/manage-manifest.sh. Each iteration: check status, if COMPLETE then collect summaries and synthesize and output promise DONE, otherwise get next-batch, spawn 3 parallel content-distiller agents with sonnet model and general-purpose subagent type, mark done, then exit so ralph gives a fresh context for the next batch. --completion-promise DONE --max-iterations MAX
```

**Replace** `OUTPUT_DIR`, `SCRIPTS`, and `MAX` with actual values. Set `MAX` to `TOTAL_BATCHES + 2` (extra headroom for the synthesis iteration and any retries).

**Important: keep the ralph-loop prompt as a single simple string.** The Skill tool is sensitive to special characters — avoid parentheses, angle brackets, and multi-line formatting in the args.

**How ralph-loop processes each iteration:**
1. Reads manifest from disk → checks status
2. If COMPLETE → collects summaries, synthesizes report, outputs `<promise>DONE</promise>`
3. Otherwise → gets next batch, spawns parallel content-distiller agents
4. Marks items done with summaries → exits
5. Stop hook feeds the same prompt back → next iteration with fresh context

**Token economics:**
- Each iteration: ~50K tokens (batch of 3 web pages in sub-agents + orchestration overhead)
- Without ralph: 12 sources × ~50K = 600K tokens in one context (impossible)
- With ralph: 4 iterations × ~50K each, but each starts fresh (works perfectly)

### Step 4: Synthesize

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

### Large Website / Documentation Site (auto-ralph)

Break a single large site into section URLs. With 12 sources at batch-size 3 = 4 batches → **ralph mode auto-activates**.

```bash
# Example: MCP documentation (12 pages, auto-ralph)
$SCRIPTS/manage-manifest.sh create --task "Comprehensive analysis of MCP protocol" \
  --output-dir /tmp/cs-mcp --batch-size 3 \
  "url:https://modelcontextprotocol.io/introduction,label=Introduction" \
  "url:https://modelcontextprotocol.io/docs/concepts/architecture,label=Architecture" \
  "url:https://modelcontextprotocol.io/docs/concepts/resources,label=Resources" \
  "url:https://modelcontextprotocol.io/docs/concepts/tools,label=Tools" \
  "url:https://modelcontextprotocol.io/docs/concepts/prompts,label=Prompts" \
  "url:https://modelcontextprotocol.io/docs/concepts/sampling,label=Sampling" \
  "url:https://modelcontextprotocol.io/docs/concepts/transports,label=Transports" \
  "url:https://modelcontextprotocol.io/docs/concepts/roots,label=Roots" \
  "url:https://modelcontextprotocol.io/docs/guides/building-servers,label=Building Servers" \
  "url:https://modelcontextprotocol.io/docs/guides/building-clients,label=Building Clients" \
  "url:https://modelcontextprotocol.io/specification/2025-03-26,label=Specification" \
  "url:https://modelcontextprotocol.io/development/updates,label=Updates"
# 12 sources / batch 3 = 4 batches → auto-detects ralph mode
# Result: ~100:1 compression, each iteration uses fresh context
```

**How to decompose a large site**: Identify the top-level navigation or sitemap sections. Each page becomes one source. Label clearly — these labels appear in the final synthesis report.

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
