# README Template for Shareable Skills

Used by `scripts/prepare-skill-repo.sh` to generate a README.md.
Placeholders: `{{SKILL_NAME}}`, `{{DESCRIPTION}}`, `{{GITHUB_USER}}`, `{{VERSION}}`,
`{{DIRECTORY_TREE}}`, `{{WHAT_IT_DOES}}`.

---

# {{SKILL_NAME}}

{{DESCRIPTION}}

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/{{GITHUB_USER}}/{{SKILL_NAME}}.git ~/.claude/skills/{{SKILL_NAME}}

# Windows
git clone https://github.com/{{GITHUB_USER}}/{{SKILL_NAME}}.git %USERPROFILE%\.claude\skills\{{SKILL_NAME}}
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/{{GITHUB_USER}}/{{SKILL_NAME}}.git .claude/skills/{{SKILL_NAME}}
```

### Via monorepo (all skills)

```bash
git clone https://github.com/{{GITHUB_USER}}/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/{{SKILL_NAME}} ~/.claude/skills/{{SKILL_NAME}}
rm -rf /tmp/claude-code-skills
```

## Updating

```bash
git -C ~/.claude/skills/{{SKILL_NAME}} pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/{{SKILL_NAME}}
```

## What It Does

{{WHAT_IT_DOES}}

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
{{DIRECTORY_TREE}}
```

## License

[MIT](LICENSE)
