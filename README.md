
# Claude Code Skills

A curated collection of 7 reusable [Agent Skills](https://agentskills.io) for
Claude Code, Cursor, Codex CLI, and Gemini CLI.

## Skills

| Skill | Version | Description | Individual Repo |
|-------|---------|-------------|-----------------|
| [changelog-keeper](./changelog-keeper/) | 1.1.1 | Deprecated: use `dev-flow:changelog` from the dev-flow plugin. Keeps CHANGELOG.md up to date by generating categorized entries from git commit history. | [repo](https://github.com/abhattacherjee/changelog-keeper) |
| [claudeception](./claudeception/) | 3.2.0 | Deprecated: use `skill-kit:extract` from the skill-kit plugin. Extracts reusable knowledge from work sessions and codifies it into Claude Code skills. | [repo](https://github.com/abhattacherjee/claudeception) |
| [context-shield](./context-shield/) | 1.3.2 | Deprecated: use `context:shield` from the context plugin. Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count. | — |
| [conversation-search](./conversation-search/) | 1.1.0 | Deprecated: use `context:search` from the context plugin. Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries. | [repo](https://github.com/abhattacherjee/conversation-search) |
| [figma-ui-designer](./figma-ui-designer/) | 3.2.2 | Deprecated: use `ui-design:figma` from the ui-design plugin. Interactive Figma UI design skill with UX-expert brainstorming, progress tracking, and design-to-code bridging. Spawns a specialized UX designer agent that researches real-world references before proposing design directions. Four workflows: (A) capture running app, (B) new project design, (C) enhancement mockup, (D) extract existing Figma designs as input for specs/plans/code. | — |
| [skill-authoring](./skill-authoring/) | 2.6.1 | Deprecated: use `skill-kit:author` from the skill-kit plugin. Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism. | — |
| [worktree](./worktree/) | 1.0.1 | Deprecated: use `dev-flow:worktree` from the dev-flow plugin. Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch. | [repo](https://github.com/abhattacherjee/worktree) |


## Plugins

Plugins bundle skills, commands, agents, and hooks into a single installable package.

git-flow is not in this marketplace. It installs from its own: `/plugin marketplace add abhattacherjee/git-flow`, then `/plugin install git-flow@git-flow-repo`.

obsidian-brain is not in this marketplace. It installs from its own: `/plugin marketplace add abhattacherjee/obsidian-brain`, then `/plugin install obsidian-brain@obsidian-brain-repo`.

| Plugin | Version | Skills | Commands | Description |
|--------|---------|--------|----------|-------------|
| [adversarial-review](./plugins/adversarial-review/) | 0.2.0 | 1 | 0 | Deprecated: use the review plugin (review:deep / review:adversarial). Adversarial PR review — Claude and an opposing model (Codex, else Gemini) discover findings independently then cross-examine each other symmetrically, surfacing only issues both models confirm. Auto-detects PR vs local (working-tree) mode; degrades loudly to Claude-only if no adversary is available. |
| [context](./plugins/context/) | 1.0.1 | 2 | 0 | Two skills for working with large content and past sessions, plus the agents they use. context:shield keeps the context window from overflowing by delegating token-heavy reads (URLs, Figma frames, wiki pages, code directories) to isolated sub-agents that return short summaries, and hands multi-batch work to ralph-loop. context:search finds past Claude Code conversations by topic, date, branch or project, shows them verbatim, and can summarize them. |
| [context-bar](./plugins/context-bar/) | 1.0.1 | 1 | 0 | Deprecated: use the statusline plugin (statusline:install / statusline:create / statusline:context-bar). Color-coded context window usage bar for Claude Code statusline and /context-bar command |
| [context-shield](./plugins/context-shield/) | 1.3.2 | 1 | 0 | Deprecated: use the context plugin (context:shield). Prevents context window overflow by delegating token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed. Covers: documentation sites, code audits, dependency research, large PR reviews, competitive analysis, security advisories. |
| [custom-statusline](./plugins/custom-statusline/) | 1.3.1 | 1 | 0 | Deprecated: use the statusline plugin (statusline:install / statusline:create / statusline:context-bar). 4-tier adaptive statusline with icons for folder, git branch, and context usage |
| [deep-review](./plugins/deep-review/) | 1.4.0 | 1 | 0 | Deprecated: use the review plugin (review:deep / review:adversarial). Two-phase convergence harness for high-assurance review of a changeset (PR or working-tree diff). Phase 1 loops iterative multi-reviewer fix->re-review until a round finds zero actionable issues; Phase 2 runs a multi-round adversarial cross-examination with Codex, else Gemini, as the opposing model (it finds -> Claude judges -> it counters -> it re-checks fixes), fixing every confirmed finding. Soft-depends on pr-review-toolkit and adversarial-review plugins with documented fallbacks. |
| [demo-video](./plugins/demo-video/) | 1.0.0 | 2 | 0 | Record and produce demo videos. demo-video:record turns a macOS screen recording into a narrated demo with AI-written zoom scripts and voiceover. demo-video:produce builds a narrated product video in code with Remotion, from real app screenshots, TTS voiceover and background music. Ships the nine agents they use. |
| [dev-flow](./plugins/dev-flow/) | 1.0.0 | 2 | 0 | Two skills for the daily git loop. dev-flow:worktree creates isolated git worktrees so parallel Claude Code sessions each get their own directory and branch. dev-flow:changelog keeps CHANGELOG.md up to date by turning git commit history into categorized Keep-a-Changelog entries. |
| [figma-ui-designer](./plugins/figma-ui-designer/) | 3.2.2 | 1 | 0 | Deprecated: use the ui-design plugin (ui-design:figma). Interactive Figma UI design skill with brainstorming, progress tracking, and design-to-code bridging via Figma MCP |
| [github-board](./plugins/github-board/) | 1.0.1 | 7 | 0 | GitHub workflow skills in one install: create-board, triage-issues, plan-milestones, plan-week, move-card, promote-shipped and prune-branches, plus the four agents create-board dispatches. Per-user settings live in ~/.config/github-board/config.json. |
| [product-video-creation](./plugins/product-video-creation/) | 2.0.0 | 1 | 0 | Deprecated: use the demo-video plugin (demo-video:produce). Creates polished, narrated product demo videos using Remotion with AI-crafted storytelling, real app screenshots, animated phone mockups, brand-aligned styling, TTS voiceover, and background music. |
| [review](./plugins/review/) | 1.0.0 | 2 | 0 | Two review skills in one plugin. review:deep is a two-phase convergence harness: iterative multi-reviewer fix and re-review until a round finds nothing actionable, then a multi-round cross-examination with an opposing model (Codex, else Gemini). review:adversarial is the single-pass version: Claude and the opposing model find issues independently, cross-examine each other, and only findings the other side confirms are reported. Both save an audit trail on the PR (or a local file with no PR) and degrade loudly to Claude-only when no adversary is available. |
| [skill-authoring](./plugins/skill-authoring/) | 2.3.1 | 1 | 0 | Deprecated: use the skill-kit plugin (skill-kit:author). Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism |
| [skill-kit](./plugins/skill-kit/) | 1.0.2 | 3 | 0 | Three skills for building and sharing Claude Code skills in one plugin. skill-kit:author writes and optimizes skills to Anthropic's best practices, with parallel sub-agents and script-first determinism. skill-kit:publish packages skills as plugins and syncs them to a GitHub monorepo. skill-kit:extract turns what a work session just taught you into a new or updated skill. |
| [skill-publishing](./plugins/skill-publishing/) | 4.5.1 | 1 | 0 | Deprecated: use the skill-kit plugin (skill-kit:publish). Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos |
| [smart-screen-recorder](./plugins/smart-screen-recorder/) | 4.3.0 | 1 | 0 | Deprecated: use the demo-video plugin (demo-video:record). AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor, analyzes with AI vision, generates zoom scripts and voiceover narration, and produces polished demo videos. |
| [spec](./plugins/spec/) | 1.0.3 | 3 | 0 | Three skills for story specs in one plugin. spec:create writes a template-compliant story spec from a plan, requirements file, prompt or GitHub issue, with TDD implementation steps, success metrics, a Figma mockup gate for UI stories and vertical splitting for large stories. spec:review checks a spec against the real codebase and architecture and adds verified sub-tasks, an API test plan and design simplification notes. spec:implement builds a reviewed spec end-to-end: feature branch, sub-tasks, acceptance checks and a PR. |
| [spec-creator](./plugins/spec-creator/) | 2.4.2 | 1 | 0 | Deprecated: use the spec plugin (spec:create / spec:review / spec:implement). Creates detailed story specifications with TDD implementation steps, success metrics, Figma UX design gates, and vertical splitting from various inputs (plans, requirements, GitHub issues). |
| [spec-implement](./plugins/spec-implement/) | 1.0.0 | 1 | 0 | Deprecated: use the spec plugin (spec:create / spec:review / spec:implement). Implements a previously created and reviewed story spec end-to-end: feature branch, sub-task implementation with progress tracking, acceptance-criteria validation, and PR creation. |
| [spec-review](./plugins/spec-review/) | 2.2.2 | 1 | 0 | Deprecated: use the spec plugin (spec:create / spec:review / spec:implement). Reviews and enriches story specifications with codebase-verified sub-tasks, architecture alignment, design simplification, and API test plans. |
| [statusline](./plugins/statusline/) | 1.0.0 | 3 | 0 | Claude Code statusline in one install: install the 3-tier adaptive statusline, create your own from 20 composable items, or check context usage with context-bar. Never replaces a statusline script it did not write unless you pass --force, and backs up every file it replaces. |
| [statusline-creator](./plugins/statusline-creator/) | 1.0.0 | 1 | 0 | Deprecated: use the statusline plugin (statusline:install / statusline:create / statusline:context-bar). Creates and customizes Claude Code statusline scripts from composable items |
| [ui-design](./plugins/ui-design/) | 1.0.0 | 1 | 0 | Interactive Figma UI design, with the UX-expert agent it uses. ui-design:figma brainstorms with you, tracks progress, builds Figma-native mockups through the Figma MCP, and extracts existing Figma designs as input for specs, plans and code. It starts the figma-ux-expert agent (ui-design:figma-ux-expert) to research real-world references before it proposes design directions. |

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

## Installation

### Install all skills

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
# changelog-keeper and worktree are deprecated: install the dev-flow plugin instead (dev-flow:changelog, dev-flow:worktree).
# claudeception is deprecated: install the skill-kit plugin instead (skill-kit:extract).
# context-shield and conversation-search are deprecated: install the context plugin instead (context:shield, context:search).
# figma-ui-designer is deprecated: install the ui-design plugin instead (ui-design:figma).
# skill-authoring is deprecated: install the skill-kit plugin instead (skill-kit:author).
rm -rf /tmp/claude-code-skills
```

### Install a single skill from the monorepo

```bash
# Clone the monorepo
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills

# Copy the skill you want
cp -r /tmp/claude-code-skills/SKILL_NAME ~/.claude/skills/SKILL_NAME

# Clean up
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (single skill, minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set SKILL_NAME
cp -r SKILL_NAME ~/.claude/skills/SKILL_NAME
rm -rf /tmp/ccs
```

### Install from individual repo

Each skill is also available as a standalone repository:

```bash
git clone https://github.com/abhattacherjee/SKILL_NAME.git ~/.claude/skills/SKILL_NAME
```

See the table above for links to individual repos.

## Updating

```bash
cd /path/to/your/clone && git pull
# Then re-copy updated skills to ~/.claude/skills/
```

## Compatibility

These skills follow the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)

---
*Last synced: 2026-06-06*
