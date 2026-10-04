---
name: shield
description: "Was the context-shield skill (/context-shield still works as a phrase). Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count. Use when: (1) reading 3+ large external sources (URLs, Figma frames, wiki pages), (2) large documentation/API reference sites decomposed into section URLs, (3) monorepo code audits across many directories, (4) dependency upgrade research across 5+ packages, (5) large PR reviews with 15+ changed files, (6) competitive feature matrix analysis, (7) security advisory triage for dependency updates."
metadata:
  version: 1.0.0
---

# Context Shield

Prevents context overflow by delegating token-heavy content reads to isolated sub-agents. Each agent absorbs the full content in its own context and returns a compact summary (~500 tokens) to the parent. For large workloads, integrates with `/ralph-loop` to process content across multiple iterations.

## When to Use

| Signal | Action |
|--------|--------|
| Task needs 3+ large sources (URLs, Figma, files) | Use shield (auto-detects mode) |
| Single source is very large but manageable | Just use a single Agent call — no manifest needed |
| You're about to `WebFetch` 5+ pages in the parent context | Stop — use shield instead |
| Figma design has 10+ frames to analyze | Use shield (likely auto-ralph) |
| GitHub wiki has many pages | Use shield (likely auto-ralph) |
| Large documentation site (10+ pages) | Break into section URLs, shield auto-ralphs |
| API reference with many endpoint pages | Break into per-endpoint or per-section URLs |
| Monorepo code audit across many directories | Use `codebase` type with glob patterns per layer |
| Dependency upgrade research (5+ packages) | Fetch changelogs/release notes per package |
| Large PR review (15+ changed files) | Use `file` type, one per changed file |
| Competitive feature matrix (5+ competitors) | Use `url` type for each feature/pricing page |
| Security advisory review for dependency updates | Fetch CVE/advisory pages per vulnerability |
| >6 sources at batch-size 3 | Auto-ralph activates (>2 batches) |

## Quick Check

```bash
# Create manifest from sources
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Analyze competitor UIs" --output-dir /tmp/cs-run \
  "url:https://dribbble.com/shots/travel-app,label=Dribbble Travel" \
  "figma:fileKey=xYz,nodeId=5:42,label=Current Homepage"

# Check progress
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" status --manifest /tmp/cs-run/manifest.json

# Get next batch (each item carries the manifest's task)
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" next-batch --manifest /tmp/cs-run/manifest.json

# Record a source the agent could not read
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" mark-failed --manifest /tmp/cs-run/manifest.json --index 1 --reason "404 not found"

# Collect all summaries
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" summaries --manifest /tmp/cs-run/manifest.json

# Visualize workflow (full animated demo)
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" full-demo
```

## Visualization

Run `visualize.sh` at each workflow phase to show animated progress:

```bash
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" manifest --task "Analyze designs" --count 8     # Phase: manifest created
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" dispatch --batch 1 --labels "Home,Search,Results,Detail"  # Phase: agents leave
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" working --labels "Home,Search,Results,Detail"    # Phase: agents working
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" return --batch 1 --labels "Home,Search,Results,Detail"    # Phase: agents return
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" ralph-iter --iteration 1 --remaining 4           # Phase: ralph boundary
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" synthesize --done 8 --total 8                    # Phase: combining
"${CLAUDE_SKILL_DIR}/scripts/visualize.sh" complete --task "Analyze designs"                 # Phase: done
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

`<OUTPUT_DIR>` stands for a fresh directory for this run, such as `/tmp/cs-<TIMESTAMP>`. Write the same path in every later command.

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create \
  --task "Brief description of what you're looking for" \
  --output-dir "<OUTPUT_DIR>" \
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
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" next-batch --manifest "<OUTPUT_DIR>/manifest.json"
```

2. For each item in the batch, launch a `context:content-distiller` agent in parallel (SINGLE message). The agent's own definition is its instructions, so the prompt is only the item. `next-batch` has already added the manifest's `task` to each item, and the agent reads it to judge what matters:
```javascript
Agent({
  subagent_type: "context:content-distiller",
  model: "sonnet",
  description: "Distill [label]",
  prompt: JSON.stringify(item)
})
```

3. After agents return, record each result. If the agent's reply starts with `FAILED:` (404, login wall, empty page, missing file), mark the source failed with the text after `FAILED:` as the reason, so a dead page is never stored as a finding:
```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" mark-failed \
  --manifest "<OUTPUT_DIR>/manifest.json" \
  --index N \
  --reason "why the source could not be read"
```
Otherwise mark it done:
```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" mark-done \
  --manifest "<OUTPUT_DIR>/manifest.json" \
  --index N \
  --summary "the agent's distilled summary"
```

