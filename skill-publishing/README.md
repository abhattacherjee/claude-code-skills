# skill-publishing

Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports both individual repos and a monorepo (claude-code-skills).

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/skill-publishing ~/.claude/skills/skill-publishing
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set skill-publishing
cp -r skill-publishing ~/.claude/skills/skill-publishing
rm -rf /tmp/ccs
```

### From individual repo

```bash
git clone https://github.com/abhattacherjee/skill-publishing.git ~/.claude/skills/skill-publishing
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r skill-publishing ~/.claude/skills/skill-publishing

# If installed from individual repo
git -C ~/.claude/skills/skill-publishing pull
```

## What It Does

Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports both individual repos and a monorepo (claude-code-skills).

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
