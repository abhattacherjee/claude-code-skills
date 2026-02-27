---
allowed-tools: Bash(git:*)
argument-hint: <feature-name>
description: Create a new Git Flow feature branch from develop with proper naming and tracking
---

# Git Flow Feature Branch

Create new feature branch: **$ARGUMENTS**

## Current Repository State

- Current branch: !`git branch --show-current`
- Git status: !`git status --porcelain`
- Develop branch status: !`git log develop..origin/develop --oneline 2>/dev/null | head -5 || echo "No remote tracking for develop"`

## Task

Create a Git Flow feature branch following these steps:

### 1. Pre-Flight Validation

- **Check git repository**: Verify we're in a valid git repository
- **Validate feature name**: Ensure `$ARGUMENTS` is provided and follows naming conventions:
  - Valid: `user-authentication`, `payment-integration`, `dashboard-redesign`
  - Invalid: `feat1`, `My_Feature`, empty name
- **Check for uncommitted changes**:
  - If changes exist, warn user and ask to commit/stash first
  - OR offer to stash changes automatically
- **Verify develop branch exists**: Ensure `develop` branch is present

### 2. Create Feature Branch

```bash
# Switch to develop branch
git checkout develop

# Pull latest changes from remote
git pull origin develop

# Create feature branch with Git Flow naming convention
git checkout -b feature/$ARGUMENTS

# Set up remote tracking
git push -u origin feature/$ARGUMENTS
```

### 3. Provide Status Report

After successful creation, display:

```
Feature Branch Ready

Branch: feature/$ARGUMENTS
Base: develop
Status: Clean working directory

Next Steps:
1. Start implementing your feature
2. Make commits using conventional format:
   git commit -m "feat: your changes"
3. Push changes regularly: git push
4. When complete, use /finish to merge back to develop
```

### 4. Error Handling

**Feature Name Not Provided:**
```
Feature name is required

Usage: /feature <feature-name>

Examples:
  /feature user-profile-page
  /feature api-v2-integration

Feature names should be kebab-case and descriptive.
```

**Branch Already Exists:**
```
Branch feature/$ARGUMENTS already exists

Options:
1. Switch to existing branch: git checkout feature/$ARGUMENTS
2. Use a different feature name
3. Delete existing and recreate (destructive!)
```

**Uncommitted Changes:**
```
You have uncommitted changes:
[list files]

Options:
1. Commit changes first
2. Stash changes: git stash
3. Discard changes: git checkout .
```

**No Develop Branch:**
```
Develop branch not found

Git Flow requires a 'develop' branch. Create it with:
  git checkout -b develop
  git push -u origin develop
```

## Git Flow Context

See the `git-flow` skill for the full branching model, conventions, and gotchas.

Feature branches: develop -> `feature/<name>` -> develop (no tag). Use `/finish` to merge.

## Related Commands

- `/finish` — Complete and merge feature branch to develop
- `/flow-status` — Check current Git Flow status
- `/release <version>` — Create release branch from develop
- `/hotfix` — Create hotfix branch from main
- `git-flow` skill — Branching model reference, conventions, and diagnostic script
