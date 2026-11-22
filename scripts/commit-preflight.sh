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
PROJECT_KEY="$(git -C "$PROJECT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [ -n "$PROJECT_KEY" ] && [ -d "$PROJECT_KEY" ]; then
    PROJECT_KEY="$(cd "$PROJECT_KEY" && pwd -P)"
else
    PROJECT_KEY="$(realpath "$PROJECT_DIR")"
fi
PROJECT_HASH=$(python3 -c "import hashlib, sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:8])" "$PROJECT_KEY")
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

# What this run checks, recorded in the token. Ported from the harden-repo
# 1.3.2 template (#335): its require-preflight.py refuses a token without
# "head", "tree" and "worktree", and keeps a token across commit calls only
# while HEAD, the staged tree and this checkout all still match it. The tree
# is read here, before any check runs, and again just before the token is
# written, so a check that stages a file cannot leave a token naming a tree
# nobody checked. HEAD is empty on an unborn branch. The tree is read before
# the staged file list, and the list is built from the captured tree, so the
# list and the token describe the same tree.
TOKEN_HEAD=$(git rev-parse --verify -q HEAD 2>/dev/null || true)
if ! _wt_out=$(git write-tree 2>&1) || ! [[ "$_wt_out" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; then
    echo "❌ PREFLIGHT FAILED — cannot read the staged tree (git write-tree failed; unmerged files?)"
    printf '%s\n' "$_wt_out" | sed 's/^/   git: /' || true
    rm -f "$TOKEN_FILE"
    exit 1
fi
TOKEN_TREE=$_wt_out
if ! TOKEN_WORKTREE=$(git rev-parse --show-toplevel 2>/dev/null) || [ -z "$TOKEN_WORKTREE" ]; then
    echo "❌ PREFLIGHT FAILED — cannot read this checkout's toplevel"
    rm -f "$TOKEN_FILE"
    exit 1
fi

# Get staged files
if [ -n "$TOKEN_HEAD" ]; then
    _diff_base=$TOKEN_HEAD
else
    _diff_base=$(git hash-object -t tree /dev/null 2>/dev/null || true)
fi
STAGED_FILES=$(git diff --name-only --no-renames "$_diff_base" "$TOKEN_TREE" 2>/dev/null || echo "")

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

# Write the token: a temp file in the same directory, then a rename, so the
# hook never reads a half-written token. JSON comes from python, not a shell
# heredoc, because the worktree path may hold a quote or a backslash.
# Refuses (no token, exit 1) when the staged tree is no longer the one read
# before the checks.
# Args: created, staged file count, checks_run, skip_reason ("" for none).
_preflight_write_token() {
    local _tree_now
    if ! _tree_now=$(git write-tree 2>/dev/null) || [ "$_tree_now" != "$TOKEN_TREE" ]; then
        echo "❌ PREFLIGHT FAILED — the staged files changed while preflight ran; no token written."
        echo "   Stage everything first, then run preflight again."
        rm -f "$TOKEN_FILE"
        exit 1
    fi
    local _rc=0
    python3 -E - "$TOKEN_FILE" "$1" "$TOKEN_EXPIRY_SECONDS" "$2" "$3" "$4" \
        "$TOKEN_HEAD" "$TOKEN_TREE" "$TOKEN_WORKTREE" <<'PY' || _rc=$?
import fcntl, json, os, stat, sys, tempfile, time
path, created, ttl, staged, checks, reason, head, tree, worktree = sys.argv[1:10]
token = {"created": int(created), "expires": int(created) + int(ttl),
         "staged_files": int(staged), "checks_run": checks}
if reason:
    token["skip_reason"] = reason
token.update(head=head, tree=tree, worktree=os.path.realpath(worktree))
fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                           dir=os.path.dirname(path))
lock_fd = None
try:
    with os.fdopen(fd, "w") as handle:
        json.dump(token, handle, indent=4)
        handle.write("\n")
    # Take the same lock as require-preflight.py (_lock_token): same path,
    # same flags, same 2.0 s wait. A hook call that holds it is reading or
    # spending the token, so the new token is published only after it lets go.
    lock_fd = os.open(path + ".lock",
                      os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
        raise OSError("the lock file is not a regular file")
    give_up = time.monotonic() + 2.0
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= give_up:
                sys.exit(3)  # the except below removes tmp
            time.sleep(0.05)
    os.replace(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
finally:
    if lock_fd is not None:
        os.close(lock_fd)
PY
    if [ "$_rc" -eq 3 ]; then
        # Linked worktrees share one token path: another call may have just
        # published it, so it is left in place.
        echo "❌ PREFLIGHT FAILED — the preflight token is locked by a commit in progress; no token written. Retry in a few seconds."
        exit 1
    elif [ "$_rc" -ne 0 ]; then
        echo "❌ PREFLIGHT FAILED — could not write the token."
        rm -f "$TOKEN_FILE"
        exit 1
    fi
}

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

# ── Docs drift guard (always runs, --docs-only and --skip-tests too) ──
# The catalogue must match every plugin.json, and every link, repo path and
# plugin:skill name in the current docs must exist (#190). It checks what is
# being committed: the index, exported to a temp directory, with the
# check-docs.sh and checkers from that export. A fix left unstaged in the
# working tree does not hide drift in the commit.
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📚 Running docs drift guard on the staged tree..."
DOCS_EXPORT="$(mktemp -d)"
DOCS_RC=0
if ! git checkout-index -a --prefix="$DOCS_EXPORT/"; then
    echo "❌ Could not export the index for the docs drift guard"
    DOCS_RC=2
elif [ ! -f "$DOCS_EXPORT/scripts/check-docs.sh" ]; then
    echo "❌ scripts/check-docs.sh is not in the index"
    DOCS_RC=2
else
    bash "$DOCS_EXPORT/scripts/check-docs.sh" || DOCS_RC=$?
fi
if [ -n "$DOCS_EXPORT" ] && [ -d "$DOCS_EXPORT" ]; then
    rm -rf "$DOCS_EXPORT"
fi
if [ "$DOCS_RC" -ne 0 ]; then
    echo "❌ Docs drift guard failed on the staged tree. Fix the lines above and stage the fix;"
    echo "   for catalogue drift run: python3 plugins/skill-kit/skills/publish/scripts/catalogue.py ."
    rm -f "$TOKEN_FILE"
    exit 1
fi
echo ""

# Handle skip tests mode
if [ "$SKIP_TESTS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⏭️  SKIPPING TESTS"
    echo "   Reason: $SKIP_REASON"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    TIMESTAMP=$(date +%s)
    STAGED_COUNT=$(echo "$STAGED_FILES" | wc -l | tr -d ' ')
    _preflight_write_token "$TIMESTAMP" "$STAGED_COUNT" "skipped" "$SKIP_REASON"

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
_preflight_write_token "$TIMESTAMP" "$(echo "$STAGED_FILES" | wc -l | tr -d ' ')" "${CHECKS_RUN%,}" ""

echo ""
echo "✅ PREFLIGHT PASSED"
echo ""
echo "Token created (expires in ${TOKEN_EXPIRY_SECONDS}s)"
echo "📝 You may now run: git commit -m \"your message\""
echo ""
