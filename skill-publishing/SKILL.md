---
name: skill-publishing
description: "Makes any Claude Code skill shareable on GitHub by adding README, LICENSE, CHANGELOG, .gitignore, initializing a git repo, and pushing to GitHub. Supports individual repos, a monorepo (claude-code-skills), and versioned monorepo releases with semver tags. Use when: (1) a skill directory needs to be published to GitHub, (2) user wants to make a skill installable by others, (3) user says 'share this skill' or 'publish skill to GitHub', (4) preparing a skill for open-source distribution, (5) syncing skills to the monorepo, (6) user says 'sync skills' or 'update monorepo', (7) creating a versioned monorepo release with tag."
metadata:
  version: 2.1.0
---

# Skill to GitHub

Converts local Claude Code skill directories into shareable GitHub repositories.
Supports two distribution models: **individual repos** and a **monorepo** (`claude-code-skills`).

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
```

## Architecture

```
~/.claude/skills/              (SOURCE OF RECORD)
├── conversation-search/
├── skill-authoring/
├── skill-publishing/
└── ...

Individual repos:              (each skill has its own GitHub repo)
├── github.com/USER/conversation-search
├── github.com/USER/skill-authoring
└── github.com/USER/skill-publishing

Monorepo:                      (all skills in one repo)
└── github.com/USER/claude-code-skills
    ├── README.md              (auto-generated catalog table)
    ├── conversation-search/
    ├── skill-authoring/
    └── skill-publishing/
```

**Key principle**: `~/.claude/skills/` is the single source of truth. Both individual repos and the monorepo are derived from it via flat-copy (no git subtrees).

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

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `.claude/` in `.gitignore` | Always | Contains `settings.local.json` with user-specific permissions |
| License | MIT default | Most permissive, standard for open-source tools |
| Version from frontmatter | Use as-is | Avoids version mismatch between SKILL.md and tag |
| No install script | By design | `git clone` IS the installer — no extra ceremony |
| Flat copy, not subtree | By design | Simpler mental model; local dir is single source of truth |
| Monorepo README | Auto-generated | Catalog table derived from SKILL.md frontmatter; never hand-edit |

## See Also

- `skill-authoring` — how to structure and write skills (the content)
- This skill handles the distribution packaging (the container)
- **GitHub**: https://github.com/abhattacherjee/skill-publishing — install instructions, changelog, license
