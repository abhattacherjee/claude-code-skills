# install-statusline

Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/custom-statusline ~/.claude/skills/custom-statusline
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set custom-statusline
cp -r custom-statusline ~/.claude/skills/custom-statusline
rm -rf /tmp/ccs
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r custom-statusline ~/.claude/skills/custom-statusline

# If installed from individual repo
git -C ~/.claude/skills/custom-statusline pull
```

## What It Does

Install a custom 4-tier adaptive statusline with icons for folder, git branch, and context usage

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
