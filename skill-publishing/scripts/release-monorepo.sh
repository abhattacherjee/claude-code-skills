#!/usr/bin/env bash
# release-monorepo.sh — Create a versioned release of the claude-code-skills monorepo
# Bumps version, updates CHANGELOG, commits, tags, and pushes.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUMP_LEVEL=""
DRY_RUN=false
MONOREPO_DIR=""
GITHUB_USER=""

usage() {
  cat <<'EOF'
Usage: release-monorepo.sh [options] <bump-level> <monorepo-dir>

Creates a versioned release of the claude-code-skills monorepo.

Bump levels:
  patch    Bug fixes, sync updates, typo fixes (1.0.0 → 1.0.1)
  minor    New skill added, feature improvements (1.0.0 → 1.1.0)
  major    Breaking changes, removed skills, restructured layout (1.0.0 → 2.0.0)

Options:
  --dry-run              Preview changes without writing
  --github-user NAME     GitHub username (default: auto-detect via gh api)
  -h, --help             Show this help

Examples:
  release-monorepo.sh patch ~/dev/claude-code-skills        # Sync/fix release
  release-monorepo.sh minor ~/dev/claude-code-skills        # New skill release
  release-monorepo.sh --dry-run minor ~/dev/claude-code-skills

Workflow:
  1. sync-monorepo.sh ~/dev/claude-code-skills    # Sync files
  2. cd ~/dev/claude-code-skills && git add -A     # Stage changes
  3. git commit -m "feat: ..."                     # Commit
  4. release-monorepo.sh minor ~/dev/claude-code-skills  # Tag + push
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true; shift ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    -h|--help)      usage ;;
    patch|minor|major) BUMP_LEVEL="$1"; shift ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$MONOREPO_DIR" ]]; then
        MONOREPO_DIR="$1"
      else
        echo "Error: Unexpected argument: $1" >&2; exit 1
      fi
      shift ;;
  esac
done

# --- Validate arguments ---
if [[ -z "$BUMP_LEVEL" ]]; then
  echo "Error: bump level required (patch, minor, or major)" >&2
  echo "Run with --help for usage" >&2
  exit 2
fi

if [[ -z "$MONOREPO_DIR" ]]; then
  echo "Error: monorepo directory required" >&2
  echo "Run with --help for usage" >&2
  exit 2
fi

if [[ ! -d "$MONOREPO_DIR/.git" ]]; then
  echo "Error: $MONOREPO_DIR is not a git repository" >&2
  exit 1
fi

# --- Resolve GitHub user ---
if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
  if [[ -z "$GITHUB_USER" ]]; then
    echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
    exit 1
  fi
fi

cd "$MONOREPO_DIR"

# --- Get current version from latest semver tag ---
CURRENT_VERSION=$(git tag -l 'v[0-9]*' --sort=-v:refname | head -1)
if [[ -z "$CURRENT_VERSION" ]]; then
  CURRENT_VERSION="v0.0.0"
fi
CURRENT_VERSION="${CURRENT_VERSION#v}"  # Strip leading v

IFS='.' read -r CUR_MAJOR CUR_MINOR CUR_PATCH <<< "$CURRENT_VERSION"

# --- Calculate next version ---
case "$BUMP_LEVEL" in
  major) NEW_MAJOR=$((CUR_MAJOR + 1)); NEW_MINOR=0; NEW_PATCH=0 ;;
  minor) NEW_MAJOR=$CUR_MAJOR; NEW_MINOR=$((CUR_MINOR + 1)); NEW_PATCH=0 ;;
  patch) NEW_MAJOR=$CUR_MAJOR; NEW_MINOR=$CUR_MINOR; NEW_PATCH=$((CUR_PATCH + 1)) ;;
esac

NEW_VERSION="${NEW_MAJOR}.${NEW_MINOR}.${NEW_PATCH}"
TAG_NAME="v${NEW_VERSION}"
TODAY=$(date +%Y-%m-%d)

