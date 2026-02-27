---
allowed-tools: Bash(git:*), Read, Edit, Write
argument-hint: [description]
description: Create a new Git Flow hotfix branch from main with auto-versioning
---

# Git Flow Hotfix Branch

Create hotfix branch from main: **$ARGUMENTS**

## Current Repository State

- Current branch: !`git branch --show-current`
- Git status: !`git status --porcelain`
- Latest production tag: !`git describe --tags --abbrev=0 origin/main 2>/dev/null || echo "No tags on main"`
- Main branch status: !`git log main..origin/main --oneline 2>/dev/null | head -3 || echo "In sync"`

## Task

### 1. Pre-Flight Validation

- Verify clean working directory
- Verify main branch exists and is up to date

**Hotfixes are for:** Critical security vulnerabilities, production-breaking bugs,
payment/transaction failures, data loss or corruption.

**NOT for:** Regular bug fixes, features, performance (use `/feature` instead).

### 2. Compute Hotfix Version

```bash
git fetch origin main --tags

LATEST_TAG=$(git describe --tags --abbrev=0 origin/main 2>/dev/null)
if [ -z "$LATEST_TAG" ]; then
  echo "ERROR: No tags found on main."
  exit 1
fi

VERSION_BASE="${LATEST_TAG#v}"
MAJOR=$(echo "$VERSION_BASE" | cut -d. -f1)
MINOR=$(echo "$VERSION_BASE" | cut -d. -f2)
PATCH=$(echo "$VERSION_BASE" | cut -d. -f3)
NEXT_PATCH=$((PATCH + 1))
HOTFIX_VERSION="v${MAJOR}.${MINOR}.${NEXT_PATCH}"
```

### 3. Create Hotfix Branch

```bash
git checkout main
git pull origin main

git checkout -b "hotfix/$HOTFIX_VERSION"

# Bump version in package.json (root-level)
npm version "${HOTFIX_VERSION#v}" --no-git-tag-version

git add package.json
git commit -m "chore(hotfix): bump version to ${HOTFIX_VERSION#v}

Co-Authored-By: Claude <noreply@anthropic.com>"

git push -u origin "hotfix/$HOTFIX_VERSION"
```

### 4. Success Response

```
Hotfix Branch Ready: hotfix/$HOTFIX_VERSION

  Branch:    hotfix/$HOTFIX_VERSION
  Base:      main ($LATEST_TAG)
  Version:   $HOTFIX_VERSION
  Merges to: main (tagged) + develop (merge back)

  Next Steps:
  1. Implement the fix (MINIMAL changes only)
  2. Add tests to prevent regression
  3. Commit and push your changes
  4. Run /finish to merge to main + develop with tag
```

### 5. Error Handling

**No Tags on Main:**
```
Cannot compute hotfix version: no tags found on main.

Create an initial tag first:
  git tag -a v1.0.0 -m "Initial release" origin/main
  git push origin v1.0.0
```

**Uncommitted Changes:**
```
Cannot create hotfix: uncommitted changes detected.
Commit, stash, or discard first.
```

## Related Commands

- `/finish` — Merge hotfix to main + develop with tag
- `/flow-status` — Check current Git Flow status
- `/feature <name>` — For non-critical fixes
- `/release <version>` — For planned releases from develop
- `git-flow` skill — Branching model reference, conventions, and diagnostic script
