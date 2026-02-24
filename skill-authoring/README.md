# skill-authoring

Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism.

## Installation

### From this monorepo

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/skill-authoring ~/.claude/skills/skill-authoring
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set skill-authoring
cp -r skill-authoring ~/.claude/skills/skill-authoring
rm -rf /tmp/ccs
```

### From individual repo

```bash
git clone https://github.com/abhattacherjee/skill-authoring.git ~/.claude/skills/skill-authoring
```

## Updating

```bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r skill-authoring ~/.claude/skills/skill-authoring

# If installed from individual repo
git -C ~/.claude/skills/skill-authoring pull
```

## What It Does

Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
