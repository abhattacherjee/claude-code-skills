
# Claude Code Skills

A curated collection of 5 reusable [Agent Skills](https://agentskills.io) for
Claude Code, Cursor, Codex CLI, and Gemini CLI.

## Skills

| Skill | Version | Description | Individual Repo |
|-------|---------|-------------|-----------------|
| [changelog-keeper](./changelog-keeper/) | 1.0.0 | Keeps CHANGELOG.md up to date by generating categorized entries from git commit history. | [repo](https://github.com/abhattacherjee/changelog-keeper) |
| [claudeception](./claudeception/) | 3.2.0 | Extracts reusable knowledge from work sessions and codifies it into Claude Code skills. | [repo](https://github.com/abhattacherjee/claudeception) |
| [conversation-search](./conversation-search/) | 1.1.0 | Searches Claude Code conversation history in ~/.claude/projects/ by topic, date, branch, or project. Provides verbatim conversation content and AI-generated summaries. | [repo](https://github.com/abhattacherjee/conversation-search) |
| [skill-authoring](./skill-authoring/) | 2.0.0 | Creates and optimizes Claude Code skills following Anthropic's official best practices with emphasis on agent parallelization and script-first determinism. | [repo](https://github.com/abhattacherjee/skill-authoring) |
| [skill-publishing](./skill-publishing/) | 2.0.0 | Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports both individual repos and a monorepo (claude-code-skills). | [repo](https://github.com/abhattacherjee/skill-publishing) |


## Installation

### Install all skills

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/changelog-keeper ~/.claude/skills/changelog-keeper
cp -r /tmp/claude-code-skills/claudeception ~/.claude/skills/claudeception
cp -r /tmp/claude-code-skills/conversation-search ~/.claude/skills/conversation-search
cp -r /tmp/claude-code-skills/skill-authoring ~/.claude/skills/skill-authoring
cp -r /tmp/claude-code-skills/skill-publishing ~/.claude/skills/skill-publishing
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
*Last synced: 2026-02-24*
