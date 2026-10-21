#!/usr/bin/env bash
set -euo pipefail

# test-bump-version.sh — tests for bump-version.sh's current-version lookup.
#
# The version lives in git tags. The script used `git describe --tags`, which
# returns the nearest tag reachable from HEAD. On develop that is an older
# release, because each release tag sits on main's merge commit: after v4.2.0
# shipped, develop read 3.20.0 and `patch` would have made 3.20.1. The script
# now takes the highest vX.Y.Z tag in the repo.
#
# Cases 1 and 2 fail against the `git describe` version (checked with
# BUMP_SCRIPT pointed at a copy of it). Cases 3 and 4 pass on both; they guard
# the new lookup's version sort and its no-tags default.
#
# Usage: ./scripts/test-bump-version.sh   (BUMP_SCRIPT=<path> tests another copy)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUMP_SCRIPT="${BUMP_SCRIPT:-$HERE/bump-version.sh}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

check() {
  local name="$1" want="$2" got="$3"
  if [[ "$got" == "$want" ]]; then
    PASS=$((PASS + 1))
    echo "PASS: $name"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $name (want '$want', got '$got')"
  fi
}

# Build a repo whose script copy derives PROJECT_ROOT from its own location.
new_repo() {
  local dir="$1"
  mkdir -p "$dir/scripts"
  cp "$BUMP_SCRIPT" "$dir/scripts/bump-version.sh"
  chmod +x "$dir/scripts/bump-version.sh"
  git -C "$dir" init -q
  git -C "$dir" config user.email test@example.com
  git -C "$dir" config user.name test
  git -C "$dir" config commit.gpgsign false
  git -C "$dir" config tag.gpgsign false
}

commit() {
  git -C "$1" commit -q --allow-empty -m "$2"
}

# Print the version the script computes, colors stripped.
new_version() {
  "$1/scripts/bump-version.sh" "$2" 2>&1 \
    | sed 's/\x1b\[[0-9;]*m//g' \
    | sed -n 's/^info New version: //p'
}

# Case 1: the highest tag is not reachable from HEAD (develop after a release).
R1="$TMP/develop"
new_repo "$R1"
commit "$R1" base
git -C "$R1" tag -a v3.20.0 -m v3.20.0
git -C "$R1" checkout -q -b release
commit "$R1" release
git -C "$R1" tag -a v4.2.0 -m v4.2.0
git -C "$R1" checkout -q -b develop v3.20.0
commit "$R1" feature
check "patch from highest tag, not nearest" "4.2.1" "$(new_version "$R1" patch)"
check "minor from highest tag, not nearest" "4.3.0" "$(new_version "$R1" minor)"

# Case 2: pre-release and non-semver tags are not the current version.
git -C "$R1" tag v9.0.0-rc1
git -C "$R1" tag v10.0
git -C "$R1" tag nightly
check "pre-release and partial tags ignored" "4.2.1" "$(new_version "$R1" patch)"

# Case 3: version sort, not string sort (v4.10.0 > v4.9.0).
R3="$TMP/sort"
new_repo "$R3"
commit "$R3" a
git -C "$R3" tag v4.9.0
git -C "$R3" tag v4.10.0
check "version sort" "4.10.1" "$(new_version "$R3" patch)"

# Case 4: no tags starts from 0.0.0.
R4="$TMP/empty"
new_repo "$R4"
commit "$R4" a
check "no tags" "0.0.1" "$(new_version "$R4" patch)"

echo
echo "$PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
