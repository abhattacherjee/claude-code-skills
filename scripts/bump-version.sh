#!/bin/bash
# bump-version.sh — Semantic versioning for any project
# Usage: ./scripts/bump-version.sh <major|minor|patch|X.Y.Z>
#
# Installed by /harden-repo
# Version source: git tags (vX.Y.Z) — no in-repo version file.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

print_info()    { echo -e "${BLUE}info${NC} $1"; }
print_success() { echo -e "${GREEN}success${NC} $1"; }
print_warning() { echo -e "${YELLOW}warning${NC} $1"; }
print_error()   { echo -e "${RED}error${NC} $1"; }

show_usage() {
  echo "Usage: $0 <major|minor|patch|X.Y.Z>"
  echo ""
  echo "  major    Bump major version (1.0.0 -> 2.0.0)"
  echo "  minor    Bump minor version (1.0.0 -> 1.1.0)"
  echo "  patch    Bump patch version (1.0.0 -> 1.0.1)"
  echo "  X.Y.Z    Set specific version"
}

TYPE=$1
if [[ -z "$TYPE" ]]; then
  print_error "Missing version type"
  show_usage
  exit 1
fi

# ══════════════════════════════════════════════════════════════
# VERSION SOURCE — git tags (vX.Y.Z)
# This repo tracks versions via annotated git tags, not a file.
# ══════════════════════════════════════════════════════════════

# Derive current version from the latest git tag (strips leading 'v')
CURRENT_VERSION="$(git -C "$PROJECT_ROOT" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//')"
if [ -z "$CURRENT_VERSION" ]; then CURRENT_VERSION="0.0.0"; fi

if [[ -z "$CURRENT_VERSION" ]]; then
  print_error "Could not determine current version from git tags"
  exit 1
fi
print_info "Current version: $CURRENT_VERSION"

# ── Calculate new version ─────────────────────────────────────

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$TYPE" in
  major) NEW_VERSION="$((MAJOR + 1)).0.0" ;;
  minor) NEW_VERSION="$MAJOR.$((MINOR + 1)).0" ;;
  patch) NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))" ;;
  *)
    if [[ ! "$TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      print_error "Invalid version format: $TYPE (expected X.Y.Z)"
      exit 1
    fi
    NEW_VERSION="$TYPE"
    ;;
esac

print_info "New version: $NEW_VERSION"

# ── Update version files ─────────────────────────────────────

# Version is tracked via git tags (vX.Y.Z); no in-repo version file to update.
# The new tag is created by scripts/git-flow-finish.sh during the release flow.
echo -e "${BLUE}info${NC}  Version source is git tags — no file to update. Next version: $NEW_VERSION"

echo ""
print_success "Version bumped from $CURRENT_VERSION to $NEW_VERSION"
echo ""
print_info "Next steps:"
echo "  1. Update CHANGELOG.md with release notes"
echo "  2. Stage version files + CHANGELOG.md"
echo "  3. git commit -m \"chore(release): bump version to $NEW_VERSION\""