echo "Monorepo:        $MONOREPO_DIR"
echo "GitHub user:     $GITHUB_USER"
echo "Current version: v${CURRENT_VERSION}"
echo "Bump level:      $BUMP_LEVEL"
echo "New version:     $TAG_NAME"
echo "Dry run:         $DRY_RUN"
echo ""

# --- Check for uncommitted changes ---
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: uncommitted changes detected. Commit or stash first." >&2
  echo "" >&2
  git status --short >&2
  exit 1
fi

# --- Check tag doesn't already exist ---
if git tag -l "$TAG_NAME" | grep -q "$TAG_NAME"; then
  echo "Error: tag $TAG_NAME already exists" >&2
  exit 1
fi

# --- Collect release info ---
# Count skills
SKILL_COUNT=$(find . -maxdepth 2 -name "SKILL.md" -not -path "./.git/*" | wc -l | tr -d ' ')

# Get commits since last tag
COMMITS_SINCE_TAG=$(git log "v${CURRENT_VERSION}..HEAD" --oneline 2>/dev/null || git log --oneline)
COMMIT_COUNT=$(echo "$COMMITS_SINCE_TAG" | wc -l | tr -d ' ')

echo "Skills:          $SKILL_COUNT"
echo "Commits since v${CURRENT_VERSION}: $COMMIT_COUNT"
echo ""

# --- Build skill inventory ---
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"

extract_field() {
  local skill_md="$1"
  local field="$2"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "^${field}:" | head -1 | sed "s/^${field}:[[:space:]]*//; s/^[\"']//; s/[\"']$//"
}

extract_version() {
  local skill_md="$1"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "version:" | head -1 | sed "s/.*version:[[:space:]]*//; s/^[\"']*//; s/[\"']*$//"
}

SKILL_INVENTORY=""
while IFS= read -r skill_md; do
  skill_dir=$(dirname "$skill_md")
  skill_name=$(basename "$skill_dir")
  version=$(extract_version "$skill_md")
  short_desc=$(extract_field "$skill_md" "description" | sed 's/\. Use when:.*//')
  SKILL_INVENTORY="${SKILL_INVENTORY}
