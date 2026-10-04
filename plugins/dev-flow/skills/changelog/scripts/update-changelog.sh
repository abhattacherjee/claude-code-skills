#!/usr/bin/env bash
# update-changelog.sh — Generate or update CHANGELOG.md entries from git commits
# Reads the commits since a starting point and sorts them into Keep-a-Changelog categories.
# Write mode only ever adds lines to CHANGELOG.md; it checks that before it replaces the file.
set -eu

TODAY=$(date +%Y-%m-%d)

# Defaults
DRY_RUN=false
REPO_DIR=""
SINCE=""
VERSION=""
MODE="unreleased"  # unreleased | version

usage() {
  cat <<'EOF'
Usage: update-changelog.sh [options] [repo-directory]

Generates CHANGELOG.md entries from git commit history.
Categorizes changes into Added/Changed/Fixed/Removed/Testing/Documentation/Other
by conventional commit prefix. An unprefixed commit goes to Other. Only when no
commit in the range has a prefix, and the range changed a file under src/, lib/
or scripts/, do they go to Changed instead.

Options:
  --dry-run              Preview changelog entry without writing
  --since <ref>          Git ref to start from: a tag, branch or commit, also
                         HEAD~2 or v1.0.0^. Letters, digits and . _ / ~ ^ - only,
                         not starting with -.
                         Default, in this order: the newest release tag
                         (v1.2.3 or 1.2.3) reachable from HEAD; else the first
                         versioned heading of CHANGELOG.md, if it names a tag or
                         ref; else the whole history.
  --version <ver>        Move [Unreleased] and the new bullets into a
                         "## [<ver>] - <today>" section; [Unreleased] stays,
                         empty. Refused if "## [<ver>]" already exists.
                         Default: add the new bullets to [Unreleased]
  -h, --help             Show this help

Writing never removes a line: new bullets are added to the matching ### section,
and bullets already there are skipped.

Examples:
  update-changelog.sh                          # Update [Unreleased] in current dir
  update-changelog.sh --version 2.0.0          # Create versioned entry
  update-changelog.sh --since v1.0.0           # Changes since v1.0.0
  update-changelog.sh --dry-run ~/my-project   # Preview for specific repo
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=true; shift ;;
    --since)      [[ $# -ge 2 ]] || { echo "Error: --since needs a value" >&2; exit 1; }
                  SINCE="$2"; shift 2 ;;
    --version)    [[ $# -ge 2 ]] || { echo "Error: --version needs a value" >&2; exit 1; }
                  VERSION="$2"; MODE="version"; shift 2 ;;
    -h|--help)    usage ;;
    -*)           echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)            REPO_DIR="$1"; shift ;;
  esac
done

# Default to current directory
if [[ -z "$REPO_DIR" ]]; then
  REPO_DIR="$(pwd)"
fi

REPO_DIR="$(cd "$REPO_DIR" && pwd)"
CHANGELOG="$REPO_DIR/CHANGELOG.md"

# Verify it's a git repo (.git is a file, not a directory, in a worktree)
if ! git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: $REPO_DIR is not a git repository" >&2
  exit 1
fi

cd "$REPO_DIR"

# A CHANGELOG.md that is there but is not a regular file (a directory, a fifo) cannot be
# read or replaced. A symlink is refused at write time, and read through in --dry-run.
if [[ -e "$CHANGELOG" && ! -f "$CHANGELOG" ]]; then
  echo "Error: $CHANGELOG exists but is not a regular file" >&2
  exit 1
fi

# --version X refuses when "## [X]" is already a heading, before any work is done.
if [[ "$MODE" == "version" && -f "$CHANGELOG" ]]; then
  if V="$VERSION" awk 'index($0, "## [" ENVIRON["V"] "]") == 1 { found = 1 } END { exit !found }' "$CHANGELOG"; then
    echo "Error: CHANGELOG.md already has a '## [$VERSION]' section; refusing to add another" >&2
    exit 1
  fi
fi

# --- Resolve the starting point to a commit ---
# A ref name may hold only these characters, and must not start with "-", so it can never
# act as a git option. The same rule covers --since and the CHANGELOG.md heading, which is
# untrusted input: letters, digits and . _ / ~ ^ -
REF_CHARS='^[0-9A-Za-z._/~^-]+$'
# resolve_ref <name>: print the commit SHA for <name>, or fail.
resolve_ref() {
  local name="$1"
  [[ "$name" =~ $REF_CHARS && "$name" != -* ]] || return 1
  git rev-parse --verify --quiet "${name}^{commit}"
}

