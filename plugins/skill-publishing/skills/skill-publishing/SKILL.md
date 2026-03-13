---
name: skill-publishing
description: "Publishes Claude Code skills as installable plugins and syncs them to a GitHub monorepo. Plugin-first: every skill with a plugin-manifest.json is auto-assembled and synced as a plugin. Also supports bare skill publishing and individual repos. Use when: (1) user says 'publish', 'share', or 'sync' a skill, (2) a skill needs to be made installable by others, (3) syncing skills/plugins to the monorepo, (4) creating a versioned monorepo release, (5) assembling a plugin from skills + commands, (6) user says 'publish plugin' or 'package plugin'."
metadata:
  version: 4.0.0
---

# Publish Skills & Plugins

**Plugin-first publishing** for Claude Code skills. Every skill with a `plugin-manifest.json`
is automatically assembled and synced as an installable plugin. Bare skills (without manifests)
are synced as standalone directories. Both live in the `claude-code-skills` monorepo.

## Quick Reference

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

## Architecture

```
~/.claude/skills/              (SOURCE OF RECORD)
├── git-flow/                  (has plugin-manifest.json → synced as PLUGIN)
│   └── plugin-manifest.json
├── context-shield/            (has plugin-manifest.json → synced as PLUGIN)
│   └── plugin-manifest.json
├── conversation-search/       (no manifest → synced as BARE SKILL)
└── ...

Monorepo:                      (all skills + plugins in one repo)
└── github.com/USER/claude-code-skills
    ├── README.md              (auto-generated: skill table + plugin section)
    ├── conversation-search/   (bare skill — flat at root)
    ├── plugins/               (plugins — auto-assembled from manifests)
    │   ├── git-flow/
    │   │   ├── .claude-plugin/plugin.json
    │   │   ├── commands/
    │   │   └── skills/
    │   └── context-shield/
    └── scripts/
        ├── validate-skill.sh
        ├── validate-plugin.sh
        └── install-plugin.sh
```

**Key principles**:
- `~/.claude/skills/` is the single source of truth
- **Plugin-first**: Skills with `plugin-manifest.json` are auto-assembled into plugins during sync
- Skills without manifests are synced as bare directories (backward compatible)
- `sync-monorepo.sh` handles both automatically — no separate `--add-plugin` needed for known plugins

## Interactive Publishing Flow

When invoked (e.g., "publish this skill", "share skill", "sync skills"), start with target selection.

### Step 1: Detect Current State

For the skill being published, detect which targets it's already published to:

```bash
SKILL_NAME="<name-from-frontmatter>"
GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null)
MONOREPO_DIR="${HOME}/dev/claude-code-skills"

# Has plugin manifest? (determines default target)
HAS_MANIFEST=false
[[ -f "$SKILL_DIR/plugin-manifest.json" ]] && HAS_MANIFEST=true

# Plugin synced?
PLUGIN_SYNCED=false
[[ -d "$MONOREPO_DIR/plugins/$SKILL_NAME" ]] && PLUGIN_SYNCED=true

# Bare skill synced?
MONOREPO_SYNCED=false
[[ -f "$MONOREPO_DIR/$SKILL_NAME/SKILL.md" ]] && MONOREPO_SYNCED=true

# Individual repo?
INDIVIDUAL_PUBLISHED=false
gh repo view "$GITHUB_USER/$SKILL_NAME" --json name >/dev/null 2>&1 && INDIVIDUAL_PUBLISHED=true
```

### Step 2: Present Target Selection (Plugin-First)

Use `AskUserQuestion` with `multiSelect: true`. **Default: Plugin is pre-selected when manifest exists.** If no manifest exists, offer to create one.

**Question**: "Which publishing targets do you want for `<skill-name>`?"

**Options** (ordered by priority — plugin first):

| State | Label | Default | Description |
|-------|-------|---------|-------------|
| Has manifest, not synced | `Plugin (recommended)` | **SELECTED** | "Assemble and sync as installable plugin" |
| Has manifest, synced | `Plugin (synced)` | **SELECTED** | "Keep synced. Deselect to REMOVE" |
| No manifest | `Plugin` | disabled | "Create a plugin-manifest.json first (see below)" |
| Not synced | `Bare skill` | unselected | "Add as bare directory (no plugin format)" |
| Synced | `Bare skill (synced)` | **SELECTED** | "Keep synced. Deselect to REMOVE" |
| Not published | `Individual repo` | unselected | "Create a standalone GitHub repo" |
| Published | `Individual repo (published)` | **SELECTED** | "Keep synced. Deselect to DELETE" |

**When no manifest exists**, prompt:

> This skill doesn't have a `plugin-manifest.json`. Plugins are the recommended format
> for installable skills. Create a minimal manifest now?
>
> A minimal manifest for a single-skill plugin looks like:
> ```json
> {
>   "name": "<skill-name>",
>   "version": "<version-from-SKILL.md>",
>   "description": "<description-from-SKILL.md>",
>   "skills": [{ "name": "<skill-name>", "source": "~/.claude/skills/<skill-name>" }],
>   "commands": []
> }
> ```

If user agrees, create the manifest and proceed with plugin publishing.

### Step 3: Dispatch

**For each SELECTED target:**

| Target | Already Published? | Action |
|--------|--------------------|--------|
| Plugin | No | Auto-handled by `sync-monorepo.sh` if manifest exists (or manual **Workflow E**) |
| Plugin | Yes | Auto-rebuilt on next sync if source drifted (or manual **Workflow E**) |
| Bare skill | No | Run `sync-monorepo.sh --add <name>` then **Workflow B** |
| Bare skill | Yes | Run **Workflow B** (sync monorepo) |
| Individual repo | No | Run **Workflow A** (prepare + push) |
| Individual repo | Yes | Run **Workflow C** (sync individual repo) |

