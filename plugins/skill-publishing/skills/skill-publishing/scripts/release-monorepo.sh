#!/usr/bin/env bash
# release-monorepo.sh — Create a versioned release of the claude-code-skills monorepo
# Bumps version, updates CHANGELOG, commits, tags, and pushes.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load shared library
source "$SCRIPT_DIR/_lib.sh"

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

# --- Resolve GitHub user (via shared _lib.sh) ---
resolve_github_user

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
SKILL_COUNT=$(find . -maxdepth 2 -name "SKILL.md" -not -path "./.git/*" -not -path "./plugins/*" | wc -l | tr -d ' ')

# Count plugins
PLUGIN_COUNT=0
if [[ -d "./plugins" ]]; then
  PLUGIN_COUNT=$(find ./plugins -maxdepth 3 -name "plugin.json" -path "*/.claude-plugin/*" 2>/dev/null | wc -l | tr -d ' ')
fi

# Get commits since last tag
COMMITS_SINCE_TAG=$(git log "v${CURRENT_VERSION}..HEAD" --oneline 2>/dev/null || git log --oneline)
COMMIT_COUNT=$(echo "$COMMITS_SINCE_TAG" | wc -l | tr -d ' ')

echo "Skills:          $SKILL_COUNT"
echo "Plugins:         $PLUGIN_COUNT"
echo "Commits since v${CURRENT_VERSION}: $COMMIT_COUNT"
echo ""

# --- Build skill inventory (extract_field, extract_version from _lib.sh) ---
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"

SKILL_INVENTORY=""
while IFS= read -r skill_md; do
  skill_dir=$(dirname "$skill_md")
  skill_name=$(basename "$skill_dir")
  version=$(extract_version "$skill_md")
  short_desc=$(extract_field "$skill_md" "description" | sed 's/\. Use when:.*//')
  SKILL_INVENTORY="${SKILL_INVENTORY}
- \`$skill_name\` v${version:-?.?.?} — $short_desc"
done < <(find . -maxdepth 2 -name "SKILL.md" -not -path "./.git/*" -not -path "./plugins/*" | sort)

# --- Build plugin inventory ---
PLUGIN_INVENTORY=""
if [[ -d "./plugins" ]]; then
  while IFS= read -r plugin_json; do
    plugin_dir=$(dirname "$(dirname "$plugin_json")")
    plugin_name=$(basename "$plugin_dir")
    p_version=$(jq -r '.version // "?"' "$plugin_json" 2>/dev/null)
    p_desc=$(jq -r '.description // ""' "$plugin_json" 2>/dev/null | sed 's/\. Use when:.*//')
    PLUGIN_INVENTORY="${PLUGIN_INVENTORY}
- \`$plugin_name\` v${p_version} — $p_desc"
  done < <(find ./plugins -maxdepth 3 -name "plugin.json" -path "*/.claude-plugin/*" 2>/dev/null | sort)
fi

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
  HEADER=$(echo "$EXISTING" | awk '/^## \[/{exit} {print}')

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

  PLUGIN_SECTION=""
  if [[ $PLUGIN_COUNT -gt 0 ]]; then
    PLUGIN_SECTION="
### Plugin Inventory ($PLUGIN_COUNT plugins)
$PLUGIN_INVENTORY
"
  fi

  NEW_ENTRY="## [${NEW_VERSION}] - ${TODAY}
${COMMIT_SUMMARY}
### Skill Inventory ($SKILL_COUNT skills)
$SKILL_INVENTORY
${PLUGIN_SECTION}"

  # Rebuild changelog — explicit blank line between header and first entry
  # (bash $() strips trailing newlines, so HEADER never ends with \n)
  NEW_CHANGELOG="${HEADER}

${NEW_ENTRY}"
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
  echo "WOULD CREATE  GitHub release for $TAG_NAME"
  echo ""
  echo "Dry run complete. No changes made."
else
  # Stage changelog update
  git add CHANGELOG.md

  # Check if there's anything to commit
  if git diff --cached --quiet; then
    echo "No changelog changes to commit (already up to date)"
  else
    RELEASE_MSG="Monorepo release $TAG_NAME with $SKILL_COUNT skills"
    if [[ $PLUGIN_COUNT -gt 0 ]]; then
      RELEASE_MSG="$RELEASE_MSG and $PLUGIN_COUNT plugins"
    fi
    git commit -m "release: v${NEW_VERSION}

${RELEASE_MSG}.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    echo "COMMITTED  release: v${NEW_VERSION}"
  fi

  # Create annotated tag
  TAG_BODY="$SKILL_COUNT skills:
$SKILL_INVENTORY"
  if [[ $PLUGIN_COUNT -gt 0 ]]; then
    TAG_BODY="$TAG_BODY

$PLUGIN_COUNT plugins:
$PLUGIN_INVENTORY"
  fi
  git tag -a "$TAG_NAME" -m "Release $TAG_NAME

$TAG_BODY"
  echo "TAGGED     $TAG_NAME"

  # Push (branch + tag)
  git push origin main --tags
  echo "PUSHED     origin main + $TAG_NAME"

  # Create GitHub release from the annotated tag
  RELEASE_TITLE="${TAG_NAME}"
  # Extract a short title from the first Added entry, or use commit summary
  FIRST_FEAT=$(echo "$ADDED" | head -1 | sed 's/^- //')
  if [[ -n "$FIRST_FEAT" ]]; then
    RELEASE_TITLE="${TAG_NAME} — ${FIRST_FEAT}"
  fi

  RELEASE_BODY="## What's Changed
${COMMIT_SUMMARY}
## Inventory

**${SKILL_COUNT} skills** · **${PLUGIN_COUNT} plugins**
${SKILL_INVENTORY}
${PLUGIN_INVENTORY}"

  if gh release create "$TAG_NAME" --title "$RELEASE_TITLE" --notes "$RELEASE_BODY" 2>/dev/null; then
    echo "RELEASED   $TAG_NAME on GitHub"
  else
    echo "Warning: GitHub release creation failed (tag pushed successfully)" >&2
    echo "  Create manually: gh release create $TAG_NAME --generate-notes" >&2
  fi

  echo ""
  echo "Release complete!"
  echo "  Version: $TAG_NAME"
  echo "  Skills:  $SKILL_COUNT"
  echo "  Plugins: $PLUGIN_COUNT"
  echo "  URL:     https://github.com/$GITHUB_USER/claude-code-skills/releases/tag/$TAG_NAME"
fi
