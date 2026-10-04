#!/usr/bin/env bash
set -eu

# extract-spec-sections.sh — Parses a story spec into structured sections
# for parallel agent analysis.
#
# Usage:
#   extract-spec-sections.sh <spec-file>           # Human-readable report
#   extract-spec-sections.sh <spec-file> --json     # JSON for agent consumption
#   extract-spec-sections.sh --help

# Resolve repo root from git (works regardless of where the script lives)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <spec-file> [--json]

Extracts key sections from a story specification file for parallel agent analysis.

Arguments:
  spec-file    Path to the story spec .md file (absolute, relative to the current
               directory, or relative to the repo root; the current directory wins)
  --json       Output as JSON (for agent consumption)
  --help       Show this help

Examples:
  $(basename "$0") specs/stories/epic-6/story-6.11-google-places-catalog.md
  $(basename "$0") specs/stories/epic-6/story-6.11-google-places-catalog.md --json

Extracted sections:
  - Title and metadata (epic, priority, status, dependencies)
  - User story
  - Acceptance criteria (with checkbox status)
  - Sub-tasks (with file references)
  - Referenced files (paths mentioned in the spec)
  - Referenced endpoints (API routes and MCP tools)
  - Testing sections (unit, Bruno, E2E)
  - Current codebase state (if present)
EOF
    exit 0
}

