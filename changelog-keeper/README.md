# changelog-keeper

Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/abhattacherjee/changelog-keeper.git ~/.claude/skills/changelog-keeper

# Windows
git clone https://github.com/abhattacherjee/changelog-keeper.git %USERPROFILE%\.claude\skills\changelog-keeper
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/abhattacherjee/changelog-keeper.git .claude/skills/changelog-keeper
```

### Via monorepo (all skills)

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/changelog-keeper ~/.claude/skills/changelog-keeper
rm -rf /tmp/claude-code-skills
```

## Updating

```bash
git -C ~/.claude/skills/changelog-keeper pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/changelog-keeper
```

## What It Does

Keeps CHANGELOG.md up to date by generating categorized entries from git commit history.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
changelog-keeper/
├── scripts/
    ├── update-changelog.sh
├── SKILL.md
```

## License

[MIT](LICENSE)
