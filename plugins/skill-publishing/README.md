# skill-publishing

Plugin-first publishing for Claude Code skills. Auto-assembles and syncs plugins from plugin-manifest.json files. Also supports bare skills and individual repos

## What It Does

Publishes Claude Code skills as installable plugins and syncs them to a GitHub monorepo. Plugin-first: every skill with a plugin-manifest.json is auto-assembled and synced as a plugin. Also supports bare skill publishing and individual repos.

**Use when:**
- user says 'publish', 'share', or 'sync' a skill, 
- a skill needs to be made installable by others, 
- syncing skills/plugins to the monorepo, 
- creating a versioned monorepo release, 
- assembling a plugin from skills + commands, 
- user says 'publish plugin' or 'package plugin'.

## Key Features

- **Architecture**
- **Interactive Publishing Flow**
- **Workflow A: Publish a New Skill (Individual Repo)**
- **Workflow B: Sync to Monorepo**
- **Workflow C: Sync Individual Repos**
- **Workflow D: Monorepo Release (Version Tag)**
- **Workflow E: Publish a Plugin (Manual Fallback)**

## Usage

```bash
SCRIPTS=~/.claude/skills/skill-publishing/scripts

# --- Monorepo sync (auto-discovers plugins) ---
$SCRIPTS/validate-pre-sync.sh ~/dev/claude-code-skills        # Pre-sync gate (MANDATORY)
$SCRIPTS/sync-monorepo.sh --dry-run ~/dev/claude-code-skills   # Preview
$SCRIPTS/sync-monorepo.sh ~/dev/claude-code-skills             # Sync (auto-builds plugins)

# --- Monorepo (add a new skill) ---
$SCRIPTS/sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills

# --- Monorepo (initialize) ---
$SCRIPTS/sync-monorepo.sh --init ~/dev/claude-code-skills

# --- Monorepo release (version tag) ---
$SCRIPTS/release-monorepo.sh patch ~/dev/claude-code-skills   # Bug fixes
$SCRIPTS/release-monorepo.sh minor ~/dev/claude-code-skills   # New skill/plugin
$SCRIPTS/release-monorepo.sh major ~/dev/claude-code-skills   # Breaking change

# --- Plugin (manual assemble + validate) ---
$SCRIPTS/prepare-plugin.sh /path/to/plugin-manifest.json      # Build plugin
$SCRIPTS/validate-plugin.sh ./build/plugin-name                # Validate
$SCRIPTS/install-plugin.sh ./build/plugin-name                 # Install locally

# --- Individual repo (first-time publish) ---
$SCRIPTS/prepare-skill-repo.sh /path/to/skill

# --- Individual repos (sync all published) ---
$SCRIPTS/sync-individual-repos.sh --all --push
```

## Contents

- **1** skill(s), **0** command(s)

### Skills

- `skill-publishing` — Publishes Claude Code skills as installable plugins and syncs them to a GitHub monorepo. Plugin-first: every skill with a plugin-manifest.json is auto-assembled and synced as a plugin. Also supports bare skill publishing and individual repos.

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
# Copy skills
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

## See Also

- `skill-authoring` — how to structure and write skills (the content)
- This skill handles the distribution packaging (the container)
- **GitHub**: https://github.com/abhattacherjee/claude-code-skills/tree/main/skill-publishing — install instructions, changelog, license

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)
