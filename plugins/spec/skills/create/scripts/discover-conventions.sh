#!/usr/bin/env bash
set -eu

# discover-conventions.sh — Scans a project for story spec conventions.
# Detects spec directory structure, common sections, naming patterns,
# epic numbering, and outputs a project-aware template context.
#
# Usage:
#   discover-conventions.sh <project-root>           # Human-readable report
#   discover-conventions.sh <project-root> --json    # JSON for agent consumption
#   discover-conventions.sh --help

usage() {
    cat <<EOF
Usage: $(basename "$0") <project-root> [--json]

Discovers story spec conventions from an existing project.

Arguments:
  project-root   Path to the project root directory
  --json         Output as JSON (for agent consumption)
  --help         Show this help

Examples:
  $(basename "$0") /path/to/my-project
  $(basename "$0") . --json

Discovers:
  - Spec directory structure (where specs live)
  - Story file naming convention (story-X.Y-name.md)
  - Epic organization (subdirectories, flat)
  - Common sections across specs (required vs optional)
  - Next available story number per epic
  - Tracking file locations
EOF
    exit 0
}

[[ $# -lt 1 ]] && { echo "Error: project root required. Use --help for usage." >&2; exit 2; }
[[ "$1" == "--help" || "$1" == "-h" ]] && usage

PROJECT_ROOT="$1"
JSON_MODE=false
[[ "${2:-}" == "--json" ]] && JSON_MODE=true

if [[ ! -d "$PROJECT_ROOT" ]]; then
    echo "Error: Directory not found: $PROJECT_ROOT" >&2
    exit 1
fi

cd "$PROJECT_ROOT"

# --- Utility ---

json_escape() {
    # Escape a string for use inside a JSON "...": backslash, quote, and every
    # control character below 0x20 (\n, \r and \t by name, the rest as \u00XX).
    local str="$1" code c esc
    # Drop bytes that are not valid UTF-8 (a JSON string cannot hold them). Work in
    # the C locale so the pattern tests below see bytes. Valid UTF-8 is kept.
    local LC_ALL=C
    if [[ "$str" == *[!\ -~]* ]] && command -v iconv >/dev/null 2>&1; then
        str=$(printf '%s.' "$str" | iconv -c -f UTF-8 -t UTF-8 2>/dev/null) || true
        str="${str%.}"
    fi
    str="${str//\\/\\\\}"
    str="${str//\"/\\\"}"
    str="${str//$'\n'/\\n}"
    str="${str//$'\r'/\\r}"
    str="${str//$'\t'/\\t}"
    if [[ "$str" == *[[:cntrl:]]* ]]; then
        for code in 1 2 3 4 5 6 7 8 11 12 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31; do
            printf -v c "\\$(printf '%03o' "$code")"
            printf -v esc '\\u%04x' "$code"
            str="${str//"$c"/$esc}"
        done
    fi
    printf '%s' "$str"
}

# Epic names come from directory and file names, so they are untrusted. Only a
# plain number is accepted. The same check guards every $(( )) below. A story
# number is also capped at 9 digits, so $(( )) cannot overflow. `10#` makes bash
# read `07` as 7, not as octal, and the number is printed without its zero.
is_number() { [[ "$1" =~ ^[0-9]+$ ]]; }

# An unreadable spec or epic directory would look empty (find hides the error),
# and an epic would be reported as having no stories. Stop instead.
check_readable() {
    local d
    for d in "$1" "$1"/*/; do
        [[ -d "$d" ]] || continue
        if [[ ! -r "$d" || ! -x "$d" ]]; then
            echo "Error: cannot read directory: $d" >&2
            exit 1
        fi
    done
}

# --- Discovery functions ---

find_spec_dir() {
    # Common locations for specs
    for dir in specs/stories specs stories docs/specs; do
        if [[ -d "$dir" ]]; then
            echo "$dir"
            return
        fi
    done
    echo ""
}

count_specs() {
    local spec_dir="$1"
    [[ -z "$spec_dir" ]] && { echo "0"; return; }
    find "$spec_dir" -name "*.md" -not -name "README*" -not -name "tracking*" 2>/dev/null | wc -l | tr -d ' '
}

detect_epic_structure() {
    local spec_dir="$1"
    [[ -z "$spec_dir" ]] && { echo "flat"; return; }
    if compgen -G "$spec_dir/epic-*" > /dev/null; then
        echo "epic-subdirs"
    elif compgen -G "$spec_dir/[0-9]*" > /dev/null; then
        echo "numbered-subdirs"
    else
        echo "flat"
    fi
}

find_naming_pattern() {
    local spec_dir="$1"
    [[ -z "$spec_dir" ]] && { echo "unknown"; return; }
    # Check most common patterns
    local story_prefix_count feature_prefix_count spec_prefix_count
    story_prefix_count=$(find "$spec_dir" -name "story-*.md" 2>/dev/null | wc -l | tr -d ' ')
    feature_prefix_count=$(find "$spec_dir" -name "feature-*.md" 2>/dev/null | wc -l | tr -d ' ')
    spec_prefix_count=$(find "$spec_dir" -name "spec-*.md" 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$story_prefix_count" -gt "$feature_prefix_count" && "$story_prefix_count" -gt "$spec_prefix_count" ]]; then
        echo "story-X.Y-name.md"
    elif [[ "$feature_prefix_count" -gt 0 ]]; then
        echo "feature-name.md"
    elif [[ "$spec_prefix_count" -gt 0 ]]; then
        echo "spec-name.md"
    else
        echo "unknown"
    fi
}

find_epics() {
    local spec_dir="$1" d name
    [[ -z "$spec_dir" ]] && return
    # List epic directories or extract epic numbers from filenames. A name that is
    # not a plain number is skipped; text mode says so on stderr, JSON mode stays quiet.
    if [[ "$(detect_epic_structure "$spec_dir")" == "epic-subdirs" ]]; then
        for d in "$spec_dir"/epic-*; do
            [[ -e "$d" ]] || continue
            name="${d##*/epic-}"
            if is_number "$name"; then
                printf '%s\n' "$name"
            elif ! $JSON_MODE; then
                printf 'skipped epic with a non-numeric name: %q\n' "$name" >&2
            fi
        done | sort -n
    else
        find "$spec_dir" -name "story-*.md" 2>/dev/null | grep -oE 'story-[0-9]+' | sed 's/story-//' | sort -un
    fi
}

# Names of epic directories that were skipped because they are not all digits.
find_skipped_epics() {
    local spec_dir="$1" d name
    [[ -z "$spec_dir" ]] && return
    [[ "$(detect_epic_structure "$spec_dir")" == "epic-subdirs" ]] || return 0
    for d in "$spec_dir"/epic-*; do
        [[ -e "$d" ]] || continue
        name="${d##*/epic-}"
        is_number "$name" || printf '%s\0' "epic-$name"
    done
}

find_tracking_files() {
    # Common tracking file locations
    for f in specs/mvp-tracking.md specs/post-mvp-tracking.md specs/tracking.md docs/tracking.md; do
        [[ -f "$f" ]] && echo "$f"
    done
}

extract_common_sections() {
    local spec_dir="$1"
    [[ -z "$spec_dir" ]] && return
    # Sample up to 5 specs and find ## headings
    find "$spec_dir" -name "*.md" -not -name "README*" -not -name "tracking*" 2>/dev/null | \
        head -5 | while read -r f; do
        grep '^## ' "$f" 2>/dev/null | sed 's/^## //'
    done | LC_ALL=C sort | uniq -c | LC_ALL=C sort -rn | head -20
}

find_latest_story_number() {
    local spec_dir="$1" epic="$2"
    [[ -z "$spec_dir" ]] && { echo "0"; return; }
    is_number "$epic" || { echo "0"; return; }
    if [[ -d "$spec_dir/epic-$epic" ]]; then
        find "$spec_dir/epic-$epic" -name "story-${epic}.*-*.md" 2>/dev/null | \
            grep -oE "story-${epic}\.[0-9]+" | sed "s/story-${epic}\.//" | sort -n | tail -1
    else
        find "$spec_dir" -name "story-${epic}.*-*.md" 2>/dev/null | \
            grep -oE "story-${epic}\.[0-9]+" | sed "s/story-${epic}\.//" | sort -n | tail -1
    fi
}

get_sample_spec() {
    local spec_dir="$1"
    [[ -z "$spec_dir" ]] && return
    # Get the most recently modified spec
    find "$spec_dir" -name "story-*.md" -not -name "README*" -exec ls -t {} + 2>/dev/null | head -1
}

# --- Run discovery ---

SPEC_DIR=$(find_spec_dir)
[[ -n "$SPEC_DIR" ]] && check_readable "$SPEC_DIR"
SPEC_COUNT=$(count_specs "$SPEC_DIR")
EPIC_STRUCTURE=$(detect_epic_structure "$SPEC_DIR")
NAMING_PATTERN=$(find_naming_pattern "$SPEC_DIR")
SAMPLE_SPEC=$(get_sample_spec "$SPEC_DIR")

# --- Output ---

if $JSON_MODE; then
    # Build epic list as JSON array
    EPIC_JSON="["
    FIRST=true
    while IFS= read -r epic; do
        [[ -z "$epic" ]] && continue
        latest=$(find_latest_story_number "$SPEC_DIR" "$epic")
        is_number "$latest" && [[ ${#latest} -le 9 ]] || latest="0"
        next=$((10#$latest + 1))
        latest=$((10#$latest))
        if $FIRST; then FIRST=false; else EPIC_JSON+=","; fi
        EPIC_JSON+="{\"epic\":\"$(json_escape "$epic")\",\"latestStory\":$latest,\"nextStory\":$next}"
    done < <(find_epics "$SPEC_DIR")
    EPIC_JSON+="]"

    # Build skipped epics array
    SKIPPED_JSON="["
    FIRST=true
    while IFS= read -r -d '' name; do
        if $FIRST; then FIRST=false; else SKIPPED_JSON+=","; fi
        SKIPPED_JSON+="\"$(json_escape "$name")\""
    done < <(find_skipped_epics "$SPEC_DIR")
    SKIPPED_JSON+="]"

    # Build tracking files array
    TRACKING_JSON="["
    FIRST=true
    while IFS= read -r tf; do
        [[ -z "$tf" ]] && continue
        if $FIRST; then FIRST=false; else TRACKING_JSON+=","; fi
        TRACKING_JSON+="\"$(json_escape "$tf")\""
    done < <(find_tracking_files)
    TRACKING_JSON+="]"

    # Build common sections array
    SECTIONS_JSON="["
    FIRST=true
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        count=$(printf '%s\n' "$line" | awk '{print $1}')
        section=$(printf '%s\n' "$line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')
        is_number "$count" || continue
        if $FIRST; then FIRST=false; else SECTIONS_JSON+=","; fi
        SECTIONS_JSON+="{\"section\":\"$(json_escape "$section")\",\"count\":$count}"
    done < <(extract_common_sections "$SPEC_DIR")
    SECTIONS_JSON+="]"

    SPEC_DIR_ESC=$(json_escape "${SPEC_DIR:-none}")
    NAMING_ESC=$(json_escape "$NAMING_PATTERN")
    SAMPLE_ESC=$(json_escape "${SAMPLE_SPEC:-none}")

    cat <<ENDJSON
{
  "specDir": "$SPEC_DIR_ESC",
  "specCount": $SPEC_COUNT,
  "epicStructure": "$EPIC_STRUCTURE",
  "namingPattern": "$NAMING_ESC",
  "sampleSpec": "$SAMPLE_ESC",
  "epics": $EPIC_JSON,
  "skippedEpics": $SKIPPED_JSON,
  "trackingFiles": $TRACKING_JSON,
  "commonSections": $SECTIONS_JSON
}
ENDJSON

else
    echo "=== Project Spec Conventions ==="
    echo ""
    echo "Spec directory:    ${SPEC_DIR:-NOT FOUND}"
    echo "Total specs:       $SPEC_COUNT"
    echo "Epic structure:    $EPIC_STRUCTURE"
    echo "Naming pattern:    $NAMING_PATTERN"
    echo "Sample spec:       ${SAMPLE_SPEC:-none}"
    echo ""

    echo "--- Epics ---"
    while IFS= read -r epic; do
        [[ -z "$epic" ]] && continue
        latest=$(find_latest_story_number "$SPEC_DIR" "$epic")
        is_number "$latest" && [[ ${#latest} -le 9 ]] || latest="0"
        next=$((10#$latest + 1))
        latest=$((10#$latest))
        echo "  Epic $epic: latest story = $epic.$latest, next = $epic.$next"
    done < <(find_epics "$SPEC_DIR")
    echo ""

    echo "--- Tracking Files ---"
    find_tracking_files | sed 's/^/  /'
    echo ""

    echo "--- Common Sections (frequency across specs) ---"
    extract_common_sections "$SPEC_DIR" | sed 's/^/  /'
    echo ""
fi
