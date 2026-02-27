---
name: skill-publishing
description: "Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), versioned monorepo releases with semver tags, and plugin assembly/distribution. Use when: (1) a skill directory needs to be published to GitHub, (2) user wants to make a skill installable by others, (3) user says 'share this skill' or 'publish skill to GitHub', (4) preparing a skill for open-source distribution, (5) syncing skills to the monorepo, (6) user says 'sync skills' or 'update monorepo', (7) creating a versioned monorepo release with tag, (8) assembling a plugin from skills + commands, (9) user says 'publish plugin' or 'package plugin'."
metadata:
  version: 3.0.0
---

# Skill to GitHub

Converts local Claude Code skill directories into shareable GitHub repositories.
Supports three distribution models: **individual repos**, a **monorepo** (`claude-code-skills`),
and **plugins** (bundles of skills + commands).

## Quick Reference

```bash
SCRIPTS=~/.claude/skills/skill-publishing/scripts

# --- Individual repo (first-time publish) ---
$SCRIPTS/prepare-skill-repo.sh --dry-run /path/to/skill
$SCRIPTS/prepare-skill-repo.sh /path/to/skill

# --- Individual repos (sync all published) ---
$SCRIPTS/sync-individual-repos.sh --dry-run --all
$SCRIPTS/sync-individual-repos.sh --all --push

# --- Monorepo (initialize) ---
$SCRIPTS/sync-monorepo.sh --init ~/dev/claude-code-skills

# --- Monorepo (sync) ---
$SCRIPTS/sync-monorepo.sh --dry-run ~/dev/claude-code-skills
$SCRIPTS/sync-monorepo.sh ~/dev/claude-code-skills

# --- Monorepo (add a new skill) ---
$SCRIPTS/sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills

# --- After reviewing, push manually:
cd ~/dev/claude-code-skills
git add -A && git commit -m "Sync skills (YYYY-MM-DD)" && git push

# --- Monorepo release (version tag) ---
$SCRIPTS/release-monorepo.sh --dry-run minor ~/dev/claude-code-skills
$SCRIPTS/release-monorepo.sh patch ~/dev/claude-code-skills   # Bug fixes
$SCRIPTS/release-monorepo.sh minor ~/dev/claude-code-skills   # New skill
$SCRIPTS/release-monorepo.sh major ~/dev/claude-code-skills   # Breaking change

# --- Plugin (assemble from manifest) ---
$SCRIPTS/prepare-plugin.sh --dry-run /path/to/plugin-manifest.json
$SCRIPTS/prepare-plugin.sh /path/to/plugin-manifest.json

# --- Plugin (validate) ---
$SCRIPTS/validate-plugin.sh ./build/plugin-name

# --- Plugin (add to monorepo) ---
$SCRIPTS/sync-monorepo.sh --add-plugin plugin-name ~/dev/claude-code-skills

# --- Plugin (install from assembled plugin) ---
$SCRIPTS/install-plugin.sh --dry-run ./build/plugin-name
$SCRIPTS/install-plugin.sh ./build/plugin-name
$SCRIPTS/install-plugin.sh --uninstall ./build/plugin-name
```

## Architecture

```
~/.claude/skills/              (SOURCE OF RECORD)
├── conversation-search/
├── skill-authoring/
├── skill-publishing/
├── git-flow/
│   └── plugin-manifest.json   (build manifest for plugins)
└── ...

Individual repos:              (each skill has its own GitHub repo)
├── github.com/USER/conversation-search
├── github.com/USER/skill-authoring
└── github.com/USER/skill-publishing

Monorepo:                      (all skills + plugins in one repo)
└── github.com/USER/claude-code-skills
    ├── README.md              (auto-generated: skill table + plugin section)
    ├── conversation-search/   (skill — flat at root)
    ├── skill-authoring/
    ├── skill-publishing/
    ├── plugins/               (plugins — under plugins/ subfolder)
    │   └── git-flow/
    │       ├── .claude-plugin/plugin.json
    │       ├── commands/
    │       └── skills/
    └── scripts/
        ├── validate-skill.sh
        ├── validate-plugin.sh
        └── install-plugin.sh
```

