# changelog-keeper

Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/changelog-keeper ~/.claude/skills/changelog-keeper
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set changelog-keeper
cp -r changelog-keeper ~/.claude/skills/changelog-keeper
rm -rf /tmp/ccs
```

### From individual repo

```bash
git clone https://github.com/abhattacherjee/changelog-keeper.git ~/.claude/skills/changelog-keeper
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r changelog-keeper ~/.claude/skills/changelog-keeper

# If installed from individual repo
git -C ~/.claude/skills/changelog-keeper pull
```

## What It Does

Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
