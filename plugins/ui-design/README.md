# ui-design

Interactive Figma UI design in one install: a skill that brainstorms with you, tracks progress and delivers Figma-native mockups through the Figma MCP, and the UX-expert agent it uses.

```shell
/plugin install ui-design@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/ui-design:figma`. The old name still matches as a trigger phrase.

| Skill | Was | What it does |
|---|---|---|
| `figma` | `figma-ui-designer` | Interactive Figma UI design with UX-expert brainstorming, progress tracking and design-to-code bridging. Four workflows: (A) capture a running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs, plans and code. |

### Use `figma` when

- you ask for Figma mockups or UI designs,
- you share a Figma URL to use as input for a spec or plan,
- you start a new project and need Figma designs,
- you want to mock up a feature enhancement,
- you want to turn a Figma design into implementation requirements.

The skill starts with a brainstorm (Phase 0), then you pick a workflow (Phase 1). It tracks the work as a task list and ends by documenting the Figma URLs in your spec.

## Agents

Started by the skill and not meant to be invoked by hand. Claude Code adds the plugin prefix, so the agent type is `ui-design:figma-ux-expert`.

| Agent | Was | Started by | What it does |
|---|---|---|---|
| `figma-ux-expert` | `figma-ux-expert` (in `figma-ui-designer`) | `figma` | Researches real-world design references (Dribbble, Behance, Awwwards, Mobbin), analyzes UI patterns and returns 2-4 design directions with rationale, reference URLs, ASCII mockups, pros and cons and accessibility notes. Model: `sonnet`. |

```shell
/ui-design:figma mock up a settings page for my app
/ui-design:figma turn this Figma frame into a spec
```

## Scripts

The skill runs its script through `${CLAUDE_SKILL_DIR}`, so it works from your project directory. You normally do not run it yourself.

| Skill | Script | Purpose |
|---|---|---|
| `figma` | `extract-design-tokens.sh [PROJECT_DIR] [--format html\|json\|css]` | Reads, for mockups that match the real look: the CSS custom properties of top-level `:root` rules and the dark-mode ones (`.dark`, `:root.dark`, `html.dark`, `[data-theme=dark]` and similar, else `@media (prefers-color-scheme: dark)`); `@layer` counts as top-level from the first of `src/index.css`, `src/styles/globals.css`, `src/app/globals.css`, `src/main.css`, `src/styles.css` that has `:root` variables; the Google Fonts link from `index.html`, `public/index.html` or `src/index.html`; the `fontFamily` names from `tailwind.config.js`/`.ts`/`.mjs`. It warns on stderr when it finds no `:root` variables. |

## See also

- `frontend-design` plugin: generates standalone HTML/CSS/JS (input to workflows B and C)
- `spec:review` skill: reviews story specs (workflow D can generate specs as input)
- `feature-dev` skill: guided implementation (workflow D can feed designs into implementation)
- `context:shield`: use it when you analyze 10+ Figma frames
- Figma MCP tools: `generate_figma_design`, `get_screenshot`, `get_metadata`, `get_design_context`

## Install and uninstall

Install the plugin; do not copy the skill by hand. A loose copy breaks the `${CLAUDE_SKILL_DIR}` paths and shadows the plugin.

```shell
/plugin marketplace add abhattacherjee/claude-code-skills
/plugin install ui-design@claude-code-skills
/plugin uninstall ui-design@claude-code-skills
```

If you used the old name, install `ui-design` first, then remove the old `figma-ui-designer` skill and plugin (and `~/.claude/agents/figma-ux-expert.md`) so they cannot win a plain-language request.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