4. Check status — if items remain, repeat for the next batch. If status says `BLOCKED`, only failed sources are left: fix the source or tell the user which ones failed, and retry one with `mark-done`. Then proceed to Step 4 (Synthesize). `summaries` lists failed sources apart from the summaries, so say so in the report.

### Step 3b: Ralph Mode (>2 batches)

Delegate the entire batch-processing loop to `/ralph-loop`. Each iteration gets a fresh context, processes one batch, and exits. The manifest on disk is the only shared state.

**Invoke ralph-loop with this pattern:**

```
/ralph-loop Process one batch per iteration from shield manifest OUTPUT_DIR/manifest.json then exit. Scripts at ${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh. Each iteration: check status, if COMPLETE or BLOCKED then collect summaries and synthesize and name any failed sources and output promise DONE, otherwise get next-batch, spawn 3 parallel agents of subagent type context:content-distiller with sonnet model, passing each item as the prompt, mark each done or mark-failed when the agent reply starts with FAILED, then exit so ralph gives a fresh context for the next batch. --completion-promise DONE --max-iterations MAX
```

**Replace** `OUTPUT_DIR` and `MAX` with actual values. The script path is already filled in. Set `MAX` to `TOTAL_BATCHES + 2` (extra headroom for the synthesis iteration and any retries).

**Important: keep the ralph-loop prompt as a single simple string.** The Skill tool is sensitive to special characters — avoid parentheses, angle brackets, and multi-line formatting in the args.

**How ralph-loop processes each iteration:**
1. Reads manifest from disk → checks status
2. If COMPLETE or BLOCKED (only failed sources left) → collects summaries, synthesizes report and names the failed sources, outputs `<promise>DONE</promise>`
3. Otherwise → gets next batch (items already carry the task), spawns parallel content-distiller agents
4. Marks items done with summaries, or failed with a reason → exits
5. Stop hook feeds the same prompt back → next iteration with fresh context

**Token economics:**
- Each iteration: ~50K tokens (batch of 3 web pages in sub-agents + orchestration overhead)
- Without ralph: 12 sources × ~50K = 600K tokens in one context (impossible)
- With ralph: 4 iterations × ~50K each, but each starts fresh (works perfectly)

### Step 4: Synthesize

Collect all distilled summaries:

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" summaries --manifest "<OUTPUT_DIR>/manifest.json"
```

The summaries output is compact — each source compressed to ~500 tokens. Use this to:
- Write a synthesis report
- Make design decisions
- Feed into another skill (e.g., `figma-ui-designer`, `spec:review`)
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

- **`context:content-distiller`** (`agents/content-distiller.md` in this plugin) — reads one source, returns distilled summary. Model: `sonnet`. NOT user-invocable.

## Common Patterns

### Figma Design Analysis (10+ frames)

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Analyze all Figma frames for design system" \
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
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Analyze competitor booking UIs" \
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
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Comprehensive analysis of MCP protocol" \
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
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Extract architecture decisions from wiki" \
  --output-dir /tmp/cs-wiki --batch-size 5 \
  "wiki:https://github.com/org/repo/wiki/Architecture,label=Architecture" \
  "wiki:https://github.com/org/repo/wiki/API-Reference,label=API Ref" \
  "wiki:https://github.com/org/repo/wiki/Data-Model,label=Data Model" \
  "wiki:https://github.com/org/repo/wiki/Deployment,label=Deployment" \
  "wiki:https://github.com/org/repo/wiki/Security,label=Security"
```

### API Reference / Framework Docs

Break a multi-page API reference into per-section URLs. Works for any vendor docs (OpenAI, Stripe, Twilio, AWS, etc.).

```bash
# Example: OpenAI API reference (9 pages, auto-ralph)
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Comprehensive OpenAI API reference" \
  --output-dir /tmp/cs-openai --batch-size 3 \
  "url:https://platform.openai.com/docs/api-reference/chat,label=Chat Completions" \
  "url:https://platform.openai.com/docs/api-reference/embeddings,label=Embeddings" \
  "url:https://platform.openai.com/docs/api-reference/fine-tuning,label=Fine-tuning" \
  "url:https://platform.openai.com/docs/api-reference/batch,label=Batch API" \
  "url:https://platform.openai.com/docs/api-reference/uploads,label=Uploads" \
  "url:https://platform.openai.com/docs/api-reference/images,label=Images" \
  "url:https://platform.openai.com/docs/api-reference/models,label=Models" \
  "url:https://platform.openai.com/docs/api-reference/moderations,label=Moderations" \
  "url:https://platform.openai.com/docs/api-reference/assistants,label=Assistants"
```

