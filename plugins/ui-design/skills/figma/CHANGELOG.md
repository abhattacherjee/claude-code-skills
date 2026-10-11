# Changelog

All notable changes to the **figma** skill (was `figma-ui-designer`) are documented here.

## [1.0.1] - 2026-10-09

### Changed

- Phase 0 and the iteration step describe the `AskUserQuestion` options and the task list in prose instead of JSON call templates; every option, label and task is kept (#210).

## [1.0.0] - 2026-10-04

### Changed

- Moved into the `ui-design` plugin as `ui-design:figma` (#164). Same workflows as `figma-ui-designer` 3.2.2; the script fixes are under Fixed. The old name and `/figma-ui-designer` still match as trigger phrases.
- The UX-expert agent is started as `ui-design:figma-ux-expert`. The old text started a general-purpose agent and told it to read `~/.claude/agents/figma-ux-expert.md`, a file that is not part of any install (#164).
- Every script command is written to work from your project directory (checked statically by `check-skill-commands.py`): `"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh"`. The old text used `./scripts/extract-design-tokens.sh`, which only worked from the skill directory. The project path argument (`./frontend`) is yours and stays relative.

### Fixed

- `extract-design-tokens.sh` stopped with `unbound variable` (exit 1) for a project with no CSS file in its usual places, in every format.
- `--format json` built the JSON by hand: a quote or backslash in the project path broke it, and a missing file showed as the text `null`. `jq` builds it now, and a missing file is a real `null`. The old fallback printed `""` when `jq` was missing; the script now exits 1 and says it needs `jq`.
- `--format` with no value stopped with `unbound variable`. It exits 2 with a message.
- It used the first CSS file that existed, even one with no `:root` variables, so a project with tokens in `src/app/globals.css` and an `src/index.css` without them got none. It now uses the first file that has `:root` variables, and prints a warning on stderr when none has (exit stays 0).
- A `:root` inside `@media (prefers-color-scheme: dark)` was also read as light, so dark values leaked into the light set. Braces are now tracked: light is a top-level rule whose selector is exactly `:root`, dark is a top-level `.dark`, `:root.dark`, `.dark:root`, `html.dark`, `[data-theme=dark]` or `:root[data-theme=dark]` rule, else the `:root` inside that `@media` rule. A dark selector such as `:root.dark` is never read as light.
- `@layer base { ... }` (named or not) hid every token inside it. `@layer` is now see-through, so its `:root` and `.dark` rules count as top-level. Rules inside any other `@media` or `@supports` stay out of the light set.
- A brace inside a comment (`/* { */`, also over several lines) or a quoted value (`--a: "{"`) changed the nesting, so later tokens were lost. Comments and quoted strings are now skipped when braces are counted, and a `--` line inside a comment is not read.
- A CSS file with CRLF line endings kept the `\r` in the selector and in each value: `.dark\r` was not a dark selector, so every dark token was dropped, and the light value came out as `--bg: white;\r`. Every `\r` is now removed before the file is read.
- In `--format json`, `cssVariables`, `darkModeVariables` and `tailwindFonts` were `""` when not found, though the comment said `null`. They are `null` now.
- The header, help text and README said it extracts spacing and Tailwind colors. It never output either. The dead Tailwind color code is gone, and the docs name the files it reads.

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
