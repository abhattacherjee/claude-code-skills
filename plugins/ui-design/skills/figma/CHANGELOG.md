# Changelog

All notable changes to the **figma** skill (was `figma-ui-designer`) are documented here.

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `ui-design` plugin as `ui-design:figma` (#164). Same workflows and script as `figma-ui-designer` 3.2.2. The old name and `/figma-ui-designer` still match as trigger phrases.
- The UX-expert agent is started as `ui-design:figma-ux-expert`. The old text started a general-purpose agent and told it to read `~/.claude/agents/figma-ux-expert.md`, a file that is not part of any install (#164).
- Every script command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh"`. The old text used `./scripts/extract-design-tokens.sh`, which only worked from the skill directory. The project path argument (`./frontend`) is yours and stays relative.

## History before 1.0.0 (as `figma-ui-designer`)

### figma-ui-designer 3.2.2 - 2026-10-04

- The See Also line says `context:shield` (was `context-shield`), after `context-shield` moved into the `context` plugin (#163).

### figma-ui-designer 3.2.1 - 2026-10-04

- The See Also line says `spec:review` (was `spec-review`), after the three spec skills merged into the `spec` plugin (#160).
- `plugin.json` and the marketplace entry say 3.2.1. They were still at 3.1.0 while the skill was at 3.2.0.

### figma-ui-designer 3.2.0 - 2026-03-17

- **Team mode note** — when Agent Teams are enabled, multiple UX expert teammates can explore different design directions simultaneously during Phase 0 brainstorming.

### figma-ui-designer 3.1.0 - 2026-02-28

- **UX expert agent** — `figma-ux-expert` sub-agent that uses web search to research real-world design references (Dribbble, Behance, Awwwards, Mobbin) before proposing design directions.
- **Research-backed brainstorming** — Phase 0 now spawns the UX expert agent to analyze competitor/reference designs and present 2-4 grounded options with rationale, accessibility notes, and ASCII mockups.
- **Design token extraction** — `extract-design-tokens.sh` script parses Figma design context for colors, typography, spacing, and generates structured JSON output.

### figma-ui-designer 3.0.0 - 2026-02-27

- **Interactive Figma UI design workflow** — 5-phase process: Brainstorm, Design, Implement, Review, Handoff.
- **Task-driven progress tracking** — uses TaskCreate/TaskUpdate for multi-component designs.
- **Design-to-code bridging** — generates implementation code from Figma designs using `get_design_context`.
- **Phase 0 brainstorming** — gather context, present aesthetic options, create task list before designing.
- Included: 1 skill (`figma-ui-designer`), 1 agent (`figma-ux-expert`), 1 script (`extract-design-tokens.sh`).
