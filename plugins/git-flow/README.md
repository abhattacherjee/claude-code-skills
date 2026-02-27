# git-flow

Git Flow branching workflow with slash commands and diagnostic tools. Manages `feature/*`, `release/*`, and `hotfix/*` branches with proper merge targets, tagging, and cleanup.

## What It Does

This plugin gives Claude Code full Git Flow awareness. Instead of remembering merge targets and tag conventions, just use the slash commands:

- **`/feature <name>`** — creates `feature/<name>` from `develop`, sets up tracking
- **`/release <version>`** — creates `release/<version>` from `develop`, bumps version
- **`/hotfix`** — creates `hotfix/<version>` from `main`, auto-increments patch version
- **`/finish`** — merges current branch to the right target(s) with `--no-ff`, tags releases/hotfixes, cleans up
- **`/flow-status`** — shows current branch type, sync status, merge targets, and actionable next steps

The underlying skill provides Claude with the complete branching model reference so it handles edge cases (merge conflicts, uncommitted changes, release-to-develop back-merges) automatically.

## Key Features

### Branch Lifecycle Management

```
main ← develop ← feature/*, release/*, hotfix/*
```

| Branch Type | Created From | Merges To | Tag? |
|-------------|-------------|-----------|------|
| `feature/*` | `develop` | `develop` | No |
| `release/*` | `develop` | `main` + `develop` | Yes (`vX.Y.Z`) |
| `hotfix/*` | `main` | `main` + `develop` | Yes (`vX.Y.Z`) |

### Diagnostic Script

```bash
# JSON output for programmatic use
~/.claude/skills/git-flow/scripts/git-flow-status.sh --json

# Human-readable status
~/.claude/skills/git-flow/scripts/git-flow-status.sh
```

Shows: current branch type, commits ahead/behind, active release/hotfix branches, recent tags, and suggested next action.

## Contents

- **1** skill(s)
- **5** command(s)

### Skills

- `git-flow` — branching model reference + `git-flow-status.sh` diagnostic script

### Commands

- `/feature` — create a feature branch
- `/release` — create a release branch
- `/hotfix` — create a hotfix branch
- `/finish` — complete and merge the current branch
- `/flow-status` — show Git Flow repository status

## Usage

```
# Start a new feature
/feature add-dark-mode

# Check repository state
/flow-status

# Ship the feature
/finish

# Cut a release
/release 2.0.0

# Emergency fix on production
/hotfix
```

## Prerequisites

- Git repository initialized with `main` and `develop` branches
- GitHub CLI (`gh`) for remote operations (optional but recommended)

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

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
