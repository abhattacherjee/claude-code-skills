# git-flow

Git Flow branching workflow with slash commands and diagnostic tools

## What It Does

Git Flow branching workflow reference and status diagnostic.

**Use when:**
- /flow-status or checking repository state, 
- creating feature/release/hotfix branches, 
- finishing and merging Git Flow branches, 
- understanding Git Flow conventions in any repository, 
- setting up or overriding Git Flow commands for a new project.

## Key Features

- **Branching Model**
- **Two-Tier Command Architecture**
- **Command Decision Table**
- **Common Workflows**
- **Gotchas**
- **Environment Variables**
- **Directory Layout**

## Usage

```bash
~/.claude/skills/git-flow/scripts/git-flow-status.sh            # Human-readable
~/.claude/skills/git-flow/scripts/git-flow-status.sh --json     # For agent consumption
~/.claude/skills/git-flow/scripts/git-flow-status.sh --help     # Usage
```

## Contents

- **1** skill(s), **5** command(s)

### Skills

- `git-flow` — Git Flow branching workflow reference and status diagnostic.

### Commands

- `/feature` — Create a new Git Flow feature branch from develop with proper naming and tracking
- `/release` — Create a new Git Flow release branch from develop with version bumping and changelog generation
- `/hotfix` — Create a new Git Flow hotfix branch from main with auto-versioning
- `/finish` — Complete and merge current Git Flow branch (feature/release/hotfix) with proper cleanup and tagging
- `/flow-status` — Display comprehensive Git Flow status including branch type, sync status, changes, and merge targets

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install git-flow@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/git-flow
rm -rf /tmp/ccs
```

### Manual

```bash
# Copy skills
cp -r plugins/git-flow/skills/* ~/.claude/skills/

# Copy commands
cp plugins/git-flow/commands/*.md ~/.claude/commands/
```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall git-flow@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/git-flow
rm -rf /tmp/ccs
```

## See Also

- **[references/override-guide.md](references/override-guide.md)** — full override guide with patterns, per-command surface, and checklist
- `git-branch-cleanup` — audit and delete stale branches after merges
- `changelog-keeper` — generate CHANGELOG.md from commit history
- `release-and-git-flow` (project-level) — hook workarounds and release pipeline

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
