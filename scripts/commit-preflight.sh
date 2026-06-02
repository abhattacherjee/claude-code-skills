#!/bin/bash
# Commit Preflight Check
# Must be run before git commit to verify quality checks pass.
# Creates a one-time token that the require-preflight.py hook validates.
#
# Usage:
#   ./scripts/commit-preflight.sh              # Full verification
#   ./scripts/commit-preflight.sh --docs-only  # Skip tests for docs changes
#   ./scripts/commit-preflight.sh --skip-tests "reason"  # Skip with reason
#   ./scripts/commit-preflight.sh --auto       # Auto-detect if tests needed
#
# Installed by /harden-repo
# Lint/test commands customized for this project during installation.

set -e

# Project-scoped token path (must match require-preflight.py)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_HASH=$(python3 -c "import hashlib, sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:8])" "$(realpath "$PROJECT_DIR")")
TOKEN_FILE="/tmp/.preflight-token-${PROJECT_HASH}"
TOKEN_EXPIRY_SECONDS=300  # Token valid for 5 minutes

# Parse arguments
SKIP_TESTS=false
SKIP_REASON=""
AUTO_DETECT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --docs-only)
            SKIP_TESTS=true
            SKIP_REASON="documentation-only changes"
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            SKIP_REASON="$2"
            shift 2
            ;;
        --auto)
            AUTO_DETECT=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--docs-only | --skip-tests \"reason\" | --auto]"
            exit 1
            ;;
    esac
done

echo "🔍 Running commit preflight checks..."
echo ""

# Get staged files
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo "⚠️  No staged files. Stage files first with 'git add'"
    exit 1
fi

echo "📁 Staged files:"
echo "$STAGED_FILES" | head -10
TOTAL=$(echo "$STAGED_FILES" | wc -l | tr -d ' ')
if [ "$TOTAL" -gt 10 ]; then
    echo "   ... and $((TOTAL - 10)) more"
fi
echo ""

# Auto-detect if tests are needed
if [ "$AUTO_DETECT" = true ]; then
    NON_DOC_FILES=$(echo "$STAGED_FILES" | grep -vE '\.(md|txt|json|yaml|yml)$|^docs/|^specs/|^\.claude/|^README|^LICENSE|^\.gitignore' || true)
    if [ -z "$NON_DOC_FILES" ]; then
        echo "📄 Auto-detected: Documentation/config changes only"
        SKIP_TESTS=true
        SKIP_REASON="auto-detected docs/config only"
    else
        echo "🔧 Auto-detected: Code changes present - running tests"
    fi
    echo ""
fi