SINCE_LABEL="$SINCE"
WHOLE_HISTORY=false
if [[ -n "$SINCE" ]]; then
  if ! SINCE=$(resolve_ref "$SINCE"); then
    echo "Error: --since '$SINCE_LABEL' is not a tag, branch or commit in this repository" >&2
    echo "  (a ref may use letters, digits and . _ / ~ ^ -, and must not start with -)" >&2
    exit 1
  fi
else
  # 1. The newest final-release tag reachable from HEAD: v1.2.3 or 1.2.3 exactly. Not
  #    v1.2.3-rc1, 20261001-snap or release-2.0.0. Sorted by version, so v1.10.0 > v1.9.0.
  ALL_TAGS=$(git tag -l --merged HEAD 2>/dev/null || true)
  LAST_TAG=$(printf '%s\n' "$ALL_TAGS" | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' \
    | awk '{ v = $0; sub(/^v/, "", v); split(v, p, "."); printf "%d %d %d %s\n", p[1], p[2], p[3], $0 }' \
    | sort -k1,1n -k2,2n -k3,3n | tail -1 | cut -d' ' -f4 || true)
  SINCE=""
  if [[ -n "$LAST_TAG" ]] && SINCE=$(resolve_ref "$LAST_TAG"); then
    SINCE_LABEL="$LAST_TAG"
    echo "Auto-detected: changes since tag $SINCE_LABEL"
  else
    SINCE=""
    if [[ -z "$ALL_TAGS" ]]; then
      echo "No tags found."
    else
      echo "Found $(printf '%s\n' "$ALL_TAGS" | wc -l | tr -d ' ') tag(s) reachable from HEAD, but none is a release version (v1.2.3 or 1.2.3)."
    fi
    # 2. The first versioned heading of CHANGELOG.md ([Unreleased] skipped), as vX or X.
    if [[ -f "$CHANGELOG" ]]; then
      LAST_VERSION=$(grep '^## \[' "$CHANGELOG" | grep -v '^## \[Unreleased\]' | head -1 | sed 's/^## \[\([^]]*\)\].*/\1/' || true)
      if [[ -n "$LAST_VERSION" ]]; then
        for prefix in "v" ""; do
          if SINCE=$(resolve_ref "${prefix}${LAST_VERSION}"); then
            SINCE_LABEL="${prefix}${LAST_VERSION}"
            echo "Auto-detected: changes since $SINCE_LABEL (from CHANGELOG.md)"
            break
          fi
          SINCE=""
        done
      fi
    fi
    # 3. The whole history. An empty SINCE means every commit reachable from HEAD, the
    #    first one included ("root..HEAD" would skip it).
    if [[ -z "$SINCE" ]]; then
      WHOLE_HISTORY=true
      echo "Using the whole history (every commit reachable from HEAD, the first one included)."
    fi
  fi
fi

# --- Gather commits ---
if [[ -n "$SINCE" ]]; then
  RANGE="$SINCE..HEAD"
  DIFF_FROM="$SINCE"
else
  RANGE="HEAD"
  DIFF_FROM="$(git hash-object -t tree /dev/null)"  # the empty tree
fi
if $WHOLE_HISTORY; then
  SPAN="in the whole history"
else
  SPAN="since $SINCE_LABEL"
fi
COMMITS=$(git log "$RANGE" --pretty=format:"%s" --no-merges)
if [[ -z "$COMMITS" ]]; then
  echo "No new commits $SPAN"
  exit 0
fi

COMMIT_COUNT=$(printf '%s\n' "$COMMITS" | wc -l | tr -d ' ')
echo "Found $COMMIT_COUNT commits $SPAN"
echo ""

# --- Gather changed files for categorization ---
CHANGED_FILES=$(git diff --name-only "$DIFF_FROM" HEAD)

# --- Categorize commits by conventional commit prefix ---
ADDED=""
CHANGED=""
FIXED=""
REMOVED=""
TESTING=""
DOCS=""
OTHER=""

while IFS= read -r msg; do
  [[ -z "$msg" ]] && continue

  # Strip scope: "feat(auth): message" -> "feat" + "message"
  prefix=$(echo "$msg" | sed -nE 's/^([a-z]+)(\([^)]*\))?[!]?:.*/\1/p')
  body=$(echo "$msg" | sed -E 's/^[a-z]+(\([^)]*\))?[!]?:[[:space:]]*//')

  # If no conventional prefix, use the full message
  if [[ -z "$prefix" ]]; then
    body="$msg"
    prefix="other"
  fi

  # Categorize
  case "$prefix" in
    feat|add)     ADDED="${ADDED}- ${body}"$'\n' ;;
    fix)          FIXED="${FIXED}- ${body}"$'\n' ;;
    docs)         DOCS="${DOCS}- ${body}"$'\n' ;;
    test)         TESTING="${TESTING}- ${body}"$'\n' ;;
    refactor|perf|style|chore|build|ci)
                  CHANGED="${CHANGED}- ${body}"$'\n' ;;
    revert)       REMOVED="${REMOVED}- ${body}"$'\n' ;;
    *)            OTHER="${OTHER}- ${body}"$'\n' ;;
  esac
