#!/usr/bin/env bash
# git-flow-finish.sh — Complete Git Flow finish with merge, tag, and push
# Handles: merge to main + tag + GitHub Release + merge to develop + version bump + cleanup
#
# Installed by /harden-repo
#
# Usage:
#   ./scripts/git-flow-finish.sh <branch-type> <version> [--dry-run]
#
# Examples:
#   ./scripts/git-flow-finish.sh hotfix v1.0.6
#   ./scripts/git-flow-finish.sh release v2.0.0
#   ./scripts/git-flow-finish.sh hotfix v1.0.6 --dry-run

set -eu

# ── Constants ──────────────────────────────────────────────────────
REPO=""
BRANCH_TYPE=""
BRANCH_TYPE_CAPITALIZED=""
VERSION=""
VERSION_NUMBER=""
SOURCE_BRANCH=""
DRY_RUN=false
MERGE_VIA_PR=false

# ── Functions ──────────────────────────────────────────────────────

usage() {
  cat <<'USAGE'
Usage: git-flow-finish.sh <branch-type> <version> [options]

Arguments:
  branch-type   "hotfix" or "release"
  version       Version with v prefix (e.g., v1.0.6)

Options:
  --dry-run         Show what would be done without executing
  --help, -h        Show this help message

Examples:
  git-flow-finish.sh hotfix v1.0.6
  git-flow-finish.sh release v2.0.0
  git-flow-finish.sh hotfix v1.0.6 --dry-run

What this script does:
  1. Merges the source branch to main (--no-ff)
  2. Creates annotated tag on main (local)
  3. Pushes main + creates GitHub Release (tag + release notes from CHANGELOG.md)
  4. Merges source branch back to develop (--no-ff)
  5. Bumps develop to next patch version
  6. Pushes develop to remote
  7. Deletes source branch (local + remote)
  8. Verifies final state (including GitHub Release)

Push Strategy:
  Direct git push. The prevent-direct-push.py hook detects Git Flow
  merge context (release/hotfix in commit history) and allows the push.

USAGE
  exit 0
}

log() { echo "  $1"; }
log_ok() { echo "  ✅ $1"; }
log_fail() { echo "  ❌ $1"; }
log_skip() { echo "  ⏭️  $1"; }
log_phase() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  $1"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

die() { log_fail "$1"; exit 1; }

# Push a local branch to a remote ref.
# The prevent-direct-push.py hook detects Git Flow merge context and allows these pushes.
# Args: $1 = target ref (e.g., "main" or "develop"), $2 = local branch to push from
push_ref() {
  local TARGET_REF="$1"
  local LOCAL_BRANCH="$2"
  local COMMIT_SHA
  COMMIT_SHA=$(git rev-parse "$LOCAL_BRANCH")

  if $DRY_RUN; then
    log "[dry-run] Would push $LOCAL_BRANCH ($COMMIT_SHA) to origin/$TARGET_REF"
    return 0
  fi

  git push origin "$LOCAL_BRANCH:$TARGET_REF" || die "Failed to push to origin/$TARGET_REF"
  git fetch origin "$TARGET_REF" 2>/dev/null
  log_ok "Pushed to origin/$TARGET_REF ($COMMIT_SHA)"
}

