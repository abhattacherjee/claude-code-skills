# figma-ui-designer

Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP

## What It Does

Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code.

**Use when:**
- user asks for Figma mockups or UI designs, 
- user shares a Figma URL to use as input for a spec or plan, 
- starting a new project and needs Figma designs, 
- mocking up a feature enhancement, 
- user wants to translate a Figma design into implementation requirements.

## Key Features

- **Phase 0: Brainstorm & Plan**
- **Project Context**
- **Phase 1: Choose Workflow**
- **Workflow A: Capture Running App**
- **Workflow B: New Project Design**
- **Workflow C: Enhancement Mockup**
- **Workflow D: Figma as Input**
- **Capture Process**
- **Capturing Variants**
- **Post-Capture**
- **Design Iteration Pattern**

## Usage

```bash
./scripts/extract-design-tokens.sh ./frontend              # HTML tokens
./scripts/extract-design-tokens.sh ./frontend --format json # JSON tokens
./scripts/extract-design-tokens.sh --help                   # Usage
```

## Contents

- **1** skill(s), **0** command(s), **1** agent(s)

### Skills

- `figma-ui-designer` — Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code.

### Agents

- `figma-ux-expert` — Expert UX designer agent that researches real-world design references, analyzes UI patterns, and proposes grounded design directions with rationale. NOT user-invocable — spawned by figma-ui-designer skill during Phase 0 brainstorming.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install figma-ui-designer@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/figma-ui-designer
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/figma-ui-designer/skills/* ~/.claude/skills/

```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall figma-ui-designer@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/figma-ui-designer
rm -rf /tmp/ccs
```

## See Also

- `frontend-design` plugin — generates creative standalone HTML/CSS/JS (input to Workflows B/C)
- `spec-review` skill — reviews story specs (Workflow D can generate specs as input)
- `feature-dev` skill — guided implementation workflow (Workflow D can feed designs into implementation)
- Figma MCP tools — `generate_figma_design`, `get_screenshot`, `get_metadata`, `get_design_context`

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
