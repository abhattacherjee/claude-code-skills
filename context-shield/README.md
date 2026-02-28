# context-shield

Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently.

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/context-shield ~/.claude/skills/context-shield
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set context-shield
cp -r context-shield ~/.claude/skills/context-shield
rm -rf /tmp/ccs
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r context-shield ~/.claude/skills/context-shield

# If installed from individual repo
git -C ~/.claude/skills/context-shield pull
```

## What It Does

Prevents context window overflow when processing large content (Figma designs, web pages, GitHub wikis, large codebases). Delegates token-heavy reads to isolated sub-agents that return distilled summaries. Auto-detects when ralph-loop is needed based on batch count and activates it transparently.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
