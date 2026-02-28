---
name: figma-ui-designer
description: "Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code. Use when: (1) user asks for Figma mockups or UI designs, (2) user shares a Figma URL to use as input for a spec or plan, (3) starting a new project and needs Figma designs, (4) mocking up a feature enhancement, (5) user wants to translate a Figma design into implementation requirements."
metadata:
  version: 3.0.0
---

# Figma UI Designer

Interactive design skill that brainstorms with users, tracks progress, and delivers Figma-native mockups. Also extracts existing Figma designs as structured input for specs, plans, and implementation.

## Phase 0: Brainstorm & Plan

**ALWAYS start here.** Before building anything, brainstorm with the user.

### Step 0a: Gather Context

Read the spec, user description, or project requirements. Identify:
- What screens/components need design
- What the design should communicate
- Technical constraints (framework, responsive, dark mode, i18n)

### Step 0b: Present Design Options

Use `AskUserQuestion` with `markdown` previews to present 2-4 design directions. Each option should include an ASCII mockup showing the visual approach.

**Example — pill badge design options:**
```
AskUserQuestion({
  questions: [{
    question: "Which design direction for the duration pill badge?",
    header: "Design",
    options: [
      {
        label: "Option A: Subtitle",
        description: "Muted text line below the pill badge",
        markdown: "┌─────────────────────────────┐\n│  📅  7 nights               │\n└─────────────────────────────┘\n   ↳ That's 8 calendar days\n\nPros: Always visible\nCons: Adds vertical space"
      },
      {
        label: "Option B: Dual Pills",
        description: "Two separate pill badges side by side",
        markdown: "┌──────────────┐ ┌──────────────┐\n│ 🌙 7 nights  │ │ 📅 8 days    │\n└──────────────┘ └──────────────┘\n\nPros: Clearest comparison\nCons: More visual weight"
      },
      {
        label: "Option C: Parenthetical (Recommended)",
        description: "Days count added inline in parentheses",
        markdown: "┌──────────────────────────────────┐\n│  📅  7 nights (8 days)           │\n└──────────────────────────────────┘\n\nPros: Minimal change, single pill\nCons: Pill slightly wider"
      }
    ],
    multiSelect: false
  }]
})
```

**For new project designs**, present aesthetic directions:

```
AskUserQuestion({
  questions: [
    {
      question: "What aesthetic direction for the UI?",
      header: "Aesthetic",
      options: [
        {
          label: "Organic & Natural",
          description: "Earthy tones, soft curves, nature-inspired",
          markdown: "Color: #5f7355 olive, #8B7355 warm brown\nFont:  Lora (serif headings)\n       Montserrat (clean body)\nVibe:  Calm, premium, artisanal\n\n┌─────────────────────────────┐\n│  ╭───────────────────────╮  │\n│  │  Discover Your Escape │  │\n│  ╰───────────────────────╯  │\n│                             │\n│  [ Plan My Journey  →  ]   │\n└─────────────────────────────┘"
        },
        {
          label: "Bold & Modern",
          description: "High contrast, geometric, dynamic",
          markdown: "Color: #1a1a2e deep navy, #e94560 accent\nFont:  Space Grotesk (bold headings)\n       Inter (minimal body)\nVibe:  Tech-forward, energetic\n\n┌─────────────────────────────┐\n│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │\n│ ▓  DISCOVER YOUR ESCAPE   ▓ │\n│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │\n│                             │\n│  [ GET STARTED ▶ ]          │\n└─────────────────────────────┘"
        }
      ],
      multiSelect: false
    },
    {
      question: "Which variants do you need?",
      header: "Variants",
      options: [
        { label: "All 4", description: "Desktop + Mobile, Light + Dark" },
        { label: "Desktop only", description: "Light + Dark, desktop viewport" },
        { label: "Light only", description: "Desktop + Mobile, light theme" },
        { label: "Desktop Light only", description: "Single variant" }
      ],
      multiSelect: false
    }
  ]
})
```

### Step 0c: Create Task List

After the user picks a direction, create a trackable task list using `TaskCreate`:

```
TaskCreate({ subject: "Extract design tokens", description: "Run extract-design-tokens.sh", activeForm: "Extracting design tokens" })
TaskCreate({ subject: "Build HTML prototype", description: "Create HTML with chosen design direction", activeForm: "Building prototype" })
TaskCreate({ subject: "Start dev server", description: "Serve HTML/app locally", activeForm: "Starting server" })
TaskCreate({ subject: "Capture Desktop Light into Figma", description: "First capture, creates new Figma file", activeForm: "Capturing Desktop Light" })
TaskCreate({ subject: "Capture Desktop Dark into Figma", description: "Toggle dark mode, capture", activeForm: "Capturing Desktop Dark" })
TaskCreate({ subject: "Capture Mobile Light into Figma", description: "Resize to 375px, capture", activeForm: "Capturing Mobile Light" })
TaskCreate({ subject: "Capture Mobile Dark into Figma", description: "Mobile + dark mode, capture", activeForm: "Capturing Mobile Dark" })
TaskCreate({ subject: "Identify Figma frames", description: "Map node IDs to variants", activeForm: "Identifying frames" })
TaskCreate({ subject: "Document in spec", description: "Add Figma URLs to story spec", activeForm: "Documenting mockups" })
TaskCreate({ subject: "Revert temporary changes", description: "git checkout, verify clean tree", activeForm: "Reverting changes" })
```

Mark each task `in_progress` before starting, `completed` when done.

---

## Phase 1: Choose Workflow

```
Does the user have an EXISTING Figma design to use as input?
├── YES → Workflow D: Figma as Input (specs, plans, or implementation)
│
└── NO → Creating new Figma designs:
    ├── Running app with feature visible? → Workflow A: Capture Running App
    ├── No existing project?              → Workflow B: New Project Design
    └── Project exists, feature doesn't?  → Workflow C: Enhancement Mockup
```

---

## Workflow A: Capture Running App

**When:** Existing app where the UI change can be applied temporarily.

1. **Apply temporary code changes** — minimum files needed. Track modifications:
   ```markdown
   ## Temporary Changes (REVERT AFTER CAPTURE)
   - [ ] `src/components/MyComponent.tsx`
   - [ ] `src/i18n/locales/en.ts`
   ```