### Monorepo Code Audit

Use `codebase` type to scan patterns across directories. Use batch-size 4-5 since code files are lighter than web pages.

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Audit error handling across service layers" \
  --output-dir /tmp/cs-audit --batch-size 4 \
  "codebase:backend/src/services/**/*.ts,label=Backend Services" \
  "codebase:backend/src/routes/**/*.ts,label=API Routes" \
  "codebase:backend/src/middleware/**/*.ts,label=Middleware" \
  "codebase:mcp-events-server/src/**/*.ts,label=MCP Server" \
  "codebase:frontend/src/services/**/*.ts,label=Frontend Services"
```

### Dependency Upgrade Research

Fetch changelogs and migration guides before a major upgrade. Label with version ranges.

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Research breaking changes for dependency upgrade" \
  --output-dir /tmp/cs-deps --batch-size 3 \
  "url:https://github.com/expressjs/express/releases,label=Express Releases" \
  "url:https://github.com/vitejs/vite/blob/main/packages/vite/CHANGELOG.md,label=Vite Changelog" \
  "url:https://github.com/vitest-dev/vitest/releases,label=Vitest Releases" \
  "url:https://github.com/microsoft/playwright/releases,label=Playwright Releases" \
  "url:https://github.com/usebruno/bruno/releases,label=Bruno Releases" \
  "url:https://github.com/tailwindlabs/tailwindcss/releases,label=Tailwind Releases"
```

### Large PR Review (many changed files)

Distill each changed file's diff to review a large PR without exhausting context.

```bash
# Generate file list from git diff, then create manifest
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Review PR changes for feature X" \
  --output-dir /tmp/cs-pr --batch-size 5 \
  "file:backend/src/services/eventService.ts,label=eventService" \
  "file:backend/src/services/sessionService.ts,label=sessionService" \
  "file:backend/src/routes/recommendations.ts,label=recommendations route" \
  "file:frontend/src/components/Results.tsx,label=Results component" \
  "file:frontend/src/components/Questionnaire.tsx,label=Questionnaire" \
  "file:mcp-events-server/src/tools/recommend.ts,label=MCP recommend tool"
```

### Competitive Feature Matrix

Analyze pricing/feature pages across competitors to build a comparison matrix.

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Compare vacation rental platform features" \
  --output-dir /tmp/cs-compete --batch-size 3 \
  "url:https://www.airbnb.com/help/article/2503,label=Airbnb Host Features" \
  "url:https://www.vrbo.com/discoveryhub/tips-and-resources,label=VRBO Features" \
  "url:https://www.booking.com/content/about.html,label=Booking.com About" \
  "url:https://www.tripadvisor.com/business,label=TripAdvisor Business" \
  "url:https://www.expedia.com/partner-solutions,label=Expedia Partners" \
  "url:https://www.hotels.com/page/about-us,label=Hotels.com About"
```

### Security Advisory Review

Fetch and distill CVE/advisory pages when triaging dependency vulnerabilities.

```bash
"${CLAUDE_SKILL_DIR}/scripts/manage-manifest.sh" create --task "Assess security advisories for dependency update" \
  --output-dir /tmp/cs-security --batch-size 4 \
  "url:https://github.com/advisories/GHSA-xxxx-yyyy-zzzz,label=minimatch ReDoS" \
  "url:https://github.com/advisories/GHSA-aaaa-bbbb-cccc,label=express path traversal" \
  "url:https://nvd.nist.gov/vuln/detail/CVE-2024-NNNNN,label=CVE-2024-NNNNN" \
  "url:https://snyk.io/vuln/SNYK-JS-EXAMPLE,label=Snyk Advisory"
```

## See Also

- `figma-ui-designer` — use shield when analyzing 10+ Figma frames or 5+ competitor designs
- `spec:review` — use shield when a spec references many external docs or code directories
- `project-code-review` — use shield for large PRs with 15+ changed files
- `npm-dependency-management` — use shield to research 5+ package changelogs before upgrades
- `ci-security-issue-creator` — use shield to triage many CVE/GHSA advisory pages
- `context:search` — use shield when summarizing multiple large conversations at once
- `ralph-loop` plugin — provides the iteration mechanism for multi-batch processing
- `context:content-distiller` agent — the isolated reader