**Key principle**: `~/.claude/skills/` is the single source of truth. Both individual repos and the monorepo are derived from it via flat-copy (no git subtrees). Plugins are assembled from build manifests and stored in `plugins/`.

## Workflow A: Publish a New Skill (Individual Repo)

### Step 1: Run the Preparation Script

```bash
~/.claude/skills/skill-publishing/scripts/prepare-skill-repo.sh /path/to/skill
```

The script:
- Reads `SKILL.md` frontmatter to extract `name`, `description`, `version`
- Creates `.gitignore` (with `.claude/` exclusion for local settings)
- Creates `LICENSE` (MIT)
- Creates `CHANGELOG.md` from the extracted metadata
- Generates a `README.md` with individual + monorepo install instructions
- Reports what files already exist (skips them) vs what was created

### Step 2: Review and Customize

After the script runs, review the generated files. Common customizations:
- **README.md**: Add a Prerequisites section if the skill has dependencies (e.g., `jq`, `perl`)
- **README.md**: Add usage examples specific to the skill
- **CHANGELOG.md**: Expand the "Included" section with more detail
- **SKILL.md**: Add a See Also section linking to the GitHub repo

### Step 3: Add See Also to SKILL.md

Append to the end of `SKILL.md`:

```markdown
## See Also

- **GitHub**: https://github.com/<github-user>/<skill-name> — install instructions, changelog, license
```

### Step 4: Initialize Git and Push

```bash
cd /path/to/skill
git init
git add .gitignore LICENSE CHANGELOG.md README.md SKILL.md scripts/ references/
git commit -m "Initial public release: <skill-name> v<version>"
gh repo create <skill-name> --public --description "<short-description>" --source . --push
git tag v<version>
git push origin v<version>
```

**Known gotcha**: If `git remote add origin` was already run before `gh repo create --source .`,
the latter fails with "Unable to add remote" — but the repo IS created. Fix with
`git remote set-url origin <url>` then push manually.

**Username discovery**: `gh repo create` reveals the actual GitHub username (e.g., `abhattacherjee`
not `abhishek`). After repo creation, update any references in README.md and SKILL.md with the
correct username.

### Step 5: Verify

After pushing:
1. Clone to a temp dir: `git clone <url> /tmp/test-skill`
2. Confirm `SKILL.md` is at root with correct frontmatter
3. Confirm `scripts/` and `references/` are present (if applicable)
4. Check that `.claude/` was NOT committed

## Workflow B: Sync to Monorepo

### First Time: Initialize the Monorepo

```bash
~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh --init ~/dev/claude-code-skills
```

This creates the directory, syncs the default skills (conversation-search, skill-authoring, skill-publishing), generates the root README with a catalog table, and creates + pushes the GitHub repo.

### Ongoing: Sync Changes

```bash
# Preview changes
~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh --dry-run ~/dev/claude-code-skills

# Sync
~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh ~/dev/claude-code-skills

# Then commit and push
cd ~/dev/claude-code-skills
git add -A && git commit -m "Sync skills ($(date +%Y-%m-%d))" && git push
```

### Adding a New Skill to the Monorepo

```bash
~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills
```

## Workflow C: Sync Individual Repos

When you update a skill locally and want to push changes to its individual GitHub repo:

```bash
# Preview changes to all published repos
~/.claude/skills/skill-publishing/scripts/sync-individual-repos.sh --dry-run --all

# Sync all and auto-push
~/.claude/skills/skill-publishing/scripts/sync-individual-repos.sh --all --push

# Sync a specific skill
~/.claude/skills/skill-publishing/scripts/sync-individual-repos.sh conversation-search
```

## Workflow D: Monorepo Release (Version Tag)

