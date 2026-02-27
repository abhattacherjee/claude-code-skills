# skill-publishing

Makes any Claude Code skill shareable on GitHub. Supports three distribution models: individual repos, a monorepo, and plugins (bundles of skills + commands).

## What It Does

This skill handles the entire lifecycle of publishing Claude Code skills to GitHub:

1. **Individual repos** — generates README, LICENSE, CHANGELOG, .gitignore, initializes git, and pushes to a standalone GitHub repo per skill
2. **Monorepo** — syncs all your skills into a single `claude-code-skills` repository with an auto-generated catalog README
3. **Plugins** — assembles skills + commands into installable plugin packages with marketplace support
4. **Interactive flow** — detects what's already published and lets you choose targets with `multiSelect`, including safe removal of deselected targets

## Key Features

### Plugin Assembly Pipeline

Bundles skills and slash commands into the official Claude Code Plugin format:

```
plugin-manifest.json → prepare-plugin.sh → validate-plugin.sh → sync-monorepo.sh
```

Output:
```
plugin-name/
├── .claude-plugin/plugin.json    # Required manifest
├── skills/skill-name/SKILL.md    # Skills with scripts/ and references/
├── commands/cmd-name.md          # Slash commands
└── README.md                     # Auto-generated with install instructions
```

### Monorepo with Marketplace

The monorepo generates a `.claude-plugin/marketplace.json` enabling plugin discovery:

```shell
# Users can install plugins with two commands
/plugin marketplace add your-username/claude-code-skills
/plugin install git-flow@claude-code-skills
```

### Interactive Publishing

When invoked, the skill:
- Detects current state (which targets each skill is already published to)
- Presents options with state labels: `Individual repo (published)`, `Monorepo (synced)`, `Plugin (synced)`
- Handles additions AND removals (deselecting a target removes the skill from that location)
- Confirms destructive operations before executing
- Auto-syncs to monorepo, commits, and pushes when Monorepo/Plugin targets are selected

### Included Scripts

| Script | Purpose |
|--------|---------|
| `prepare-skill-repo.sh` | Generate scaffolding for individual GitHub repos |
| `sync-monorepo.sh` | Sync skills + plugins to the monorepo, generate README catalog |
| `sync-individual-repos.sh` | Push updates to all individual repos at once |
| `prepare-plugin.sh` | Assemble a plugin from a build manifest |
| `validate-plugin.sh` | Validate plugin structure and contents |
| `install-plugin.sh` | Install/uninstall a plugin to `~/.claude/` |
| `release-monorepo.sh` | Create versioned releases with tags |

All scripts support `--dry-run` and `--help`.

## Contents

- **1** skill(s)
- **0** command(s)

### Skills

- `skill-publishing` — SKILL.md with publishing workflows + 10 automation scripts

## Usage

```bash
# Invoke the skill
"Publish my git-flow skill"
"Sync skills to the monorepo"
"Share this skill on GitHub"

# Or use scripts directly
SCRIPTS=~/.claude/skills/skill-publishing/scripts

# Publish a new skill as individual repo
$SCRIPTS/prepare-skill-repo.sh /path/to/skill

# Sync everything to monorepo
$SCRIPTS/sync-monorepo.sh ~/dev/claude-code-skills

# Assemble a plugin
$SCRIPTS/prepare-plugin.sh /path/to/plugin-manifest.json

# Create a versioned release
$SCRIPTS/release-monorepo.sh minor ~/dev/claude-code-skills
```

## Prerequisites

- **GitHub CLI** (`gh`) — for repo creation, releases, and user detection
- **jq** — for plugin manifest parsing (plugin features only)
- **rsync** — for directory syncing (available by default on macOS/Linux)

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install skill-publishing@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/skill-publishing
rm -rf /tmp/ccs
```

### Manual

```bash
cp -r plugins/skill-publishing/skills/* ~/.claude/skills/
```

## Uninstall

```bash
# Via Claude Code
/plugin uninstall skill-publishing@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/skill-publishing
rm -rf /tmp/ccs
```

## Companion Skills

- **[skill-authoring](../skill-authoring/)** — how to write skills (the content); this skill handles distribution (the packaging)
- **[claudeception](../../claudeception/)** — extracts knowledge into skills, which can then be published with this skill

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
