---
allowed-tools: Bash(git:*), Read, Edit, Write
argument-hint: <version>
description: Create a new Git Flow release branch from develop with version bumping and changelog generation
---

# Git Flow Release Branch

Create new release branch: **$ARGUMENTS**

## Current Repository State

- Current branch: !`git branch --show-current`
- Git status: !`git status --porcelain`
- Latest tag: !`git describe --tags --abbrev=0 2>/dev/null || echo "No tags found"`
- Commits since last tag: !`git log $(git describe --tags --abbrev=0 2>/dev/null)..HEAD --oneline 2>/dev/null | wc -l | tr -d ' '`
- Package.json version: !`cat package.json 2>/dev/null | grep '"version"' | head -1 || echo "No package.json found"`
- Recent commits: !`git log --oneline -10`

## Task

Create a Git Flow release branch following these steps:

### 1. Version Validation

Validate the version format and ensure it's newer than current:

- Must follow semantic versioning: `vMAJOR.MINOR.PATCH`
- Examples: `v1.0.0`, `v2.1.3`, `v0.5.0-beta.1`

**Version Increment Logic** (analyze commits since last tag):
- **MAJOR** (v2.0.0): Breaking changes (`BREAKING CHANGE:` in commits)
- **MINOR** (v1.3.0): New features (`feat:` commits)
- **PATCH** (v1.2.1): Bug fixes only (`fix:` commits)

See the `git-flow` skill for the full semver selection guide.

### 2. Create Release Branch

```bash
# Switch to develop and update
git checkout develop
git pull origin develop

# Create release branch
git checkout -b release/$ARGUMENTS

# Update package.json version (if Node.js project)
npm version ${ARGUMENTS#v} --no-git-tag-version

# Commit version bump
git add package.json CHANGELOG.md
git commit -m "chore(release): bump version to ${ARGUMENTS#v}

Co-Authored-By: Claude <noreply@anthropic.com>"

# Push to remote with tracking
git push -u origin release/$ARGUMENTS
```

### 3. CHANGELOG Generation

Generate changelog from commits since last tag, grouped by type:

```markdown
## [$ARGUMENTS] - [Current Date]

### Added
- [feat: commits]

### Fixed
- [fix: commits]

### Changed
- [refactor:/perf:/chore: commits]

### Documentation
- [docs: commits]
```

### 4. Success Response

```
Release Branch Ready: $ARGUMENTS

Branch: release/$ARGUMENTS
Base: develop
Target: main (after review)

Next Steps:
1. Review CHANGELOG.md for accuracy
2. Run final tests
3. Create PR to main: gh pr create --base main
4. Get team approvals
5. Run /finish to complete release (or /finalize-release if available)

Release Tips:
- No new features on release branch — bug fixes only
- Keep release branch short-lived
- Tag will be created when merged to main
```

### 5. Error Handling

**No Version Provided:**
```
Version is required

Usage: /release <version>

Examples:
  /release v1.2.0
  /release v2.0.0-beta.1

Current version: [from git describe]
Suggested version: [based on commit analysis]
```

**Invalid Version Format:**
```
Invalid version format: "$ARGUMENTS"

Correct format: vMAJOR.MINOR.PATCH (must start with 'v')
```

**Uncommitted Changes:**
```
Uncommitted changes detected. Commit or stash first.
```

## Related Commands

- `/finish` — Complete release (merge to main and develop, create tag)
- `/finalize-release` — Ship release with parallel artifact generation (project-specific)
- `/flow-status` — Check current Git Flow status
- `/feature <name>` — Create feature branch
- `/hotfix` — Create hotfix branch from main
- `git-flow` skill — Branching model reference, conventions, and diagnostic script