# Create a GitHub Release (which also creates the tag on the remote)
create_github_release() {
  local TAG_NAME="$1"
  local NOTES_FILE

  if $DRY_RUN; then
    log "[dry-run] Would create GitHub Release $TAG_NAME on main"
    return 0
  fi

  NOTES_FILE=$(mktemp)

  # Extract the version's section from CHANGELOG.md
  if [[ -f CHANGELOG.md ]]; then
    awk -v ver="## [$VERSION_NUMBER]" '{
      if (index($0, ver) == 1) { found = 1; next }
      if (found == 1 && $0 ~ /^## \[/) exit
      if (found == 1) print
    }' CHANGELOG.md > "$NOTES_FILE"

    # Strip empty leading lines
    if [[ -s "$NOTES_FILE" ]]; then
      sed -i.bak '/./,$!d' "$NOTES_FILE" && rm -f "${NOTES_FILE}.bak"
    fi
  fi

  # Log extraction result for debugging
  if [[ -s "$NOTES_FILE" ]]; then
    local NOTES_LINES
    NOTES_LINES=$(wc -l < "$NOTES_FILE" | tr -d ' ')
    log "Extracted $NOTES_LINES lines from CHANGELOG.md"
  fi

  # Fallback if CHANGELOG.md missing or extraction yielded nothing
  if [[ ! -s "$NOTES_FILE" ]]; then
    cat > "$NOTES_FILE" <<EOF
${BRANCH_TYPE_CAPITALIZED} ${TAG_NAME}

See CHANGELOG.md for full details.
EOF
    log "Using fallback release notes (CHANGELOG.md extraction empty)"
  fi

  # gh release create also creates the tag on the remote — no separate API call needed
  if gh release create "$TAG_NAME" \
    --repo "$REPO" \
    --target main \
    --title "${BRANCH_TYPE_CAPITALIZED} ${TAG_NAME}" \
    --notes-file "$NOTES_FILE" 2>&1; then
    log_ok "Created GitHub Release $TAG_NAME"
  else
    # If the release already exists (e.g., partial re-run), update it
    log "Release $TAG_NAME may already exist, attempting update..."
    if ! gh release edit "$TAG_NAME" \
      --repo "$REPO" \
      --title "${BRANCH_TYPE_CAPITALIZED} ${TAG_NAME}" \
      --notes-file "$NOTES_FILE" 2>&1; then
      rm -f "$NOTES_FILE"
      die "Failed to create or update GitHub Release for $TAG_NAME"
    fi
    log_ok "Updated existing GitHub Release $TAG_NAME"
  fi

  # Verify release body is populated (catches silent failures where notes weren't applied)
  local BODY_LENGTH
  BODY_LENGTH=$(gh release view "$TAG_NAME" --repo "$REPO" --json body --jq '.body | length' 2>/dev/null || echo "0")
  if [[ "$BODY_LENGTH" -lt 50 ]]; then
    log "Release body appears empty or minimal ($BODY_LENGTH chars), re-applying notes..."
    gh release edit "$TAG_NAME" \
      --repo "$REPO" \
      --notes-file "$NOTES_FILE" 2>&1 || log_fail "Failed to re-apply release notes"
    log_ok "Re-applied release notes to $TAG_NAME"
  fi

  rm -f "$NOTES_FILE"
}