done <<< "$COMMITS"

# File-path fallback: only when NO commit in the range has a prefix. If the range changed a
# file under src/, lib/ or scripts/, the unprefixed commits go to Changed; otherwise they
# stay in Other. In a mixed range, unprefixed commits always stay in Other.
if [[ -z "$ADDED" && -z "$CHANGED" && -z "$FIXED" && -z "$REMOVED" && -z "$TESTING" && -z "$DOCS" && -n "$OTHER" ]]; then
  has_src=false
  while IFS= read -r f; do
    case "$f" in
      src/*|lib/*|scripts/*) has_src=true ;;
    esac
  done <<< "$CHANGED_FILES"
  if $has_src; then
    CHANGED="$OTHER"
    OTHER=""
  fi
fi

# --- Build changelog entry ---
if [[ "$MODE" == "version" ]]; then
  ENTRY_HEADER="## [$VERSION] - $TODAY"
else
  ENTRY_HEADER="## [Unreleased]"
fi

ENTRY="$ENTRY_HEADER"

# Add commit range summary
ENTRY="$ENTRY
"

if [[ -n "$ADDED" ]]; then
  ENTRY="${ENTRY}
### Added

${ADDED}"
fi

if [[ -n "$CHANGED" ]]; then
  ENTRY="${ENTRY}
### Changed

${CHANGED}"
fi

if [[ -n "$FIXED" ]]; then
  ENTRY="${ENTRY}
### Fixed

${FIXED}"
fi

if [[ -n "$REMOVED" ]]; then
  ENTRY="${ENTRY}
### Removed

${REMOVED}"
fi

if [[ -n "$TESTING" ]]; then
  ENTRY="${ENTRY}
### Testing

${TESTING}"
fi

if [[ -n "$DOCS" ]]; then
  ENTRY="${ENTRY}
### Documentation

${DOCS}"
fi

if [[ -n "$OTHER" ]]; then
  ENTRY="${ENTRY}
### Other

${OTHER}"
fi

# Each section ends with a newline, so a blank line separates it from the next heading.
ENTRY="${ENTRY%$'\n'}"

# --- Output ---
echo "Generated changelog entry:"
echo "─────────────────────────────"
echo "$ENTRY"
echo "─────────────────────────────"

if $DRY_RUN; then
  echo ""
  echo "Dry run — no files written."
  exit 0
fi

# --- Write to CHANGELOG.md ---
# Never write through a symlink: a CHANGELOG.md that points outside the repo would
# overwrite that file. The new content goes to a temp file in the same directory
# and is renamed over CHANGELOG.md.
if [[ -L "$CHANGELOG" ]]; then
  echo "Error: $CHANGELOG is a symlink; refusing to write through it" >&2
  exit 1
fi
TMPFILE=$(mktemp "$REPO_DIR/.CHANGELOG.XXXXXX")
trap 'rm -f "$TMPFILE"' EXIT

if [[ ! -e "$CHANGELOG" ]]; then
  # Create new changelog
  chmod 644 "$TMPFILE"
  printf '# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n%s\n' "$ENTRY" > "$TMPFILE"
  mv "$TMPFILE" "$CHANGELOG"
  echo ""
  echo "Created $CHANGELOG"
  exit 0
fi

# Merge into the existing file. Every line of the old file is kept; lines are only added.
#   - The [Unreleased] block runs from "## [Unreleased]" to the next line that starts with
#     "## " or is a link reference ("[x]: url"), or to the end of the file.
#   - Each generated bullet that is not already a line of that block goes under the block's
#     "### <Category>" heading (after its last line), or under a new heading at the end
#     of the block.
#   - With no [Unreleased] block, a new section goes before the first "## " heading or
#     link reference, or at the end of the file.
#   - --version: the "## [X] - DATE" heading goes right under "## [Unreleased]", so the old
#     body and the new bullets become the X section and [Unreleased] is left empty.
# The bullets reach awk through the environment ("Category<TAB>- bullet" per line): `awk -v`
# would turn a backslash in a commit subject into an escape.
GEN=""
add_gen() {
  local cat="$1" list="$2" line
  while IFS= read -r line; do
    [[ -n "$line" ]] && GEN="${GEN}${cat}"$'\t'"${line}"$'\n'
  done <<< "$list"
  return 0
}
add_gen Added "$ADDED"
add_gen Changed "$CHANGED"
add_gen Fixed "$FIXED"
add_gen Removed "$REMOVED"
add_gen Testing "$TESTING"
add_gen Documentation "$DOCS"
add_gen Other "$OTHER"
if [[ "$MODE" == "version" ]]; then
  VHEAD="$ENTRY_HEADER"
else
  VHEAD=""
fi
export GEN VHEAD

cp -p "$CHANGELOG" "$TMPFILE"
ADDED_COUNT=$(awk -v out="$TMPFILE" '
  function blank(s) { return s ~ /^[ \t]*$/ }
  function emit(s) { print s > out }
  BEGIN {
    ng = split(ENVIRON["GEN"], g, "\n")
    ncat = 0
    for (i = 1; i <= ng; i++) {
      if (g[i] == "") continue
      t = index(g[i], "\t")
      c = substr(g[i], 1, t - 1)
      if (!(c in nb)) { order[++ncat] = c; nb[c] = 0 }
      nb[c]++
      bl[c, nb[c]] = substr(g[i], t + 1)
    }
    vhead = ENVIRON["VHEAD"]
  }
  { L[++n] = $0 }
  END {
    u = 0
    for (i = 1; i <= n; i++) if (L[i] ~ /^## \[Unreleased\]/) { u = i; break }
    added = 0
    if (u == 0) {
      # No [Unreleased]: build a new section and put it before the first "## " heading or
      # link reference, or at the end.
      at = n + 1
      for (i = 1; i <= n; i++) if (L[i] ~ /^## / || L[i] ~ /^\[[^]]+\]: /) { at = i; break }
      sec = (vhead != "" ? vhead : "## [Unreleased]")
      for (k = 1; k <= ncat; k++) {
        c = order[k]; s = ""
        for (j = 1; j <= nb[c]; j++) if (!((c, bl[c, j]) in dup)) { dup[c, bl[c, j]] = 1; s = s "\n" bl[c, j]; added++ }
        if (s != "") sec = sec "\n\n### " c "\n" s
      }
      for (i = 1; i < at; i++) emit(L[i])
      if (at > 1 && !blank(L[at - 1])) emit("")
      emit(sec)
      if (at <= n) emit("")
      for (i = at; i <= n; i++) emit(L[i])
      print added
      exit 0
    }
    e = n + 1
    for (i = u + 1; i <= n; i++) if (L[i] ~ /^## / || L[i] ~ /^\[[^]]+\]: /) { e = i; break }
    # Lines already in the block, the first heading of each category, and the last
    # non-blank line of the sub-section under that heading.
    hidx = 0; blast = u
    for (i = u + 1; i < e; i++) {
      have[L[i]] = 1
      if (!blank(L[i])) blast = i
      if (L[i] ~ /^### /) {
        name = substr(L[i], 5); sub(/[ \t]+$/, "", name)
        hidx = i
        if (!(name in h)) { h[name] = i; last[i] = i }
        continue
      }
      if (hidx && !blank(L[i])) last[hidx] = i
    }
    tail = ""
    for (k = 1; k <= ncat; k++) {
      c = order[k]; s = ""
      for (j = 1; j <= nb[c]; j++) {
        b = bl[c, j]
        if (b in have) continue
        have[b] = 1; s = s "\n" b; added++
      }
      if (s == "") continue
      if (c in h) { at = last[h[c]]; after[at] = after[at] s }
      else tail = tail "\n\n### " c "\n" s
    }
    if (tail != "") after[blast] = after[blast] tail
    for (i = 1; i <= n; i++) {
      emit(L[i])
      if (i == u && vhead != "") { emit(""); emit(vhead); added++ }
      if (i in after) {
        emit(substr(after[i], 2))
        if (i < n && !blank(L[i + 1])) emit("")
      }
    }
    print added
  }
' "$CHANGELOG")

if [[ "$ADDED_COUNT" == 0 ]]; then
  echo ""
  echo "CHANGELOG.md already has every generated bullet; nothing written."
  exit 0
fi

# Safety net: every line of the old file must still be in the new one, in the same order.
# If not, leave CHANGELOG.md alone (the trap removes the temp file) and fail.
if ! awk '
  FILENAME == ARGV[1] { old[++n] = $0; next }
  i < n && ($0 "") == (old[i + 1] "") { i++ }
  END { exit (i == n) ? 0 : 1 }
' "$CHANGELOG" "$TMPFILE"; then
  echo "Error: the new CHANGELOG.md would lose or reorder lines of the old one; nothing written" >&2
  exit 1
fi

mv "$TMPFILE" "$CHANGELOG"
echo ""
echo "Updated $CHANGELOG"
