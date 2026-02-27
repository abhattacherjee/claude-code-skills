---
name: git-flow
description: "Git Flow branching workflow reference and status diagnostic. Use when: (1) /flow-status or checking repository state, (2) creating feature/release/hotfix branches, (3) finishing and merging Git Flow branches, (4) understanding Git Flow conventions in any repository, (5) setting up or overriding Git Flow commands for a new project."
metadata:
  version: 2.0.0
---

# Git Flow

Reference guide and diagnostic for the Git Flow branching model. Provides generic
commands that work in any repo, with a two-tier override system for project-specific
customization.

## Quick Check

```bash
~/.claude/skills/git-flow/scripts/git-flow-status.sh            # Human-readable
~/.claude/skills/git-flow/scripts/git-flow-status.sh --json     # For agent consumption
~/.claude/skills/git-flow/scripts/git-flow-status.sh --help     # Usage
```

## Branching Model

```
main ──────────────────────────────────────────────► (production, tagged releases)
  │                     ▲           ▲
  │                     │           │
  │              release/v1.3.0  hotfix/v1.2.1
  │                     ▲           │
  │                     │           │
  └──► develop ─────────┴───────────┴──────────────► (integration)
         │         ▲
         │         │
         └──► feature/my-feature
```

| Branch Type | Branches From | Merges To | Tag? | Purpose |
|-------------|--------------|-----------|------|---------|
| `feature/*` | develop | develop | No | New functionality |
| `release/*` | develop | main + develop | Yes | Release preparation |
| `hotfix/*` | main | main + develop | Yes | Emergency production fix |

## Two-Tier Command Architecture

### How It Works

```
Resolution order:
  1. .claude/commands/<name>.md       ← Project (checked first)
  2. ~/.claude/commands/<name>.md      ← User (fallback)
```

Generic commands at `~/.claude/commands/` work in any Git Flow repo:
- `/feature`, `/release`, `/hotfix`, `/finish`, `/flow-status`

Projects override by placing a same-name file in `.claude/commands/`.
**Overrides fully replace** the user-level version (no merging, no inheritance).

### What Each Generic Command Provides

| Command | Generic Behavior | Override When |
|---------|-----------------|---------------|
| `/feature <name>` | Branch from develop, push | Custom naming conventions |
| `/release <version>` | Branch, single `npm version`, changelog | Monorepo, non-npm, custom changelog |
| `/hotfix` | Auto-patch from main tag, single `npm version` | Monorepo, release pipeline integration |
| `/finish` | Merge to target(s), tag, cleanup | Push hooks, finish scripts, deploy triggers |
| `/flow-status` | Delegates to `git-flow-status.sh` | Custom branch types (rare) |

### Common Override Reasons

| Reason | Affects | Example |
|--------|---------|---------|
| **Monorepo** — multiple package files | `/hotfix`, `/release` | Bump 3 `package.json` in lockstep |
| **Push hooks** — blocking direct pushes | `/finish` | Temp-branch + `gh api` workaround |
| **Release pipeline** — parallel artifacts | `/finish` | Recommend `/finalize-release` instead |
| **Non-npm** — Python, Rust, Java | `/hotfix`, `/release` | `pyproject.toml`, `Cargo.toml` |
| **Naming conventions** — ticket prefixes | `/feature` | `feature/JIRA-123-description` |

See **[references/override-guide.md](references/override-guide.md)** for the complete
override guide: resolution mechanics, per-command override surface, patterns, and checklist.

## Command Decision Table

| Situation | Command | What It Does |
|-----------|---------|-------------|
| Start new work | `/feature <name>` | Branch from develop, push with tracking |
| Prepare a release | `/release <version>` | Branch from develop, bump versions, update changelog |
| Emergency production fix | `/hotfix` | Branch from main, auto-increment patch version |
| Done with current branch | `/finish` | Merge to target(s), tag if release/hotfix, cleanup |
| Ship release with artifacts | `/finalize-release` | Parallel doc generation + `/finish` (project-specific) |
| Check repo state | `/flow-status` | Branch type, sync, active branches, recommendations |

### Key Rules

- **Feature names**: kebab-case, descriptive (`user-authentication`, not `feat1`)
- **PRs always target develop**, never main
- **Release branches**: only bug fixes allowed after creation, no new features
- **Hotfix vs feature**: hotfix = production broken / security / data loss; feature = everything else
- **`--no-ff` always**: merge commits preserve branch history in the graph
- **Pre-merge checks**: clean working dir, all pushed, no conflicts with target

### `/finish` Merge Targets