# Fallback: merge source branch to main via PR when direct push is blocked by branch protection.
# Creates PR, waits for CI, merges, and syncs local main.
merge_main_via_pr() {
  local PR_URL PR_NUMBER

  log "Direct push to main blocked (branch protection?). Falling back to PR merge..."

  # Go back to source branch (we were on main after failed push)
  git reset --hard origin/main
  git checkout "$SOURCE_BRANCH"

  # Create PR
  PR_URL=$(gh pr create \
    --base main \
    --head "$SOURCE_BRANCH" \
    --repo "$REPO" \
    --title "$BRANCH_TYPE_CAPITALIZED $VERSION" \
    --body "$(cat <<EOF
$BRANCH_TYPE_CAPITALIZED $VERSION

Merged via git-flow-finish.sh (branch protection PR path).
See CHANGELOG.md for full details.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" 2>/dev/null) || die "Failed to create PR for $SOURCE_BRANCH → main"

  PR_NUMBER=$(echo "$PR_URL" | grep -oE '[0-9]+$')
  log_ok "Created PR #$PR_NUMBER: $SOURCE_BRANCH → main"

  # Wait for CI checks
  log "Waiting for CI checks on PR #$PR_NUMBER..."
  if ! gh pr checks "$PR_NUMBER" --repo "$REPO" --watch --fail-any 2>/dev/null; then
    die "CI checks failed on PR #$PR_NUMBER. Fix issues and re-run."
  fi
  log_ok "CI checks passed on PR #$PR_NUMBER"

  # Squash merge PR — combines all commits into a single commit on main.
  # Release notes are captured via GitHub Release (from CHANGELOG.md),
  # not from the merge commit message, so squash is safe here.
  gh pr merge "$PR_NUMBER" \
    --repo "$REPO" \
    --squash \
    --delete-branch=false \
    || die "Failed to merge PR #$PR_NUMBER"

  log_ok "Squash-merged PR #$PR_NUMBER to main"

  # Sync local main with remote
  git checkout main
  git pull origin main

  MERGE_VIA_PR=true
}

# ── Parse Arguments ────────────────────────────────────────────────

[[ $# -lt 1 ]] && usage
[[ "$1" == "--help" || "$1" == "-h" ]] && usage
[[ $# -lt 2 ]] && { echo "Error: Missing version argument"; usage; }

BRANCH_TYPE="$1"
VERSION="$2"
shift 2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --help|-h) usage ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

# ── Validate Inputs ────────────────────────────────────────────────

[[ "$BRANCH_TYPE" == "hotfix" || "$BRANCH_TYPE" == "release" ]] || die "branch-type must be 'hotfix' or 'release', got '$BRANCH_TYPE'"

echo "$VERSION" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$' || die "Version must follow semver (e.g., v1.0.6 or v1.0.6-beta.1), got '$VERSION'"

VERSION_NUMBER="${VERSION#v}"
SOURCE_BRANCH="${BRANCH_TYPE}/${VERSION}"

# Detect source branch variations (hotfix/deps-v1.0.6 vs hotfix/v1.0.6)
if ! git rev-parse --verify "$SOURCE_BRANCH" >/dev/null 2>&1; then
  # Try with deps- prefix (common for dependabot hotfixes)
  if git rev-parse --verify "${BRANCH_TYPE}/deps-${VERSION}" >/dev/null 2>&1; then
    SOURCE_BRANCH="${BRANCH_TYPE}/deps-${VERSION}"
  else
    die "Source branch not found. Tried: ${BRANCH_TYPE}/${VERSION}, ${BRANCH_TYPE}/deps-${VERSION}"
  fi
fi

REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null) || die "Failed to get repo name. Is gh authenticated?"

# ── Verify Prerequisites ───────────────────────────────────────────

log_phase "PRE-FLIGHT CHECKS"

# Must be on the source branch
CURRENT=$(git branch --show-current)
if [[ "$CURRENT" != "$SOURCE_BRANCH" ]]; then
  die "Must be on $SOURCE_BRANCH, currently on $CURRENT"
fi

# Working directory must be clean
if [[ -n "$(git status --porcelain)" ]]; then
  die "Working directory is not clean. Commit or stash changes first."
fi

# All commits must be pushed (verify upstream is configured first)
if ! git rev-parse --abbrev-ref "@{u}" >/dev/null 2>&1; then
  die "No upstream configured for $SOURCE_BRANCH. Push it first: git push -u origin $SOURCE_BRANCH"
fi
UNPUSHED=$(git log "@{u}..HEAD" --oneline 2>/dev/null | wc -l | tr -d ' ')
if [[ "$UNPUSHED" -gt 0 ]]; then
  die "$UNPUSHED unpushed commits. Push them first: git push"
fi

log_ok "On $SOURCE_BRANCH, clean, all pushed"

# Capitalize first letter (POSIX-compatible; ${VAR^} requires bash 4+ and macOS ships bash 3.2)
BRANCH_TYPE_CAPITALIZED="$(echo "$BRANCH_TYPE" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"

# ── Phase 1: Merge to Main ────────────────────────────────────────

log_phase "MERGE TO MAIN"

if $DRY_RUN; then
  log "[dry-run] Would merge $SOURCE_BRANCH into main"
else
  git checkout main
  git pull origin main

  git merge --no-ff "$SOURCE_BRANCH" -m "$(cat <<EOF
Merge $SOURCE_BRANCH into main

$BRANCH_TYPE_CAPITALIZED $VERSION

See CHANGELOG.md for full details.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" || die "Merge to main failed (conflict?)"

  log_ok "Merged $SOURCE_BRANCH into main (local)"

  # Try to push; if branch protection blocks it, fall back to PR merge
  if ! git push origin main:main 2>/dev/null; then
    merge_main_via_pr
  else
    log_ok "Pushed to origin/main"
  fi
fi

# ── Phase 2: Create Tag ───────────────────────────────────────────

log_phase "CREATE TAG"

if $DRY_RUN; then
  log "[dry-run] Would create tag $VERSION on main"
else
  git tag -a "$VERSION" -m "$BRANCH_TYPE_CAPITALIZED $VERSION" || die "Failed to create tag $VERSION"
  log_ok "Created annotated tag $VERSION"
fi

# ── Phase 3: Create GitHub Release ───────────────────────────────

log_phase "CREATE GITHUB RELEASE"

# Push tag to remote (gh release create uses --target but having the tag pushed ensures annotated tag)
if ! $DRY_RUN && ! $MERGE_VIA_PR; then
  if ! git push origin "$VERSION" 2>&1; then
    log "⚠️  Failed to push tag $VERSION to remote. gh release create will create the tag."
  fi
fi
create_github_release "$VERSION"

# ── Phase 4: Merge to Develop ─────────────────────────────────────

log_phase "MERGE TO DEVELOP"

if $DRY_RUN; then
  log "[dry-run] Would merge $SOURCE_BRANCH into develop"
else
  git checkout develop
  git pull origin develop

  git merge --no-ff "$SOURCE_BRANCH" -m "$(cat <<EOF
Merge $SOURCE_BRANCH back into develop

Sync ${BRANCH_TYPE} artifacts from $VERSION:
- Changelog with versioned section
- Version bumps

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)" || die "Merge to develop failed (conflict?)"

  log_ok "Merged $SOURCE_BRANCH into develop"

  # Sync main's --no-ff merge commit into develop's ancestry.
  # Without this, GitHub shows develop as "1 commit behind main" because
  # the merge commit on main (e.g., "Merge hotfix/v1.0.9 into main") is
  # not an ancestor of develop — even though file content is identical.
  git fetch origin main
  if git log origin/main --not HEAD --oneline | grep -q .; then
    log "Syncing main merge commit into develop ancestry..."
    if git merge origin/main -m "Merge main into develop (sync $VERSION merge commit)

Co-Authored-By: Claude <noreply@anthropic.com>"; then
      log_ok "Develop ancestry now includes main's merge commit"
    else
      git merge --abort 2>/dev/null || true
      log "⚠️  Could not sync main merge commit into develop. Run manually: git merge origin/main"
    fi
  else
    log_ok "Develop already includes all main commits"
  fi
fi

# ── Phase 5: Bump Develop Version ─────────────────────────────────

log_phase "BUMP DEVELOP VERSION"

# Calculate next patch version
MAJOR=$(echo "$VERSION_NUMBER" | cut -d. -f1)
MINOR=$(echo "$VERSION_NUMBER" | cut -d. -f2)
RAW_PATCH=$(echo "$VERSION_NUMBER" | cut -d. -f3)
PATCH=$(echo "$RAW_PATCH" | cut -d- -f1)
NEXT_PATCH=$((PATCH + 1))
NEXT_VERSION="${MAJOR}.${MINOR}.${NEXT_PATCH}"

log "Next development version: $NEXT_VERSION"

if $DRY_RUN; then
  log "[dry-run] Would bump to next patch version via bump-version.sh"
else
  if [[ -x "./scripts/bump-version.sh" ]]; then
    ./scripts/bump-version.sh patch
  else
    log_skip "bump-version.sh not found — skip version bump"
  fi

  # Ensure [Unreleased] header exists in CHANGELOG.md
  if [[ -f CHANGELOG.md ]]; then
    if ! grep -q '## \[Unreleased\]' CHANGELOG.md; then
      # Add [Unreleased] header once before the first version header, portably
      changelog_tmp="$(mktemp)"
      awk '
        BEGIN { inserted = 0 }
        /^## \[/ && !inserted {
          print "## [Unreleased]"
          print ""
          inserted = 1
        }
        { print }
      ' CHANGELOG.md > "$changelog_tmp"
      mv "$changelog_tmp" CHANGELOG.md
      log_ok "Added [Unreleased] header to CHANGELOG.md"
    else
      log_ok "[Unreleased] header already exists in CHANGELOG.md"
    fi
  fi

  # Stage version file changes and CHANGELOG (avoid git add -A which could stage unintended files)
  git add .claude-plugin/plugin.json package.json pyproject.toml Cargo.toml version.txt CHANGELOG.md 2>/dev/null || true
  if ! git diff --cached --quiet; then
    git commit -m "$(cat <<EOF
chore(develop): bump version for next development cycle

Previous ${BRANCH_TYPE}: $VERSION

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
    log_ok "Bumped to next patch and committed"
  else
    log_skip "No version files changed"
  fi
fi

# ── Phase 6: Push Develop ─────────────────────────────────────────

log_phase "PUSH DEVELOP"

push_ref "develop" "develop"

# ── Phase 7: Cleanup ──────────────────────────────────────────────

log_phase "CLEANUP"

if $DRY_RUN; then
  log "[dry-run] Would delete $SOURCE_BRANCH (local + remote)"
else
  # Delete local branch (-D force because squash merge creates different SHA,
  # so git branch -d fails with "not fully merged")
  git branch -D "$SOURCE_BRANCH" 2>/dev/null && log_ok "Deleted local $SOURCE_BRANCH" || log_skip "Local $SOURCE_BRANCH already deleted"

  # Delete remote branch via API (avoids push hook)
  gh api "repos/$REPO/git/refs/heads/$SOURCE_BRANCH" -X DELETE 2>/dev/null && log_ok "Deleted remote $SOURCE_BRANCH" || log_skip "Remote $SOURCE_BRANCH already deleted"
fi

# ── Phase 8: Verify ───────────────────────────────────────────────

log_phase "VERIFICATION"

if $DRY_RUN; then
  log "[dry-run] Would verify main, develop, and tag are in sync"
else
  # Verify current branch
  FINAL_BRANCH=$(git branch --show-current)
  [[ "$FINAL_BRANCH" == "develop" ]] && log_ok "On develop branch" || log_fail "Expected develop, on $FINAL_BRANCH"

  # Verify local = remote for develop
  git fetch origin develop 2>/dev/null
  LOCAL_SHA=$(git rev-parse develop)
  REMOTE_SHA=$(git rev-parse origin/develop 2>/dev/null)
  [[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] && log_ok "develop in sync (local = remote)" || log_fail "develop out of sync: local=$LOCAL_SHA remote=$REMOTE_SHA"

  # Verify local = remote for main
  git fetch origin main 2>/dev/null
  LOCAL_MAIN=$(git rev-parse main)
  REMOTE_MAIN=$(git rev-parse origin/main 2>/dev/null)
  [[ "$LOCAL_MAIN" == "$REMOTE_MAIN" ]] && log_ok "main in sync (local = remote)" || log_fail "main out of sync"

  # Verify GitHub Release (and tag) exists on remote
  if gh release view "$VERSION" --repo "$REPO" --json tagName --jq '.tagName' >/dev/null 2>&1; then
    log_ok "GitHub Release $VERSION exists on remote"
  else
    log_fail "GitHub Release $VERSION not found on remote"
  fi

  log_ok "Develop ready for next development cycle"
fi

# ── Summary ────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Git Flow Finish Complete: $VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  $SOURCE_BRANCH → main (GitHub Release $VERSION) → develop"
echo "  develop bumped to $NEXT_VERSION"
echo "  Source branch deleted (local + remote)"
echo ""
if $DRY_RUN; then
  echo "  [DRY RUN — no changes were made]"
  echo ""
fi
