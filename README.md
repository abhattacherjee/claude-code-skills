
# Claude Code Skills

A curated collection of reusable [Agent Skills](https://agentskills.io) for
Claude Code. Every skill ships inside a plugin, and you install it through Claude
Code's plugin system (or the install script below, which copies a plugin into
`~/.claude/`).

## Plugins

Plugins bundle skills, commands, agents, and hooks into a single installable package.

git-flow is not in this marketplace. It installs from its own: `/plugin marketplace add abhattacherjee/git-flow`, then `/plugin install git-flow@git-flow-repo`.

obsidian-brain is not in this marketplace. It installs from its own: `/plugin marketplace add abhattacherjee/obsidian-brain`, then `/plugin install obsidian-brain@obsidian-brain-repo`.

<!-- catalogue:start -->
| Plugin | Version | Skills | Commands | Description |
|--------|---------|--------|----------|-------------|
| [context](./plugins/context/) | 1.0.3 | 2 | 0 | Two skills for working with large content and past sessions, plus the agents they use. context:shield keeps the context window from overflowing by delegating token-heavy reads (URLs, Figma frames, wiki pages, code directories) to isolated sub-agents that return short summaries, and hands multi-batch work to ralph-loop. context:search finds past Claude Code conversations by topic, date, branch or project, shows them verbatim, and can summarize them. |
| [demo-video](./plugins/demo-video/) | 1.0.1 | 2 | 0 | Record and produce demo videos. demo-video:record turns a macOS screen recording into a narrated demo with AI-written zoom scripts and voiceover. demo-video:produce builds a narrated product video in code with Remotion, from real app screenshots, TTS voiceover and background music. Ships the nine agents they use. |
| [dev-flow](./plugins/dev-flow/) | 1.0.2 | 2 | 0 | Two skills for the daily git loop. dev-flow:worktree creates isolated git worktrees so parallel Claude Code sessions each get their own directory and branch. dev-flow:changelog keeps CHANGELOG.md up to date by turning git commit history into categorized Keep-a-Changelog entries. |
| [github-board](./plugins/github-board/) | 1.2.1 | 7 | 0 | GitHub workflow skills in one install: create-board, triage-issues, plan-milestones, plan-week, move-card, promote-shipped and prune-branches, plus the four agents create-board dispatches. Per-user settings live in ~/.config/github-board/config.json. |
| [review](./plugins/review/) | 1.0.1 | 2 | 0 | Two review skills in one plugin. review:deep is a two-phase convergence harness: iterative multi-reviewer fix and re-review until a round finds nothing actionable, then a multi-round cross-examination with an opposing model (Codex, else Gemini). review:adversarial is the single-pass version: Claude and the opposing model find issues independently, cross-examine each other, and only findings the other side confirms are reported. Both save an audit trail on the PR (or a local file with no PR) and degrade loudly to Claude-only when no adversary is available. |
| [skill-kit](./plugins/skill-kit/) | 1.2.0 | 3 | 0 | Three skills for building and sharing Claude Code skills in one plugin. skill-kit:author writes and optimizes skills to Anthropic's best practices, with parallel sub-agents and script-first determinism. skill-kit:publish packages skills as plugins and syncs them to a GitHub monorepo. skill-kit:extract turns what a work session just taught you into a new or updated skill. |
| [spec](./plugins/spec/) | 1.0.6 | 3 | 0 | Three skills for story specs in one plugin. spec:create writes a template-compliant story spec from a plan, requirements file, prompt or GitHub issue, with TDD implementation steps, success metrics, a Figma mockup gate for UI stories and vertical splitting for large stories. spec:review checks a spec against the real codebase and architecture and adds verified sub-tasks, an API test plan and design simplification notes. spec:implement builds a reviewed spec end-to-end: feature branch, sub-tasks, acceptance checks and a PR. |
| [statusline](./plugins/statusline/) | 1.0.1 | 3 | 0 | Claude Code statusline in one install: install the 3-tier adaptive statusline, create your own from 20 composable items, or check context usage with context-bar. Never replaces a statusline script it did not write unless you pass --force, and backs up every file it replaces. |
| [ui-design](./plugins/ui-design/) | 1.0.1 | 1 | 0 | Interactive Figma UI design, with the UX-expert agent it uses. ui-design:figma brainstorms with you, tracks progress, builds Figma-native mockups through the Figma MCP, and extracts existing Figma designs as input for specs, plans and code. It starts the figma-ux-expert agent (ui-design:figma-ux-expert) to research real-world references before it proposes design directions. |
<!-- catalogue:end -->

> **Note:** The `git-flow` plugin moved to its own repository — install via `/plugin marketplace add abhattacherjee/git-flow`.


### Install via Claude Code (Recommended)

Add this repo as a plugin marketplace, then install individual plugins:

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install a plugin
/plugin install PLUGIN_NAME@claude-code-skills
```

To browse all available plugins interactively, run `/plugin` and go to the **Discover** tab.

### Install via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
```

### Uninstall a Plugin

```bash
# Via Claude Code
/plugin uninstall PLUGIN_NAME@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
```

## Compatibility

These skills follow the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter — and ship as [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) plugins. Both install paths above target Claude Code. Other tools that read `SKILL.md` (Cursor, Codex CLI, Gemini CLI) have no install path here since the top-level skill directories were removed (#167); the plugins also use Claude Code features such as `${CLAUDE_SKILL_DIR}` and plugin agent types.

## License

[MIT](LICENSE)

---
*Last synced: 2026-06-06*