**For each DESELECTED target that was previously published (removal):**

| Target | Removal Action |
|--------|---------------|
| Plugin | `rm -rf $MONOREPO_DIR/plugins/$SKILL_NAME/` then re-sync README + commit + push |
| Bare skill | `rm -rf $MONOREPO_DIR/$SKILL_NAME/` then re-sync README + commit + push |
| Individual repo | `gh repo delete $GITHUB_USER/$SKILL_NAME --yes` (confirm with user first!) |

**Always confirm destructive removals** with the user before executing.

### Step 4: Pre-Sync Validation (MANDATORY GATE)

**Before syncing, validate that every skill's CHANGELOG matches its version.** This catches the common failure where SKILL.md version is bumped but CHANGELOG.md is not updated.

```bash
SCRIPTS=~/.claude/skills/skill-publishing/scripts
MONOREPO_DIR="${HOME}/dev/claude-code-skills"

# GATE: Validate all skill CHANGELOGs match their SKILL.md versions
$SCRIPTS/validate-pre-sync.sh $MONOREPO_DIR
```

**If validation fails (exit code 1):** STOP. Do not proceed to sync. Fix each failing skill:
1. Open the skill's `CHANGELOG.md`
2. Add a `## [X.Y.Z] - YYYY-MM-DD` entry describing what changed
3. Re-run validation until it passes

**This gate is non-negotiable.** The monorepo must never receive a skill whose CHANGELOG is behind its version.

### Step 5: Auto-Sync to Monorepo

**When any Monorepo or Plugin target is selected, automatically sync and push.** Do NOT leave this as a manual step — the user expects publishing to be end-to-end.

`sync-monorepo.sh` automatically handles both bare skills and plugins:
- Skills **with** `plugin-manifest.json` → auto-assembled via `prepare-plugin.sh` and synced to `plugins/`
- Skills **without** manifest → synced as bare directories at monorepo root

```bash
# 1. Sync all skills + auto-build plugins (single command does both)
$SCRIPTS/sync-monorepo.sh $MONOREPO_DIR

# 2. Commit and push
cd $MONOREPO_DIR
git add -A
CHANGED=$(git diff --cached --stat)
if [[ -n "$CHANGED" ]]; then
  git commit -m "Sync skills ($(date +%Y-%m-%d))"
  git push origin main
fi
```

**Important**: The `prevent-direct-push` hook in some projects blocks `git push origin main` via Claude. If push is blocked, instruct the user to push manually from their terminal:
```
cd ~/dev/claude-code-skills && git push origin main
```

### Step 6: Monorepo Release (MANDATORY)

**After every sync that changes skill content, ALWAYS create a monorepo release.** Do NOT ask whether to release — just do it.

```bash
# Determine bump level from what changed:
#   - patch: typo fixes, sync-only updates, no SKILL.md changes
#   - minor: skill version bumps, new features, new scripts
#   - major: new skill added, skill removed, breaking structure changes
$SCRIPTS/release-monorepo.sh <patch|minor|major> $MONOREPO_DIR
```

**Bump level decision:**
| What Changed | Bump |
|---|---|
| Skill version bumped (e.g., v2.3.0 → v2.4.0) | `minor` |
| New skill added to monorepo | `minor` |
| Plugin added or restructured | `minor` |
| Typo/wording fixes only, no version changes | `patch` |
| Skill removed or breaking layout change | `major` |

### Step 7: Post-Publish

After all targets are processed:
1. Clean up build artifacts: `rm -rf ~/.claude/skills/skill-publishing/build/`
2. Report summary of what was published/synced/released

**Summary must include:**
- Skills synced (with version numbers)
- Monorepo release version created
- Individual repos updated (if any)
- Any validation failures that were fixed

---

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

## Workflow E: Publish a Plugin (Manual Fallback)

> **Note:** For skills that already have a `plugin-manifest.json`, `sync-monorepo.sh`
> auto-builds and syncs the plugin. Use this manual workflow only for first-time setup,
> debugging, or when you need to control the build/validate cycle explicitly.

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
| **Plugin-first default** | Manifest → plugin | Plugins are the installable unit; bare skills are for simple cases without commands/agents |
| **Auto-assemble on sync** | `sync-monorepo.sh` builds plugins | Eliminates manual `prepare-plugin.sh` + `--add-plugin` for known plugins |
| `.claude/` in `.gitignore` | Always | Contains `settings.local.json` with user-specific permissions |
| License | MIT default | Most permissive, standard for open-source tools |
| Version from frontmatter | Use as-is | Avoids version mismatch between SKILL.md and tag |
| Flat copy, not subtree | By design | Simpler mental model; local dir is single source of truth |
| Monorepo README | Auto-generated | Catalog table derived from SKILL.md frontmatter; never hand-edit |
| Plugins in `plugins/` subfolder | By design | Different structure than bare skills; separates concerns |
| Plugin build manifest (JSON) | `jq` dependency | Plugins bundle multiple sources; CLI-only would be unwieldy |
| `install-plugin.sh` in monorepo | Consumer-facing | Users need it to install plugins; not just an author tool |

## See Also

- `skill-authoring` — how to structure and write skills (the content)
- This skill handles the distribution packaging (the container)
- **GitHub**: https://github.com/abhattacherjee/claude-code-skills/tree/main/skill-publishing — install instructions, changelog, license
