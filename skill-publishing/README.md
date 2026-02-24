# skill-publishing

Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags.

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

```bash
# macOS / Linux
git clone https://github.com/abhattacherjee/skill-publishing.git ~/.claude/skills/skill-publishing

# Windows
git clone https://github.com/abhattacherjee/skill-publishing.git %USERPROFILE%\.claude\skills\skill-publishing
```

**Project-level** (available only in one project):

```bash
git clone https://github.com/abhattacherjee/skill-publishing.git .claude/skills/skill-publishing
```

### Via monorepo (all skills)

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/skill-publishing ~/.claude/skills/skill-publishing
rm -rf /tmp/claude-code-skills
```

## Updating

```bash
git -C ~/.claude/skills/skill-publishing pull
```

## Uninstall

```bash
rm -rf ~/.claude/skills/skill-publishing
```

## What It Does

Converts a local Claude Code skill directory into a shareable GitHub repository:
- **Generates** `.gitignore`, `LICENSE` (MIT), `CHANGELOG.md`, and `README.md` from `SKILL.md` frontmatter
- **Skips** existing files (safe to re-run on already-prepared skills)
- **Excludes** `.claude/` from git (contains user-specific local settings)
- **Guides** through `git init`, `gh repo create`, tagging, and pushing
### Usage
```bash
# Preview what will be created (dry run)
prepare-skill-repo.sh --dry-run ~/.claude/skills/my-skill
# Generate files with GitHub username
prepare-skill-repo.sh --github-user myuser ~/.claude/skills/my-skill
# Then follow the printed next steps to git init + push
```
The script reads `name`, `description`, and `version` from `SKILL.md` frontmatter to populate all generated files automatically.

## Compatibility

This skill follows the **Agent Skills** standard — a `SKILL.md` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

```
skill-publishing/
├── .github/
    ├── PULL_REQUEST_TEMPLATE.md
    ├── workflows/
        ├── validate-skill.yml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── references/
    ├── CONTRIBUTING-template.md
    ├── monorepo-readme-template.md
    ├── PR_TEMPLATE-template.md
    ├── readme-template.md
    ├── workflow-individual.yml
    ├── workflow-monorepo.yml
├── scripts/
    ├── apply-branch-protection.sh
    ├── prepare-skill-repo.sh
    ├── release-monorepo.sh
    ├── sync-individual-repos.sh
    ├── sync-monorepo.sh
    ├── validate-skill.sh
├── SKILL.md
```

## License

[MIT](LICENSE)