- \`$skill_name\` v${version:-?.?.?} — $short_desc"
done < <(find . -maxdepth 2 -name "SKILL.md" -not -path "./.git/*" | sort)

# --- Build commit summary ---
# Categorize commits since last tag into Added/Changed/Fixed sections
COMMIT_SUMMARY=""
ADDED=""
CHANGED=""
FIXED=""
OTHER=""

while IFS= read -r line; do
  msg="${line#* }"  # Strip commit hash prefix
  case "$msg" in
    feat:*|feat\(*) ADDED="${ADDED}
- ${msg#*: }" ;;
    fix:*|fix\(*)   FIXED="${FIXED}
- ${msg#*: }" ;;
    chore:*|chore\(*|docs:*|docs\(*|style:*|refactor:*|refactor\(*)
      CHANGED="${CHANGED}
- ${msg#*: }" ;;
    release:*) ;; # Skip release commits
    Merge*) ;; # Skip merge commits
    *)
      OTHER="${OTHER}
- ${msg}" ;;
  esac
done <<< "$COMMITS_SINCE_TAG"

# Build summary sections
if [[ -n "$ADDED" ]]; then
  COMMIT_SUMMARY="${COMMIT_SUMMARY}
### Added
${ADDED}
"
fi
if [[ -n "$CHANGED" ]]; then
  COMMIT_SUMMARY="${COMMIT_SUMMARY}
### Changed
${CHANGED}
"
fi
if [[ -n "$FIXED" ]]; then
  COMMIT_SUMMARY="${COMMIT_SUMMARY}
### Fixed
${FIXED}
"
fi
if [[ -n "$OTHER" && -z "$ADDED" && -z "$CHANGED" && -z "$FIXED" ]]; then
  # Only include "other" if no categorized commits exist
  COMMIT_SUMMARY="${COMMIT_SUMMARY}
### Changes
${OTHER}
"
fi

# --- Update CHANGELOG ---
# Replace the top "Monorepo sync" entry with a versioned release entry,
# or prepend a new versioned entry if the top isn't a sync entry.
CHANGELOG_FILE="$MONOREPO_DIR/CHANGELOG.md"

if [[ -f "$CHANGELOG_FILE" ]]; then
  # Read current changelog
  EXISTING=$(cat "$CHANGELOG_FILE")

  # Extract header (everything before first ## [)
  # Ensure it ends with exactly one trailing newline
  HEADER=$(echo "$EXISTING" | awk '/^## \[/{exit} {print}')
  HEADER=$(printf '%s\n\n' "$HEADER")

  # Extract all entries
  ALL_ENTRIES=$(echo "$EXISTING" | awk '/^## \[/{found=1} found{print}')

  # Check if the top entry is today's "Monorepo sync" — if so, replace it with versioned
  FIRST_ENTRY_HEADER=$(echo "$ALL_ENTRIES" | head -1)
  if echo "$FIRST_ENTRY_HEADER" | grep -q "Monorepo sync"; then
    # Replace the sync entry with a versioned release entry
    # Skip the first entry, keep the rest
    REMAINING_ENTRIES=$(echo "$ALL_ENTRIES" | awk '/^## \[/{count++} count>=2{print}')
  else
    # No sync entry to replace — prepend before existing entries
    REMAINING_ENTRIES="$ALL_ENTRIES"
  fi

  NEW_ENTRY="## [${NEW_VERSION}] - ${TODAY}
${COMMIT_SUMMARY}
### Skill Inventory ($SKILL_COUNT skills)
$SKILL_INVENTORY
"

  # Rebuild changelog
  NEW_CHANGELOG="${HEADER}${NEW_ENTRY}"
  if [[ -n "$REMAINING_ENTRIES" ]]; then
    NEW_CHANGELOG="${NEW_CHANGELOG}
${REMAINING_ENTRIES}"
  fi

  if $DRY_RUN; then
    echo "WOULD UPDATE  CHANGELOG.md"
    echo "  Top entry: ## [${NEW_VERSION}] - ${TODAY}"
    echo ""
  else
    echo "$NEW_CHANGELOG" > "$CHANGELOG_FILE"
    echo "UPDATED  CHANGELOG.md (top entry → v${NEW_VERSION})"
  fi
else
  echo "Warning: no CHANGELOG.md found, skipping" >&2
fi

# --- Commit, tag, push ---
if $DRY_RUN; then
  echo "WOULD COMMIT  release: v${NEW_VERSION}"
  echo "WOULD TAG     $TAG_NAME"
  echo "WOULD PUSH    origin main --tags"
  echo ""
  echo "Dry run complete. No changes made."
else
  # Stage changelog update
  git add CHANGELOG.md

  # Check if there's anything to commit
  if git diff --cached --quiet; then
    echo "No changelog changes to commit (already up to date)"
  else
    git commit -m "release: v${NEW_VERSION}

Monorepo release $TAG_NAME with $SKILL_COUNT skills.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    echo "COMMITTED  release: v${NEW_VERSION}"
  fi

  # Create annotated tag
  git tag -a "$TAG_NAME" -m "Release $TAG_NAME

$SKILL_COUNT skills:
$SKILL_INVENTORY"
  echo "TAGGED     $TAG_NAME"

  # Push (branch + tag)
  git push origin main --tags
  echo "PUSHED     origin main + $TAG_NAME"

  echo ""
  echo "Release complete!"
  echo "  Version: $TAG_NAME"
  echo "  Skills:  $SKILL_COUNT"
  echo "  URL:     https://github.com/$GITHUB_USER/claude-code-skills/releases/tag/$TAG_NAME"
fi
