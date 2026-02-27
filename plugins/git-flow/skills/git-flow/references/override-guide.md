# Git Flow Command Override Guide

How the two-tier command system works, what to override, and how to write overrides.

## Table of Contents

- [How Resolution Works](#how-resolution-works)
- [Generic Commands Reference](#generic-commands-reference)
- [Why Override](#why-override)
- [Override Patterns](#override-patterns)
- [Writing an Override](#writing-an-override)
- [Override Checklist](#override-checklist)

---

## How Resolution Works

Claude Code resolves `/command` names in this order:

```
1. Project:  .claude/commands/<name>.md       ← checked first
2. User:     ~/.claude/commands/<name>.md      ← fallback
```

**Key behaviors:**
- Project-level **fully replaces** user-level (no merging, no inheritance)
- If only user-level exists, it runs everywhere (any Git Flow repo)
- If both exist, only the project version runs — user version is invisible
- Skills (`.claude/skills/`) are separate — they activate by description matching,
  not by command name. The `git-flow` skill is always available regardless of overrides.

```
~/.claude/
├── commands/              ← Generic commands (work in any repo)
│   ├── feature.md
│   ├── release.md
│   ├── hotfix.md
│   ├── finish.md
│   └── flow-status.md
└── skills/
    └── git-flow/          ← Reference skill (always available)
        ├── SKILL.md
        └── scripts/
            └── git-flow-status.sh

<project>/
└── .claude/
    └── commands/          ← Project overrides (take precedence)
        ├── hotfix.md      ← Overrides ~/.claude/commands/hotfix.md
        ├── finish.md      ← Overrides ~/.claude/commands/finish.md
        └── finalize-release.md  ← Project-only (no user-level equivalent)
```

---

## Generic Commands Reference

Each generic command provides standard Git Flow operations that work in any repo
with a single `package.json` and no push restrictions.

### `/feature <name>` (124 lines)

**What it does:** Creates a feature branch from develop.

| Step | Action |
|------|--------|
| Pre-flight | Clean working dir, develop exists |
| Create | `git checkout -b feature/<name>` from develop |
| Push | `git push -u origin feature/<name>` |
| Report | Branch info + next steps |

**Override surface:** Rarely needed. Override if your project has naming conventions
beyond kebab-case (e.g., ticket prefixes like `feature/JIRA-123-description`).

### `/release <version>` (138 lines)

**What it does:** Creates a release branch from develop with version bumping.

| Step | Action |
|------|--------|
| Validate | Semver format, newer than current |
| Create | `git checkout -b release/<version>` from develop |
| Bump | `npm version <ver> --no-git-tag-version` (single package.json) |
| Changelog | Generate grouped changelog from commits |
| Push | `git push -u origin release/<version>` |

**Override surface:** Override if you have:
- Multiple `package.json` files (monorepo)
- Non-npm version files (e.g., `pyproject.toml`, `Cargo.toml`, `pom.xml`)
- Custom changelog format or tooling (e.g., `conventional-changelog`)
- Additional release prep steps (lock file regeneration, asset builds)

### `/hotfix` (108 lines)

**What it does:** Creates a hotfix branch from main, auto-computing the next patch version.

| Step | Action |
|------|--------|
| Compute | Next patch from latest tag on main (v1.2.0 → v1.2.1) |
| Create | `git checkout -b hotfix/<version>` from main |
| Bump | `npm version <ver> --no-git-tag-version` (single package.json) |
| Push | `git push -u origin hotfix/<version>` |

**Override surface:** Override if you have:
- Multiple `package.json` files (monorepo) — most common reason
- Non-npm version files
- Release finalization tooling (e.g., `/finalize-release` integration)
- Additional next-steps guidance specific to your deploy pipeline

### `/finish [--no-delete] [--no-tag]` (122 lines)

**What it does:** Completes the current Git Flow branch by merging to target(s).

| Branch Type | Merge To | Tag | Cleanup |
|-------------|----------|-----|---------|
| feature/* | develop | No | Delete branch |
| release/* | main + develop | Yes | Delete branch |
| hotfix/* | main + develop | Yes | Delete branch |

**Override surface:** Override if you have:
- Push hooks blocking direct pushes to main/develop (most common reason)
- A finish script that handles merges automatically (`git-flow-finish.sh`)
- Custom merge commit message format
- Post-merge automation (deploy triggers, notification hooks)
- A `/finalize-release` command that should be preferred for release/hotfix

### `/flow-status` (40 lines)

**What it does:** Delegates to `git-flow-status.sh` for a comprehensive diagnostic,
then adds branch-specific guidance.

**Override surface:** Almost never needed. The script is already portable. Override
only if your project has custom branch types beyond the standard Git Flow set.

---

## Why Override

### Monorepo Version Bumping

Generic commands run `npm version` once (root `package.json`). Monorepos need
all packages bumped in lockstep:

```bash
# Generic (single package)
npm version "1.2.1" --no-git-tag-version

# Override (monorepo with 3 packages)
cd backend && npm version "1.2.1" --no-git-tag-version && cd ..
cd frontend && npm version "1.2.1" --no-git-tag-version && cd ..
cd mcp-events-server && npm version "1.2.1" --no-git-tag-version && cd ..
```

**Affects:** `/hotfix`, `/release`

### Push Hook Workarounds

Some projects have pre-push hooks (e.g., `prevent-direct-push.py`) that block
`git push origin main` and `git push origin develop`. The workaround pushes to
a temporary branch, then updates the protected ref via GitHub API:

```bash
# Blocked:
git push origin develop

# Workaround:
git push origin develop:refs/heads/temp-finish-xxx
gh api repos/{owner}/{repo}/git/refs/heads/develop \
  -X PATCH -F sha="$(git rev-parse HEAD)" -F force=false
gh api repos/{owner}/{repo}/git/refs/heads/temp-finish-xxx -X DELETE
```

**Critical:** Use `-F` (typed) not `-f` (string) for boolean parameters in `gh api`.

**Affects:** `/finish`

### Release Finalization Pipeline

Some projects have a `/finalize-release` command that orchestrates parallel
artifact generation (changelog, release notes, README updates) before running
the finish. The project's `/finish` override should recommend `/finalize-release`
for release/hotfix branches.

**Affects:** `/finish` (documentation/guidance), `/finalize-release` (project-only)

### Non-npm Ecosystems

For Python, Rust, Java, or other ecosystems, override the version bump step:

```bash
# Python (pyproject.toml)
sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml

# Rust (Cargo.toml)
sed -i "s/^version = .*/version = \"$VERSION\"/" Cargo.toml
```

**Affects:** `/hotfix`, `/release`

---

## Override Patterns

### Pattern 1: Minimal Override (add project-specific steps)

Override a single aspect while keeping the same structure. Self-contained but
includes all steps since user-level is fully replaced.

```markdown
---
allowed-tools: Bash(git:*), Read, Edit, Write
argument-hint: [description]
description: Create a new Git Flow hotfix branch from main with auto-versioning,
  bump all package.json files, and set up for finalization
---

# Git Flow Hotfix Branch (Project Override)

This overrides the generic `/hotfix` with monorepo version bumping.

[... all steps including the project-specific bump ...]
```

### Pattern 2: Script Delegation (for complex finish logic)

When the project has a finish script, the override becomes thin — just branch
detection and delegation:

```markdown
# Git Flow Finish Branch (Project Override)

### Release/Hotfix → Use the script or /finalize-release

.claude/skills/release-and-git-flow/scripts/git-flow-finish.sh <type> <version>

### Feature → Manual merge with push workaround

[... only feature-specific steps ...]
```

### Pattern 3: Project-Only Command (no user-level equivalent)

Commands like `/finalize-release` that only make sense for a specific project.
No user-level file needed — just place in `.claude/commands/`.

---

## Writing an Override

### Step 1: Identify what's project-specific

Read the generic command at `~/.claude/commands/<name>.md` and identify which
steps need modification. Common touch points:

| Generic Step | Project Override Reason |
|-------------|----------------------|
| `npm version` (single) | Monorepo: bump N packages |
| `git push origin <target>` | Push hook: add workaround |
| Success message / next steps | Reference project tooling |
| Pre-flight checks | Additional project validations |

### Step 2: Copy frontmatter, adjust allowed-tools

Start with the generic frontmatter and add any additional tools needed:

```yaml
# Generic
allowed-tools: Bash(git:*)

# Override might need
allowed-tools: Bash(git:*), Bash(npm test:*), Bash(test:*), Read, Edit
```

### Step 3: Write self-contained override

Since overrides fully replace the generic version, include ALL steps — not just
the changed parts. But keep it focused:

- **Label it clearly**: `# Git Flow <Command> (Project Override)` at the top
- **Comment project-specific sections**: `# PROJECT-SPECIFIC: Bump ALL three packages`
- **Reference scripts**: Don't duplicate script logic; point to the script
- **Link back to skill**: `See git-flow skill for branching model reference`

### Step 4: Test resolution

Verify the override takes precedence:

```bash
# Should show project version, not user version
head -10 .claude/commands/<name>.md

# Verify both exist
ls -la ~/.claude/commands/<name>.md .claude/commands/<name>.md
```

---

## Override Checklist

Before committing a project override:

- [ ] Frontmatter has `description`, `allowed-tools`, `argument-hint`
- [ ] File is self-contained (doesn't rely on user-level version for missing steps)
- [ ] Clearly labeled as "Project Override" in the title
- [ ] Project-specific sections are commented
- [ ] References `git-flow` skill for shared knowledge (branching model, semver, etc.)
- [ ] Related Commands section includes project-specific commands (e.g., `/finalize-release`)
- [ ] Error handling covers project-specific failure modes
- [ ] Tested: command resolves from project level, not user level