| Branch Type | Merge To | Tag | Delete Branch |
|-------------|----------|-----|---------------|
| feature/* | develop | No | Yes |
| release/* | main + develop | Yes (version) | Yes |
| hotfix/* | main + develop | Yes (version) | Yes |

### Semver Version Selection

When creating release branches, choose the version increment:
- **MAJOR** (v2.0.0): Breaking changes (`BREAKING CHANGE:` in commits)
- **MINOR** (v1.3.0): New features (`feat:` commits since last tag)
- **PATCH** (v1.2.1): Bug fixes only (`fix:` commits)

## Common Workflows

### Feature Development
```
1. /feature user-auth          # Create branch
2. [implement, commit, push]   # Developer work
3. gh pr create --base develop  # Create PR
4. [review, CI]                # PR review
5. /finish                     # Merge to develop
```

### Planned Release
```
1. /release v1.3.0             # Create release branch
2. [bug fixes only]            # Stabilize
3. /finalize-release           # Artifacts + merge + tag + cleanup
```

### Emergency Hotfix
```
1. /hotfix                     # Auto-version from main
2. [minimal fix + tests]       # Fix the issue
3. /finalize-release           # Merge to main + tag + sync develop
```

### New Project Setup
```
1. Verify generic commands:    ls ~/.claude/commands/
2. Test: /flow-status          # Should work immediately
3. Identify override needs:    Does the project have monorepo? Push hooks?
4. Create overrides:           See references/override-guide.md
```

## Gotchas

### Squash-merged branches need force-delete
After a squash-merge PR, `git branch -d` fails with "not fully merged" because the
original commits aren't in the target. Use `git branch -D` after verifying the PR
was merged (check `gh pr list --state all --head <branch>`).

### Stale worktrees block checkout
If `git checkout develop` fails with "already used by worktree", run:
```bash
git worktree prune   # Clean stale references to deleted worktree directories
```

### `--no-ff` is critical
Always use `--no-ff` (no fast-forward) for merge commits. This preserves branch
history in the graph, making it clear where features started and ended:
```bash
git merge --no-ff feature/x    # Creates merge commit (good)
git merge feature/x            # May fast-forward (loses history)
```

### Tag filtering for semver
`git describe --tags --abbrev=0` picks up ANY tag. For version detection, filter:
```bash
git tag -l 'v[0-9]*' --sort=-v:refname | head -1   # Only semver tags
```

### Push hooks may block direct pushes
Some repos have pre-push hooks that block pushes to main/develop. If blocked,
use the temp-branch + API ref patch workaround:
```bash
git push origin HEAD:refs/heads/temp-finish-xxx
COMMIT_SHA=$(git rev-parse HEAD)
gh api repos/{owner}/{repo}/git/refs/heads/<target> \
  -X PATCH -F sha="$COMMIT_SHA" -F force=false
gh api repos/{owner}/{repo}/git/refs/heads/temp-finish-xxx -X DELETE
```
**Critical:** Use `-F` (typed) not `-f` (string) for `gh api` boolean parameters.

### `grep -c` in bash scripts returns exit 1 on zero matches
`grep -c pattern` exits with status 1 when the count is 0 (even though it outputs "0").
Combined with `set -e`, this terminates the script. Fix: use a helper function:
```bash
count_lines() { if [[ -z "$1" ]]; then echo 0; else echo "$1" | wc -l | tr -d ' '; fi; }
```

### Hook validators may scan bash command text
Some projects have hooks that scan the raw text of bash commands for patterns
(e.g., branch names). Even text inside heredocs or echo statements can trigger
the validator. Use text-only output (not bash) for simulations containing
branch name patterns.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `GIT_FLOW_MAIN_BRANCH` | `main` | Production branch name |
| `GIT_FLOW_DEVELOP_BRANCH` | `develop` | Integration branch name |

## Directory Layout

```
~/.claude/skills/git-flow/
├── SKILL.md                          # This file — branching model, commands, gotchas
├── scripts/
│   └── git-flow-status.sh            # Portable diagnostic (any Git Flow repo)
└── references/
    └── override-guide.md             # How to write project-level command overrides

~/.claude/commands/                    # Generic commands (created by this skill)
├── feature.md                        # /feature <name>
├── release.md                        # /release <version>
├── hotfix.md                         # /hotfix
├── finish.md                         # /finish [--no-delete] [--no-tag]
└── flow-status.md                    # /flow-status
```

## See Also

- **[references/override-guide.md](references/override-guide.md)** — full override guide with patterns, per-command surface, and checklist
- `git-branch-cleanup` — audit and delete stale branches after merges
- `changelog-keeper` — generate CHANGELOG.md from commit history
- `release-and-git-flow` (project-level) — hook workarounds and release pipeline
