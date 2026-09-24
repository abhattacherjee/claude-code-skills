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
# Validate BEFORE the arithmetic below. `$(( ))` recursively expands the
# *contents* of the variables it evaluates, so an array-subscript payload in the
# version string -- e.g. `x[$(rm -rf ~)].0.0` -- executes as a command substitution
# during the bump. Here the version comes from `git describe --tags`, so a
# crafted tag name is the untrusted input, and only a semver-shaped string is
# allowed through: X.Y.Z plus an optional `-prerelease` / `+build` suffix
# limited to alphanumerics, dots, `+` and `-`, and each core component is
# bounded to 9 digits so the arithmetic below cannot overflow into a wrapped
# value. This filter is NOT by itself what makes the arithmetic safe -- the
# suffix strip further down is. See the comment there before widening either.
if [[ ! "$CURRENT_VERSION" =~ ^[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}([-+][0-9A-Za-z.+-]+)?$ ]]; then
  print_error "Malformed version from git tag: $CURRENT_VERSION (expected X.Y.Z)"
  exit 1
fi
print_info "Current version: $CURRENT_VERSION"

# ── Calculate new version ─────────────────────────────────────

# The regex above pins the three core components to digit runs, but a permitted
# `-prerelease` / `+build` suffix would otherwise ride along inside PATCH and
# reach `$(( ))`. That is not safe. Arithmetic does not need a literal `$` or
# backtick to execute something: a bare identifier inside `$(( ))` is looked up
# and its *value* re-evaluated as an arithmetic expression, so `1.2.3-zz` with
# `zz='x[$(cmd)]'` exported runs cmd and still exits 0 reporting success -- the
# same recursion this fix exists to stop, reached one level of indirection
# later. A numeric suffix is just as bad the other way: `1.2.3-4` evaluates
# `10#3-4 + 1` to 0 and silently DOWNGRADES to 1.2.0, which is semver-shaped so
# the write guard below cannot catch it.
#
# Stripping at the first `-` or `+` guarantees every component that reaches the
# arithmetic is digits-only, which is the property that actually makes it safe.
IFS='.' read -r MAJOR MINOR PATCH <<< "${CURRENT_VERSION%%[-+]*}"

# `10#` forces base 10: without it a zero-padded component like `08` is read as
# an invalid octal literal and the bump silently produces an empty version.
case "$TYPE" in
  major) NEW_VERSION="$((10#$MAJOR + 1)).0.0" ;;
  minor) NEW_VERSION="$((10#$MAJOR)).$((10#$MINOR + 1)).0" ;;
  patch) NEW_VERSION="$((10#$MAJOR)).$((10#$MINOR)).$((10#$PATCH + 1))" ;;
  *)
    if [[ ! "$TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      print_error "Invalid version format: $TYPE (expected X.Y.Z)"
      exit 1
    fi
    NEW_VERSION="$TYPE"
    ;;
esac

# Symmetric guard: an arithmetic expansion that fails (bash does not treat that
# as fatal even under `set -e`) leaves NEW_VERSION empty or truncated. This repo
# has no version file to clobber -- the version lives in git tags -- but without
# this guard the release flow below reports a bogus (often empty) version and
# still exits 0, which is how a `v1.08.09` tag used to bump to nothing at all.
# Refuse to continue with anything that is not semver-shaped.
if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.+-]+)?$ ]]; then
  print_error "Refusing to continue with malformed version: '$NEW_VERSION' (computed from $CURRENT_VERSION)"
  exit 1
fi

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
