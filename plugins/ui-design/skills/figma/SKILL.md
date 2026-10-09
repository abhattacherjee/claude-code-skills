---
name: figma
description: "Was the figma-ui-designer skill (/figma-ui-designer still works as a phrase). Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code. Use when: (1) user asks for Figma mockups or UI designs, (2) user shares a Figma URL to use as input for a spec or plan, (3) starting a new project and needs Figma designs, (4) mocking up a feature enhancement, (5) user wants to translate a Figma design into implementation requirements."
metadata:
  version: 1.0.1
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
- Target audience and domain (vacation, SaaS, e-commerce, etc.)

### Step 0b: Research & Brainstorm via UX Expert Agent

Launch the `figma-ux-expert` agent to research real-world design references and propose grounded design directions. This replaces generic hardcoded options with informed, research-backed alternatives.

```
Agent({
  subagent_type: "ui-design:figma-ux-expert",
  model: "sonnet",
  description: "UX research and design directions",
  prompt: `## Project Context
- **What to design:** [screens/components from Step 0a]
- **Domain:** [e.g., vacation booking, travel recommendations]
- **Design goals:** [what the design should communicate]
- **Constraints:** [framework, dark mode, i18n, responsive, etc.]
- **Existing design tokens:** [if extracted, include key colors/fonts]

Research real-world references, then propose 2-4 design directions with rationale, reference URLs, ASCII mockups, and pros/cons.`
})
```

The agent will return a structured report with:
- **Research summary** — 3-5 reference URLs with analysis
- **2-4 design directions** — each with name, rationale, color palette, typography, ASCII mockup, pros/cons, accessibility notes
- **Recommendation** — which direction is strongest and why

### Step 0c: Present Design Options

Use the agent's structured output to build `AskUserQuestion` options. Each option should include the agent's ASCII mockup, reference URLs, and rationale — NOT generic placeholders.

**For component/feature designs** (Workflow A or C): one single-select question, "Which design direction? (References researched by UX expert)", with one option per agent direction (up to 4). Each option's label is the direction's name, its description the agent's rationale, and its markdown preview the agent's ASCII mockup followed by `Inspired by:` (reference URLs), `Pros:`, `Cons:` and `A11y:` (contrast and keyboard notes).

**For new project designs** (Workflow B), ask a second single-select question in the same call: "Which variants do you need?" with `All 4` (Desktop + Mobile, Light + Dark), `Desktop only` (Light + Dark), `Light only` (Desktop + Mobile) and `Desktop Light only`.

**Team mode:** When Agent Teams are enabled, multiple UX expert teammates can explore different design directions simultaneously (e.g., one researching minimalist approaches while another explores bold/editorial styles), then present all findings together for the user to pick from. This is especially valuable for new project designs (Workflow B) where the design space is wide.

**Fallback:** If the agent fails or returns incomplete results, fall back to presenting 2-3 directions based on your own knowledge, but note that references were not available.

### Step 0d: Create Task List

After the user picks a direction, create one `TaskCreate` task per step, in this order (drop the capture tasks for variants the user did not pick):

1. Extract design tokens (`extract-design-tokens.sh`)
2. Build HTML prototype with the chosen direction
3. Start dev server (serve the HTML or app locally)
4. Capture Desktop Light into Figma (first capture, creates the Figma file)
5. Capture Desktop Dark into Figma (toggle dark mode)
6. Capture Mobile Light into Figma (resize to 375px)
7. Capture Mobile Dark into Figma
8. Identify Figma frames (map node IDs to variants)
9. Document in spec (add the Figma URLs to the story spec)
10. Revert temporary changes (`git checkout`, verify a clean tree)

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
   "${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh" ./frontend --format html > /tmp/tokens.html
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

After the first capture, ask one single-select question, "I've captured the variants into Figma. Review them and let me know what's next.", with the options `Approved` (document in spec), `Iterate` (the user gives feedback), `Add screens` (more screens or states) and `Start over` (a different direction).

---

## Quick Check

```bash
"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh" ./frontend              # HTML tokens
"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh" ./frontend --format json # JSON tokens
"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh" --help                   # Usage
```

The script reads the CSS custom properties of top-level rules whose selector is exactly `:root`, and the dark-mode ones (rules on `.dark`, `:root.dark`, `.dark:root`, `html.dark`, `[data-theme=dark]` or `:root[data-theme=dark]`, else a `:root` inside `@media (prefers-color-scheme: dark)`). Rules inside `@layer` count as top-level; rules inside any other `@media` or `@supports` are skipped. It reads them from the first of `src/index.css`, `src/styles/globals.css`, `src/app/globals.css`, `src/main.css` and `src/styles.css` that has `:root` variables. It reads the Google Fonts link from `index.html`, `public/index.html` or `src/index.html`, and the `fontFamily` names from `tailwind.config.js`, `.ts` or `.mjs`. Paths are relative to the project directory you pass. It does not read spacing or Tailwind colors. When it finds no `:root` variables it prints a warning on stderr and still exits 0, so check stderr before trusting the tokens. In `--format json` a value it did not find is `null`.

## Figma MCP Gotchas

1. **Single-use capture IDs** — one page per ID
2. **Renders what's on screen** — verify mock data before capturing
3. **Wait for full load** — streaming states get captured too
4. **Large metadata** — use `jq` + `grep`, not direct inspection
5. **External URLs** — use Playwright MCP, not `open` command

## See Also

- `frontend-design` plugin — generates creative standalone HTML/CSS/JS (input to Workflows B/C)
- `spec:review` skill — reviews story specs (Workflow D can generate specs as input)
- `feature-dev` skill — guided implementation workflow (Workflow D can feed designs into implementation)
- `context:shield` — use when analyzing 10+ Figma frames or researching 5+ competitor designs in Phase 0; delegates reads to isolated agents to avoid context overflow
- Figma MCP tools — `generate_figma_design`, `get_screenshot`, `get_metadata`, `get_design_context`