# Handle skip tests mode
if [ "$SKIP_TESTS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⏭️  SKIPPING TESTS"
    echo "   Reason: $SKIP_REASON"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    TIMESTAMP=$(date +%s)
    STAGED_COUNT=$(echo "$STAGED_FILES" | wc -l | tr -d ' ')
    python3 -c "
import json, sys
token = {
    'created': int(sys.argv[1]),
    'expires': int(sys.argv[1]) + int(sys.argv[2]),
    'staged_files': int(sys.argv[3]),
    'checks_run': 'skipped',
    'skip_reason': sys.argv[4]
}
print(json.dumps(token, indent=4))
" "$TIMESTAMP" "$TOKEN_EXPIRY_SECONDS" "$STAGED_COUNT" "$SKIP_REASON" > "$TOKEN_FILE"

    echo "✅ PREFLIGHT PASSED (tests skipped)"
    echo "📝 You may now run: git commit -m \"your message\""
    echo ""
    exit 0
fi

# Track what we checked
CHECKS_RUN=""
CHECKS_PASSED=true

# ── Secret scanning (always runs) ────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 Running secret scan..."
if ./scripts/pre-commit.sh; then
    CHECKS_RUN="${CHECKS_RUN}secrets,"
else
    echo "❌ Secret scan failed"
    CHECKS_PASSED=false
fi

# ══════════════════════════════════════════════════════════════
# LINT SECTION — customized by /harden-repo during installation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Running lint checks..."

echo "⏭️  No linter detected — skipping lint"

# ══════════════════════════════════════════════════════════════
# TEST SECTION — customized by /harden-repo during installation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 Running tests..."

# This repo's quality gate is the validate scripts. Mirror CI's changed-dirs
# approach: validate ONLY the skill/plugin dirs that have staged changes.
VALIDATE_FAILED=false
VALIDATED_ANY=false
SKILL_DIRS=""
PLUGIN_DIRS=""

# Derive the skill/plugin dirs to validate from the staged file list.
for path in $STAGED_FILES; do
    # Skill dir = nearest ancestor directory containing a SKILL.md.
    dir="$(dirname "$path")"
    while [ "$dir" != "." ] && [ "$dir" != "/" ]; do
        if [ -f "$dir/SKILL.md" ]; then
            SKILL_DIRS="${SKILL_DIRS}${dir}"$'\n'
            break
        fi
        dir="$(dirname "$dir")"
    done

    # Plugin dir = plugins/<name> when that dir has a plugin manifest.
    case "$path" in
        plugins/*/*)
            plugin_dir="plugins/$(echo "$path" | cut -d/ -f2)"
            if [ -f "$plugin_dir/.claude-plugin/plugin.json" ]; then
                PLUGIN_DIRS="${PLUGIN_DIRS}${plugin_dir}"$'\n'
            fi
            ;;
    esac
done

# Dedupe the dir sets.
SKILL_DIRS="$(printf '%s' "$SKILL_DIRS" | grep -v '^$' | sort -u || true)"
PLUGIN_DIRS="$(printf '%s' "$PLUGIN_DIRS" | grep -v '^$' | sort -u || true)"

if [ -z "$SKILL_DIRS" ] && [ -z "$PLUGIN_DIRS" ]; then
    echo "ℹ️  No skill/plugin changes staged — skipping validation"
else
    while IFS= read -r skill_dir; do
        [ -z "$skill_dir" ] && continue
        if [ -f "$skill_dir/SKILL.md" ]; then
            VALIDATED_ANY=true
            if ! ./scripts/validate-skill.sh "$skill_dir" > /dev/null 2>&1; then
                echo "❌ Skill validation failed: $skill_dir"
                VALIDATE_FAILED=true
            fi
        fi
    done <<< "$SKILL_DIRS"

    while IFS= read -r plugin_dir; do
        [ -z "$plugin_dir" ] && continue
        VALIDATED_ANY=true
        if ! ./scripts/validate-plugin.sh "$plugin_dir" > /dev/null 2>&1; then
            echo "❌ Plugin validation failed: $plugin_dir"
            VALIDATE_FAILED=true
        fi
    done <<< "$PLUGIN_DIRS"

    if [ "$VALIDATE_FAILED" = true ]; then
        echo "❌ Validation failed"
        CHECKS_PASSED=false
    elif [ "$VALIDATED_ANY" = true ]; then
        echo "✅ Staged skills and plugins pass validation"
        CHECKS_RUN="${CHECKS_RUN}validate,"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$CHECKS_PASSED" = false ]; then
    echo "❌ PREFLIGHT FAILED - Fix errors before committing"
    rm -f "$TOKEN_FILE"
    exit 1
fi

# Create confirmation token
TIMESTAMP=$(date +%s)
TOKEN_DATA=$(cat <<EOF
{
    "created": $TIMESTAMP,
    "expires": $((TIMESTAMP + TOKEN_EXPIRY_SECONDS)),
    "staged_files": $(echo "$STAGED_FILES" | wc -l | tr -d ' '),
    "checks_run": "${CHECKS_RUN%,}"
}
EOF
)

echo "$TOKEN_DATA" > "$TOKEN_FILE"

echo ""
echo "✅ PREFLIGHT PASSED"
echo ""
echo "Token created (expires in ${TOKEN_EXPIRY_SECONDS}s)"
echo "📝 You may now run: git commit -m \"your message\""
echo ""