2. **Start dev server** — use mock mode if available (`?mock=true`)
3. **Capture into Figma** — see [Capture Process](#capture-process)
4. **Capture variants** — see [Variants](#capturing-variants)
5. **Revert all changes** — `git checkout -- <files>`, verify with `git status`
6. **Document frames** — see [Post-Capture](#post-capture)

**Critical:** Verify mock data before capturing. AI-generated text may not match intended display.

---

## Workflow B: New Project Design

**When:** Greenfield project, no running UI.

1. **Use `frontend-design` skill** to build HTML prototype with chosen aesthetic
2. **Serve locally**: `npx http-server /path/to/mockup -p 8080`
3. **Capture** — see [Capture Process](#capture-process)
4. **Iterate** — share Figma URL, gather feedback via `AskUserQuestion`:
   ```
   AskUserQuestion({
     questions: [{
       question: "How does the design look? What should change?",
       header: "Feedback",
       options: [
         { label: "Looks great!", description: "Proceed to next screen" },
         { label: "Color tweaks", description: "Adjust the color palette" },
         { label: "Layout changes", description: "Restructure the layout" },
         { label: "Typography", description: "Change fonts or sizes" }
       ],
       multiSelect: true
     }]
   })
   ```
5. If changes needed: update HTML, re-serve, re-capture

---

## Workflow C: Enhancement Mockup

**When:** Existing project, but feature doesn't exist yet.

1. **Extract design tokens**:
   ```bash
   ./scripts/extract-design-tokens.sh ./frontend --format html > /tmp/tokens.html
   ```
2. **Build standalone HTML** using extracted tokens + chosen design
3. **Include surrounding UI context** — show the new element within existing page layout
4. **Serve and capture** — same as Workflow B
5. **Clean up** — delete standalone HTML

---

## Workflow D: Figma as Input

**When:** User shares a Figma URL and wants to use the design as input for writing specs, creating plans, or driving actual code implementation.

### Step D1: Extract Design Context

```
get_design_context(fileKey: "<key>", nodeId: "<id>")
```

This returns reference code, a screenshot, and contextual metadata. For multi-screen designs, call on each relevant node.

### Step D2: Capture Screenshots for Reference

```
get_screenshot(fileKey: "<key>", nodeId: "<id>")
```

Save screenshots alongside any specs or plans for visual reference.

### Step D3: Map Design to Project

Analyze the extracted design context against the target project:
- **Components**: Which existing project components map to design elements?
- **Tokens**: Do design colors/fonts/spacing match the project's CSS variables?
- **Gaps**: What new components, i18n keys, or types need creation?

### Step D4: Choose Output Target

Use `AskUserQuestion` to determine what the user needs:

```
AskUserQuestion({
  questions: [{
    question: "What should I do with this Figma design?",
    header: "Output",
    options: [
      { label: "Write a story spec", description: "Generate a story spec with acceptance criteria and sub-tasks" },
      { label: "Create a plan", description: "Enter plan mode with implementation steps" },
      { label: "Implement directly", description: "Write the code matching this design now" },
      { label: "All three", description: "Spec → Plan → Implement in sequence" }
    ],
    multiSelect: false
  }]
})
```

### Step D5: Execute

**Story spec:** Extract visual requirements from the design (layout, colors, typography, states, responsive breakpoints, dark mode). Write a spec following project conventions with Figma URLs as the design reference.

**Plan mode:** Enter plan mode. Map each design element to specific files, components, and i18n keys. Include the Figma screenshots as visual targets.

**Implementation:** Write code that matches the design. Use `get_design_context` output as a reference — adapt to the project's actual stack, components, and conventions. Verify with screenshots side-by-side.

**Verification:** After implementation, compare rendered output against the Figma screenshots using browser DevTools or Playwright screenshots.

---

## Capture Process

Uses Figma MCP `generate_figma_design` tool.

### First Capture (New File)

```
generate_figma_design(outputMode: "newFile", fileName: "Story X.Y - Description")
```

User opens app URL with Figma capture hash appended. Poll every 5s:

```
generate_figma_design(captureId: "<id>")
```

### Subsequent Captures (Same File)

```
generate_figma_design(outputMode: "existingFile", fileKey: "<key>")
```

Or let user use the **Figma capture toolbar** in the browser.

---

## Capturing Variants

Each capture ID is **single-use**. For multiple variants:

| Variant | Setup |
|---------|-------|
| Desktop Light | Default viewport (~1920px), light theme |
| Desktop Dark | Toggle dark mode |
| Mobile Light | Resize to ~375px or DevTools emulation |
| Mobile Dark | Mobile viewport + dark mode |
| Locale variant | Switch language |

**Recommended:** Capture first variant via MCP, then user toggles and uses Figma toolbar for rest.

---

## Post-Capture

### Identify Frames

```
get_metadata(fileKey: "<key>", nodeId: "0:1")
```

For large responses:
```bash
jq -r '.[0].text' /path/to/metadata.txt | \
  grep -oE '<frame id="[0-9]+:2" name="[^"]+" .+ width="[^"]+" height="[^"]+"'
```

Match by width (Desktop ~1920px, Mobile ~375-574px) and `get_screenshot` for light vs dark.

### Document in Spec

```markdown
### Design Mockups (Figma)

**Figma File:** `https://www.figma.com/design/<fileKey>`

| Variant | Node ID | URL |
|---------|---------|-----|
| Desktop Light | `X:2` | `https://www.figma.com/design/<fileKey>?node-id=X-2` |
| Desktop Dark | `Y:2` | `https://www.figma.com/design/<fileKey>?node-id=Y-2` |
| Mobile Light | `Z:2` | `https://www.figma.com/design/<fileKey>?node-id=Z-2` |
| Mobile Dark | `W:2` | `https://www.figma.com/design/<fileKey>?node-id=W-2` |
```

---

## Design Iteration Pattern

After initial capture, present results and iterate:

```
AskUserQuestion({
  questions: [{
    question: "I've captured 4 variants into Figma. Review them and let me know what's next.",
    header: "Next step",
    options: [
      { label: "Approved", description: "Designs look good, document in spec" },
      { label: "Iterate", description: "Need changes, will provide feedback" },
      { label: "Add screens", description: "Design additional screens/states" },
      { label: "Start over", description: "Different direction entirely" }
    ],
    multiSelect: false
  }]
})
```

---

## Quick Check

```bash
./scripts/extract-design-tokens.sh ./frontend              # HTML tokens
./scripts/extract-design-tokens.sh ./frontend --format json # JSON tokens
./scripts/extract-design-tokens.sh --help                   # Usage
```

## Figma MCP Gotchas

1. **Single-use capture IDs** — one page per ID
2. **Renders what's on screen** — verify mock data before capturing
3. **Wait for full load** — streaming states get captured too
4. **Large metadata** — use `jq` + `grep`, not direct inspection
5. **External URLs** — use Playwright MCP, not `open` command

## See Also

- `frontend-design` plugin — generates creative standalone HTML/CSS/JS (input to Workflows B/C)
- `spec-review` skill — reviews story specs (Workflow D can generate specs as input)
- `feature-dev` skill — guided implementation workflow (Workflow D can feed designs into implementation)
- Figma MCP tools — `generate_figma_design`, `get_screenshot`, `get_metadata`, `get_design_context`
