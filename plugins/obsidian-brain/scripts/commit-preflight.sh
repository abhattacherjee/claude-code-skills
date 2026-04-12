#!/bin/bash
# Commit Preflight Check
# Must be run before git commit to verify tests pass.
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

# ── Plugin manifest version sync (ALWAYS runs, even in skip modes) ──
# Must run BEFORE the --docs-only / --skip-tests / --auto early-exit
# below — those skip modes intentionally bypass tests, but version
# drift between plugin.json and marketplace.json must NEVER be skipped
# regardless of flag. This is the gate that catches the bug PR #14
# was opened to fix; if it lives below the early-exit it provides
# zero protection against any user who runs preflight with a skip flag
# (Copilot iter-4 finding on PR #14).
PLUGIN_JSON_PRE="$PROJECT_DIR/.claude-plugin/plugin.json"
MARKETPLACE_JSON_PRE="$PROJECT_DIR/.claude-plugin/marketplace.json"
VERSION_SYNC_RAN=false
if [ -f "$PLUGIN_JSON_PRE" ] && [ -f "$MARKETPLACE_JSON_PRE" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔖 Checking plugin manifest version sync..."
    VERSION_SYNC_EXIT=0
    VERSION_CHECK_TMP=$(mktemp "${TMPDIR:-/tmp}/preflight-version.XXXXXX")
    VERSION_CHECK_STDOUT=$(python3 - "$PLUGIN_JSON_PRE" "$MARKETPLACE_JSON_PRE" 2>"$VERSION_CHECK_TMP" <<'PY'
import json, sys, traceback
plugin_path, market_path = sys.argv[1], sys.argv[2]
try:
    plugin = json.load(open(plugin_path))
    market = json.load(open(market_path))
except Exception as e:
    sys.stderr.write(f"parse error: {e}\n")
    sys.exit(2)
plugin_v = plugin.get("version")
plugin_name = plugin.get("name")
if not plugin_v or not plugin_name:
    sys.stderr.write("plugin.json missing 'name' or 'version'\n")
    sys.exit(2)
try:
    entries = [p for p in market.get("plugins", []) if p.get("name") == plugin_name]
    if not entries:
        sys.stderr.write(f"marketplace.json has no entry for '{plugin_name}'\n")
        sys.exit(2)
    mismatches = []
    for idx, entry in enumerate(entries):
        market_v = entry.get("version")
        if market_v is None:
            sys.stderr.write(
                f"marketplace.json entry #{idx} for '{plugin_name}' has no 'version' field\n"
            )
            sys.exit(2)
        if market_v != plugin_v:
            mismatches.append((idx, market_v))
    if mismatches:
        details = ", ".join(f"entry#{i}={v}" for i, v in mismatches)
        print(f"MISMATCH: plugin.json={plugin_v} marketplace.json={details}")
        sys.exit(1)
    suffix = "" if len(entries) == 1 else f" ({len(entries)} entries)"
    print(f"OK: {plugin_name}@{plugin_v}{suffix}")
except Exception:
    sys.stderr.write("unexpected error during version sync check:\n")
    traceback.print_exc(file=sys.stderr)
    sys.exit(2)
PY
) || VERSION_SYNC_EXIT=$?
    VERSION_CHECK_STDERR=$(cat "$VERSION_CHECK_TMP" 2>/dev/null || true)
    rm -f "$VERSION_CHECK_TMP"
    if [ -n "$VERSION_CHECK_STDOUT" ]; then
        echo "$VERSION_CHECK_STDOUT"
    fi
    case "$VERSION_SYNC_EXIT" in
        0)
            VERSION_SYNC_RAN=true
            ;;
        1)
            echo ""
            echo "❌ Plugin manifest versions are out of sync."
            echo "   Update .claude-plugin/marketplace.json to match plugin.json,"
            echo "   or run ./scripts/bump-version.sh which updates both."
            echo "   This check runs even in --skip-tests modes."
            rm -f "$TOKEN_FILE"
            exit 1
            ;;
        *)
            echo ""
            echo "❌ Plugin manifest version check failed with a structural error:"
            if [ -n "$VERSION_CHECK_STDERR" ]; then
                echo "$VERSION_CHECK_STDERR" | sed 's/^/   /'
            else
                echo "   (no error output — python exited with code $VERSION_SYNC_EXIT)"
            fi
            echo "   Fix the manifest files before committing."
            rm -f "$TOKEN_FILE"
            exit 1
            ;;
    esac
    unset VERSION_SYNC_EXIT VERSION_CHECK_STDOUT VERSION_CHECK_STDERR VERSION_CHECK_TMP
    echo ""
fi

# Handle skip tests mode
if [ "$SKIP_TESTS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⏭️  SKIPPING TESTS"
    echo "   Reason: $SKIP_REASON"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Even in skip mode, version-sync must be recorded if it ran above
    # — it is the one check that is NEVER actually skipped. Use a
    # generic "skipped" marker for everything else (lint, secret scan,
    # tests are all skipped, not just tests) so the audit trail is
    # accurate (Copilot iter-5 finding on PR #14).
    SKIP_CHECKS_RUN="skipped"
    if [ "$VERSION_SYNC_RAN" = true ]; then
        SKIP_CHECKS_RUN="version-sync,skipped"
    fi
    TIMESTAMP=$(date +%s)
    TOKEN_DATA=$(cat <<EOF
{
    "created": $TIMESTAMP,
    "expires": $((TIMESTAMP + TOKEN_EXPIRY_SECONDS)),
    "staged_files": $(echo "$STAGED_FILES" | wc -l | tr -d ' '),
    "checks_run": "$SKIP_CHECKS_RUN",
    "skip_reason": "$(echo "$SKIP_REASON" | sed 's/\\/\\\\/g; s/"/\\"/g')"
}
EOF
)
    echo "$TOKEN_DATA" > "$TOKEN_FILE"

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

# Plugin manifest version sync was already verified above (before the
# skip-tests early-exit) so it cannot be bypassed by --docs-only,
# --skip-tests, or --auto. Record it in CHECKS_RUN for the normal-mode
# token bookkeeping.
if [ "$VERSION_SYNC_RAN" = true ]; then
    CHECKS_RUN="${CHECKS_RUN}version-sync,"
fi

# ══════════════════════════════════════════════════════════════
# LINT SECTION — customized by /harden-repo during installation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Running lint checks..."

# __HARDEN_LINT_START__
echo "⏭️  No linter detected — skipping lint"
# __HARDEN_LINT_END__

# ══════════════════════════════════════════════════════════════
# TEST SECTION — customized by /harden-repo during installation
# ══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 Running tests..."

# __HARDEN_TEST_START__
if [ -d "tests" ]; then
    if command -v pytest &>/dev/null; then
        echo "🧪 Running pytest with coverage..."
        if pytest tests/ -v --tb=short --cov=hooks --cov-report=term-missing --cov-fail-under=90; then
            CHECKS_RUN="${CHECKS_RUN}tests,"
        else
            echo "❌ Tests failed or coverage below 90%"
            CHECKS_PASSED=false
        fi
    else
        echo "❌ tests/ directory exists but pytest is not installed"
        echo "   Install with: pip install pytest pytest-cov"
        CHECKS_PASSED=false
    fi
else
    echo "⏭️  No test directory — skipping tests"
fi
# __HARDEN_TEST_END__

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