# Argument parsing
[[ $# -lt 1 ]] && { echo "Error: spec file required. Use --help for usage." >&2; exit 2; }
[[ "$1" == "--help" || "$1" == "-h" ]] && usage

SPEC_FILE="$1"
JSON_MODE=false
[[ "${2:-}" == "--json" ]] && JSON_MODE=true

# Resolve relative paths: against the current directory first, then the repo root.
# (It used to try only the repo root, so a path typed from a subdirectory was not
# found, or, worse, matched a different file of the same name at the repo root.)
if [[ ! "$SPEC_FILE" = /* ]]; then
    if [[ -f "$SPEC_FILE" ]]; then
        SPEC_FILE="$(pwd)/$SPEC_FILE"
    else
        SPEC_FILE="$REPO_ROOT/$SPEC_FILE"
    fi
fi

if [[ ! -f "$SPEC_FILE" ]]; then
    echo "Error: File not found: $SPEC_FILE" >&2
    exit 1
fi

if [[ ! -r "$SPEC_FILE" ]]; then
    echo "Error: cannot read: $SPEC_FILE" >&2
    exit 1
fi

# --- Section extraction functions ---

extract_title() {
    head -1 "$SPEC_FILE" | sed 's/^# //'
}

extract_metadata() {
    # Extract bold key-value pairs after the H1 title
    sed -n '2,/^##/p' "$SPEC_FILE" | grep '^\*\*' | sed 's/\*\*//g' | head -10
}

extract_user_story() {
    sed -n '/\*\*As a\*\*/,/^$/p' "$SPEC_FILE" | head -10
}

extract_acceptance_criteria() {
    # Find the AC section — supports two common formats:
    #   1. Checkbox items:  - [ ] criterion text
    #   2. AC sub-headings: ### AC1: criterion title
    local ac_section
    ac_section=$(sed -n '/^## Acceptance Criteria/,/^## [^A]/p' "$SPEC_FILE")

    # Try checkbox format first (most common across projects)
    local checkboxes
    checkboxes=$(echo "$ac_section" | grep -E '^\s*-\s*\[' | head -50)
    if [[ -n "$checkboxes" ]]; then
        echo "$checkboxes"
        return
    fi

    # Fall back to ### AC heading format (e.g., ### AC1: Title)
    local ac_headings
    ac_headings=$(echo "$ac_section" | grep -E '^### AC[0-9]+' | head -50)
    if [[ -n "$ac_headings" ]]; then
        echo "$ac_headings"
        return
    fi

    # Fall back to any ### headings within the AC section
    echo "$ac_section" | grep -E '^### ' | head -50
}

count_criteria() {
    local total checked unchecked
    total=$(extract_acceptance_criteria | wc -l | tr -d ' ')
    # Checkbox-style counts (only meaningful if checkboxes present)
    checked=$(extract_acceptance_criteria | grep -c '\[x\]' || true)
    unchecked=$(extract_acceptance_criteria | grep -c '\[ \]' || true)
    # If no checkboxes found, all criteria are "unchecked" (heading-style)
    if [[ "$checked" -eq 0 && "$unchecked" -eq 0 && "$total" -gt 0 ]]; then
        unchecked=$total
    fi
    echo "total=$total checked=$checked unchecked=$unchecked"
}

extract_subtasks() {
    # Extract sub-task headers — supports multiple naming conventions:
    #   - ### Sub-Task 1: Title
    #   - ### Task 1: Title
    #   - ### Phase 1: Title
    #   - ### 6.11.1 Title (X.Y.Z format)
    #   - ### AC1: Title (acceptance criteria as sub-tasks)
    #   - ### Step 1: Title
    grep -E '^### (Sub-Task|Task|Phase|Step|AC[0-9]|[0-9]+\.[0-9]+\.[0-9]+)' "$SPEC_FILE" | head -30
}

extract_referenced_files() {
    # Find all file path references (backticked paths ending in common extensions)
    grep -oE '`[a-zA-Z][a-zA-Z0-9/_.-]+\.(ts|js|tsx|jsx|json|bru|md|py|go|rs|rb|java|kt)`' "$SPEC_FILE" | \
        sort -u | sed 's/`//g'
}

extract_referenced_endpoints() {
    # Find API endpoints and tool paths
    # A bare path that also appears with a method ("POST /api/x" and "/api/x") is one endpoint.
    # Each grep ends with `|| true`: under `set -e` a grep that finds nothing would
    # otherwise end this group and drop the endpoints of the greps after it.
    {
        grep -oE '(GET|POST|PUT|PATCH|DELETE)\s+/[a-zA-Z0-9/:_.-]+' "$SPEC_FILE" || true
        grep -oE '/tools/[a-zA-Z0-9_-]+' "$SPEC_FILE" || true
        grep -oE '/api/[a-zA-Z0-9/:_.-]+' "$SPEC_FILE" || true
    } | sort -u | awk '
        { line[NR] = $0; if ($0 ~ /^(GET|POST|PUT|PATCH|DELETE)[ \t]+\//) { p = $0; sub(/^[A-Z]+[ \t]+/, "", p); covered[p] = 1 } }
        END { for (i = 1; i <= NR; i++) if (!(line[i] in covered)) print line[i] }'
}

extract_testing_section() {
    # Try common section names
    for section in "Testing Strategy" "Testing Checklist" "Testing" "Test Plan"; do
        local content
        content=$(sed -n "/^## ${section}/,/^## [^T]/p" "$SPEC_FILE" 2>/dev/null | head -40)
        if [[ -n "$content" ]]; then
            echo "$content"
            return
        fi
    done
}

extract_codebase_state() {
    sed -n '/^## Current Codebase State/,/^## /p' "$SPEC_FILE" | head -30
}

has_api_tests() {
    grep -qiE 'bruno|\.bru|postman|insomnia|api.test|api.spec' "$SPEC_FILE" && echo "yes" || echo "no"
}

has_codebase_state() {
    grep -q '^## Current Codebase State' "$SPEC_FILE" && echo "yes" || echo "no"
}

# --- Output ---

if $JSON_MODE; then
    TITLE=$(extract_title)
    CRITERIA_COUNTS=$(count_criteria)
    HAS_API_TESTS=$(has_api_tests)
    HAS_CODEBASE=$(has_codebase_state)
    FILE_COUNT=$(extract_referenced_files | wc -l | tr -d ' ')
    ENDPOINT_COUNT=$(extract_referenced_endpoints | wc -l | tr -d ' ')
    SUBTASK_COUNT=$(extract_subtasks | wc -l | tr -d ' ')

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

    TITLE_ESCAPED=$(json_escape "$TITLE")
    SPEC_FILE_ESCAPED=$(json_escape "$SPEC_FILE")

    cat <<ENDJSON
{
  "specFile": "$SPEC_FILE_ESCAPED",
  "title": "$TITLE_ESCAPED",
  "criteriaCounts": "$CRITERIA_COUNTS",
  "hasApiTests": "$HAS_API_TESTS",
  "hasCodebaseState": "$HAS_CODEBASE",
  "referencedFileCount": $FILE_COUNT,
  "referencedEndpointCount": $ENDPOINT_COUNT,
  "subtaskCount": $SUBTASK_COUNT,
  "gaps": {
    "missingCodebaseState": $([ "$HAS_CODEBASE" = "no" ] && echo "true" || echo "false"),
    "missingApiTests": $([ "$HAS_API_TESTS" = "no" ] && echo "true" || echo "false")
  }
}
ENDJSON
else
    echo "=== Spec Analysis: $(extract_title) ==="
    echo ""

    echo "--- Metadata ---"
    extract_metadata
    echo ""

    echo "--- User Story ---"
    extract_user_story
    echo ""

    echo "--- Acceptance Criteria ($(count_criteria)) ---"
    extract_acceptance_criteria
    echo ""

    echo "--- Sub-Tasks ($( extract_subtasks | wc -l | tr -d ' ') found) ---"
    extract_subtasks
    echo ""

    echo "--- Referenced Files ($(extract_referenced_files | wc -l | tr -d ' ') unique) ---"
    extract_referenced_files
    echo ""

    echo "--- Referenced Endpoints ---"
    extract_referenced_endpoints
    echo ""

    echo "--- Gaps ---"
    [[ "$(has_codebase_state)" == "no" ]] && echo "  MISSING: Current Codebase State section"
    [[ "$(has_api_tests)" == "no" ]] && echo "  MISSING: API Test Plan"
    echo ""

    echo "--- Testing Section ---"
    extract_testing_section
fi
