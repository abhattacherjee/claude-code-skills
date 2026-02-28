# Changelog

All notable changes to this project will be documented in this file.

## [3.1.0] - 2026-02-28

### Added

- **UX expert agent** — `figma-ux-expert` sub-agent that uses web search to research real-world design references (Dribbble, Behance, Awwwards, Mobbin) before proposing design directions
- **Research-backed brainstorming** — Phase 0 now spawns the UX expert agent to analyze competitor/reference designs and present 2-4 grounded options with rationale, accessibility notes, and ASCII mockups
- **Design token extraction** — `extract-design-tokens.sh` script parses Figma design context for colors, typography, spacing, and generates structured JSON output

## [3.0.0] - 2026-02-27

### Added

- **Interactive Figma UI design workflow** — 5-phase process: Brainstorm, Design, Implement, Review, Handoff
- **Task-driven progress tracking** — uses TaskCreate/TaskUpdate for multi-component designs
- **Design-to-code bridging** — generates implementation code from Figma designs using `get_design_context`
- **Phase 0 brainstorming** — gather context, present aesthetic options, create task list before designing

### Included

- **1 skill**: `figma-ui-designer`
- **1 agent**: `figma-ux-expert`
- **1 script**: `extract-design-tokens.sh`
