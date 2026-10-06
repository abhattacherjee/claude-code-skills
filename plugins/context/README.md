# context

<!-- plugin-meta:start -->
**Version:** 1.0.3 · **2** skills · **2** agents · **0** commands
<!-- plugin-meta:end -->

Two skills for working with large content and past sessions, in one install. `shield` keeps big reads out of your context window, and `search` finds and summarizes your old Claude Code conversations.

```shell
/plugin install context@claude-code-skills
```

(Add this repo as a plugin marketplace first; see the repo README.)

## Skills

Invoke as `/context:<skill>`. The old names still match as trigger phrases.

| Skill | Was | What it does |
|---|---|---|
| `shield` | `context-shield` | Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count. |
| `search` | `conversation-search` | Searches Claude Code conversation history in `~/.claude/projects/` by topic, date, branch or project. Gives verbatim conversation content and AI-generated summaries. |

## Agents

Both are started by the skills and are not meant to be invoked by hand. Claude Code adds the plugin prefix, so the agent types are `context:content-distiller` and `context:conversation-summarizer`.

| Agent | Was | Started by | What it does |
|---|---|---|---|
| `content-distiller` | `content-distiller` (in `context-shield`) | `shield` | Reads one source (URL, Figma node, file, wiki page, codebase section) in an isolated context and returns a distilled summary of about 500 tokens. Model: `sonnet`. |
| `conversation-summarizer` | `conversation-summarizer` (in `~/.claude/agents/`) | `search` | Turns the JSON from `search-conversations.sh show --json` into a structured summary: what was done, decisions, files changed, problems, open items and topics. |

### Use `shield` when

- you are reading 3+ large external sources (URLs, Figma frames, wiki pages),
- you have a large documentation or API reference site to decompose into section URLs,
- you are auditing a monorepo across many directories,
- you are researching a dependency upgrade across 5+ packages,
- you are reviewing a large PR with 15+ changed files,
- you are building a competitive feature matrix,
- you are triaging security advisories for dependency updates.

Sources are `url`, `figma`, `file`, `wiki` or `codebase`. With more than 2 batches, `shield` hands the loop to the `ralph-loop` plugin so each batch runs in a fresh context. The skill covers the workflow, the manifest format and ten common patterns.

### Use `search` when

- you want to find a past conversation,
- you want to recall what was discussed on a topic or date,
- you want to search conversation history,
- you say `/conversation-search`.

`search` can list recent conversations, search by topic, date, branch or project, deep-search inside the conversation files, show one conversation (a session ID prefix of 8 characters is enough), print statistics, and hand a conversation to the summarizer agent.

```shell
/context:search find where I debugged "CSRF token mismatch"
/context:search what did I work on last Tuesday?
/context:shield analyze these 12 Figma frames
```

## Scripts

Each skill's commands run its own scripts through `${CLAUDE_SKILL_DIR}`, so they work from your project directory. You normally do not run them yourself.

| Skill | Script | Purpose |
|---|---|---|
| `shield` | `manage-manifest.sh create\|status\|next-batch\|mark-done\|mark-failed\|reset\|summaries` | Creates and tracks the manifest of sources for a run. |
| `shield` | `visualize.sh <phase>` | Animated progress for each workflow phase (`SPEED=instant` skips the delay). |
| `search` | `search-conversations.sh list\|search\|show\|stats [--json]` | Searches `~/.claude/projects/`. |
| `search` | `validate-skill.sh <skill-dir>` | Same validator as the repo root. |

## Install and uninstall

Install the plugin; do not copy the skills by hand. A loose copy breaks the `${CLAUDE_SKILL_DIR}` paths and shadows the plugin.

```shell
/plugin marketplace add abhattacherjee/claude-code-skills
/plugin install context@claude-code-skills
/plugin uninstall context@claude-code-skills
```

If you used the old names, install `context` first, then remove the old `context-shield` and `conversation-search` copies (and `~/.claude/agents/content-distiller.md` and `conversation-summarizer.md`) so they cannot win a plain-language request.

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
