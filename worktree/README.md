# worktree

Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch.

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/abhattacherjee/worktree.git ~/.claude/skills/worktree

# Windows
git clone https://github.com/abhattacherjee/worktree.git %USERPROFILE%\.claude\skills\worktree
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/abhattacherjee/worktree.git .claude/skills/worktree
```

### Via monorepo (all skills)

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/worktree ~/.claude/skills/worktree
rm -rf /tmp/claude-code-skills
```

## Updating

```bash
git -C ~/.claude/skills/worktree pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/worktree
```

## What It Does

Creates isolated git worktrees for parallel Claude Code sessions, each on its own branch.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
worktree/
├── scripts/
    ├── setup-worktree.sh
├── SKILL.md
```

## License

[MIT](LICENSE)
