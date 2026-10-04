# Changelog

All notable changes to the **ui-design** plugin are documented here.

## [1.0.0] - 2026-10-04

### Added

- First release (#164). It takes over the `figma-ui-designer` plugin (3.2.2) and the bare `figma-ui-designer` skill. One skill under a short name: `figma` (was `figma-ui-designer`). Invoke it as `/ui-design:figma`. The old name still matches as a trigger phrase.
- The `figma-ux-expert` agent ships with the plugin. The skill starts it as `ui-design:figma-ux-expert`.
- Smoke tests for the token script and the agent wiring, in `tests/run-tests.sh`, and a CI job (`ui-design-tests`, bash 5 and bash 3.2) that runs them. They run the script from a temp project directory with `HOME` on a temp dir and a clean environment, in a plugin copy under a path with a space. For the token script they cover all three formats, a project with no CSS file, odd characters in the path, bad input, the order of the CSS and HTML files it tries, dark mode from `@media (prefers-color-scheme: dark)`, which selectors are light or dark (`:root.dark`, `[data-theme="dark"]`, `html.dark`), `@layer`, `@media (min-width)` and `@supports` wrappers, braces in comments and quoted values, a CRLF file, `null` for values not found, leading whitespace, the no-variables warning and `--format json` with no `jq`. A python check that crashes is a FAIL line, not an abort. `UIDESIGN_SKILLS` and `UIDESIGN_AGENTS` point the suite at another copy. They also check that `figma` starts `ui-design:figma-ux-expert` and never names `~/.claude/agents`, that the agent keeps the bare name, and that `${CLAUDE_SKILL_DIR}` appears only inside fenced code blocks.

### Changed

- The skill starts the agent as `ui-design:figma-ux-expert`. The old text started a general-purpose agent and told it to read `~/.claude/agents/figma-ux-expert.md`. That file is not part of any install.
- The script command is written to work from your project directory (checked statically by `check-skill-commands.py`, which now covers this plugin in CI): `"${CLAUDE_SKILL_DIR}/scripts/extract-design-tokens.sh"`. The old text used `./scripts/extract-design-tokens.sh`, which only worked from the skill directory.

### Fixed

- `figma`: `extract-design-tokens.sh` stopped with `unbound variable` (exit 1) for a project with no CSS file in its usual places, in every format.
- `--format json` built the JSON by hand: a quote or backslash in the project path broke it, and a missing file showed as the text `null`. `jq` builds it now, and a missing file is a real `null`. The old fallback printed `""` when `jq` was missing; the script now exits 1 and says it needs `jq`.
- `--format` with no value stopped with `unbound variable`. It exits 2 with a message.
- `extract-design-tokens.sh` used the first CSS file that existed, even one with no `:root` variables, so a project with tokens in `src/app/globals.css` and an `src/index.css` without them got none. It now uses the first file that has `:root` variables, and prints a warning on stderr when none has (exit stays 0).
- A `:root` inside `@media (prefers-color-scheme: dark)` was also read as light, so dark values leaked into the light set. Braces are now tracked: light is a top-level rule whose selector is exactly `:root`, dark is a top-level `.dark`, `:root.dark`, `.dark:root`, `html.dark`, `[data-theme=dark]` or `:root[data-theme=dark]` rule, else the `:root` inside that `@media` rule. A dark selector such as `:root.dark` is never read as light.
- `@layer base { ... }` (named or not) hid every token inside it. `@layer` is now see-through, so its `:root` and `.dark` rules count as top-level. Rules inside any other `@media` or `@supports` stay out of the light set.
- A brace inside a comment (`/* { */`, also over several lines) or a quoted value (`--a: "{"`) changed the nesting, so later tokens were lost. Comments and quoted strings are now skipped when braces are counted, and a `--` line inside a comment is not read.
- A CSS file with CRLF line endings kept the `\r` in the selector and in each value: `.dark\r` was not a dark selector, so every dark token was dropped, and the light value came out as `--bg: white;\r`. Every `\r` is now removed before the file is read.
- In `--format json`, `cssVariables`, `darkModeVariables` and `tailwindFonts` were `""` when not found, though the comment said `null`. They are `null` now.
- The header, help text and README said it extracts spacing and Tailwind colors. It never output either. The dead Tailwind color code is gone, and the docs name the files it reads.

### Deprecated

- The `figma-ui-designer` plugin and the bare `figma-ui-designer` skill. They stay in the repo until #167. Install `ui-design`, then remove the old ones, so the old name cannot win a plain-language request.

### History

Per-skill history before the move is in `skills/figma/CHANGELOG.md`.
