# Monorepo README Template

Used by `scripts/sync-monorepo.sh` to generate the root README.md for the monorepo.
Placeholders: `{{SKILL_CATALOG_TABLE}}`, `{{GITHUB_USER}}`, `{{SKILL_COUNT}}`, `{{LAST_UPDATED}}`.

---

# Claude Code Skills

A curated collection of {{SKILL_COUNT}} reusable [Agent Skills](https://agentskills.io) for
Claude Code, Cursor, Codex CLI, and Gemini CLI.

## Skills

{{SKILL_CATALOG_TABLE}}

## Installation

### Install all skills

```bash
git clone https://github.com/{{GITHUB_USER}}/claude-code-skills.git /tmp/claude-code-skills
{{SKILL_INSTALL_ALL_COMMANDS}}
rm -rf /tmp/claude-code-skills
```

### Install a single skill from the monorepo

```bash
# Clone the monorepo
git clone https://github.com/{{GITHUB_USER}}/claude-code-skills.git /tmp/claude-code-skills

# Copy the skill you want
cp -r /tmp/claude-code-skills/SKILL_NAME ~/.claude/skills/SKILL_NAME

# Clean up
rm -rf /tmp/claude-code-skills
```

### Sparse checkout (single skill, minimal download)

```bash
git clone --filter=blob:none --sparse https://github.com/{{GITHUB_USER}}/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set SKILL_NAME
cp -r SKILL_NAME ~/.claude/skills/SKILL_NAME
rm -rf /tmp/ccs
```

### Install from individual repo

Each skill is also available as a standalone repository:

```bash
git clone https://github.com/{{GITHUB_USER}}/SKILL_NAME.git ~/.claude/skills/SKILL_NAME
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
*Last synced: {{LAST_UPDATED}}*
