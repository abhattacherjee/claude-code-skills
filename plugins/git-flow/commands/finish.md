---
allowed-tools: Bash(git:*), Bash(npm test:*), Read, Edit
argument-hint: [--no-delete] [--no-tag]
description: Complete and merge current Git Flow branch (feature/release/hotfix) with proper cleanup and tagging
---

# Git Flow Finish Branch

Complete current Git Flow branch: **$ARGUMENTS**

## Current Repository State

- Current branch: !`git branch --show-current`
- Branch type: !`git branch --show-current | grep -oE '^(feature|release|hotfix)' || echo "Not a Git Flow branch"`
- Git status: !`git status --porcelain`
- Unpushed commits: !`git log @{u}.. --oneline 2>/dev/null | wc -l | tr -d ' '`
- Latest tag: !`git describe --tags --abbrev=0 2>/dev/null || echo "No tags"`

## Task

Complete the current Git Flow branch by merging it to appropriate target branch(es).

### 1. Branch Type Detection

```bash
CURRENT_BRANCH=$(git branch --show-current)

if [[ $CURRENT_BRANCH == feature/* ]]; then
  BRANCH_TYPE="feature"
  MERGE_TO="develop"
  CREATE_TAG="no"
elif [[ $CURRENT_BRANCH == release/* ]]; then
  BRANCH_TYPE="release"
  MERGE_TO="main develop"
  CREATE_TAG="yes"
  TAG_NAME="${CURRENT_BRANCH#release/}"
elif [[ $CURRENT_BRANCH == hotfix/* ]]; then
  BRANCH_TYPE="hotfix"
  MERGE_TO="main develop"
  CREATE_TAG="yes"
  TAG_NAME="${CURRENT_BRANCH#hotfix/}"
else
  echo "Not on a Git Flow branch (feature/release/hotfix)"
  exit 1
fi
```

### 2. Pre-Merge Validation

- All changes committed (clean working directory)
- All commits pushed to remote
- No merge conflicts with target branch(es)

### 3. Feature Branch Finish

```bash
git push
git checkout develop
git pull origin develop
git merge --no-ff feature/$NAME -m "Merge feature/$NAME into develop

$(git log develop..feature/$NAME --oneline)

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin develop
git branch -d feature/$NAME
git push origin --delete feature/$NAME
```

### 4. Release Branch Finish

```bash
VERSION="${CURRENT_BRANCH#release/}"
git push

# Merge to main
git checkout main
git pull origin main
git merge --no-ff release/$VERSION -m "Merge release/$VERSION into main

Co-Authored-By: Claude <noreply@anthropic.com>"

# Tag (unless --no-tag)
git tag -a $VERSION -m "Release $VERSION"
git push origin main --tags

# Merge back to develop
git checkout develop
git pull origin develop
git merge --no-ff release/$VERSION -m "Merge release/$VERSION back into develop

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin develop

# Cleanup (unless --no-delete)
git branch -d release/$VERSION
git push origin --delete release/$VERSION
```

### 5. Hotfix Branch Finish

Same as release finish but uses hotfix branch name. The tag is the hotfix version (already set on the branch).

### 6. Error Handling

**Not on Git Flow Branch:** Guide user to correct branch.
**Uncommitted Changes:** Ask to commit/stash.
**Unpushed Commits:** Offer to push.
**Merge Conflicts:** Show conflicting files and resolution steps.

### 7. Arguments

- `--no-delete` — Keep branch after merging
- `--no-tag` — Skip tag creation (release/hotfix only)

## Related Commands

- `/feature <name>` — Start new feature branch
- `/release <version>` — Start new release branch
- `/hotfix` — Start new hotfix branch from main
- `/flow-status` — Check Git Flow status
- `git-flow` skill — Branching model reference, merge targets, and diagnostic script
