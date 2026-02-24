# conversation-search

Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries.

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/conversation-search ~/.claude/skills/conversation-search
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set conversation-search
cp -r conversation-search ~/.claude/skills/conversation-search
rm -rf /tmp/ccs
```

### From individual repo

```bash
git clone https://github.com/abhattacherjee/conversation-search.git ~/.claude/skills/conversation-search
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r conversation-search ~/.claude/skills/conversation-search

# If installed from individual repo
git -C ~/.claude/skills/conversation-search pull
```

## What It Does

Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