After syncing skills to the monorepo and committing, create a versioned release:

```bash
# 1. Sync skills first
~/.claude/skills/skill-publishing/scripts/sync-monorepo.sh ~/dev/claude-code-skills
cd ~/dev/claude-code-skills
git add -A && git commit -m "Sync skills ($(date +%Y-%m-%d))"
git push

# 2. Create a versioned release
~/.claude/skills/skill-publishing/scripts/release-monorepo.sh minor ~/dev/claude-code-skills
```

### Bump Levels

| Level | When | Example |
|-------|------|---------|
| `patch` | Bug fixes, sync updates, typo fixes | 1.0.0 → 1.0.1 |
| `minor` | New skill added, feature improvements | 1.0.0 → 1.1.0 |
| `major` | Breaking changes, removed skills, restructured layout | 1.0.0 → 2.0.0 |

The script:
- Reads current version from the latest `v*` semver tag
- Calculates the next version based on bump level
- Updates the CHANGELOG top entry from "Monorepo sync" to a versioned section
- Commits the changelog update
- Creates an annotated tag with skill inventory
- Pushes to `origin main --tags`

Use `--dry-run` to preview without making changes.

**Prerequisite**: All changes must be committed before running. The script rejects uncommitted changes.

## Workflow E: Publish a Plugin

A plugin bundles skills + commands + optional agents/hooks into a single installable package.

### Plugin Format

```
plugin-name/
├── .claude-plugin/plugin.json   # Required manifest: {name, version, description}
├── commands/                    # Slash commands (.md files)
├── skills/skill-name/           # Skills (SKILL.md + scripts/ + references/)
├── agents/                      # Subagents (.md files, optional)
└── hooks/                       # hooks.json + scripts (optional)
```

### Step 1: Create Build Manifest

Create `plugin-manifest.json` in the skill directory that anchors the plugin:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Short description",
  "skills": [{ "name": "my-skill", "source": "~/.claude/skills/my-skill" }],
  "commands": [{ "name": "cmd-name", "source": "~/.claude/commands/cmd-name.md" }]
}
```

### Step 2: Assemble

```bash
$SCRIPTS/prepare-plugin.sh /path/to/plugin-manifest.json
```

This creates `./build/<plugin-name>/` with the official plugin format, scaffolding, and auto-runs validation.

### Step 3: Validate

```bash
$SCRIPTS/validate-plugin.sh ./build/<plugin-name>
```

### Step 4: Sync to Monorepo

```bash
$SCRIPTS/sync-monorepo.sh --add-plugin <plugin-name> ~/dev/claude-code-skills
cd ~/dev/claude-code-skills
git add -A && git commit -m "feat: add <plugin-name> plugin" && git push
```

### Step 5: Install (Consumer)

```bash
git clone https://github.com/USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/<plugin-name>
rm -rf /tmp/ccs
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `.claude/` in `.gitignore` | Always | Contains `settings.local.json` with user-specific permissions |
| License | MIT default | Most permissive, standard for open-source tools |
| Version from frontmatter | Use as-is | Avoids version mismatch between SKILL.md and tag |
| No install script for skills | By design | `git clone` IS the installer — no extra ceremony |
| Flat copy, not subtree | By design | Simpler mental model; local dir is single source of truth |
| Monorepo README | Auto-generated | Catalog table derived from SKILL.md frontmatter; never hand-edit |
| Plugins in `plugins/` subfolder | By design | Different structure than bare skills; separates concerns |
| Plugin build manifest (JSON) | `jq` dependency | Plugins bundle multiple sources; CLI-only would be unwieldy |
| `install-plugin.sh` in monorepo | Consumer-facing | Users need it to install plugins; not just an author tool |

## See Also

- `skill-authoring` — how to structure and write skills (the content)
- This skill handles the distribution packaging (the container)
- **GitHub**: https://github.com/abhattacherjee/skill-publishing — install instructions, changelog, license
