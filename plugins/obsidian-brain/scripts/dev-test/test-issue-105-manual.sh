#!/usr/bin/env bash
# Manual smoke test for Issue #105 — _get_session_id_fast cwd-gone resilience
# Run AFTER: /dev-test install
# Usage: bash scripts/dev-test/test-issue-105-manual.sh
#
# Validates the parts that can be checked without a fresh CC session:
#   Phase A: _resolve_project_basename — happy / env-fallback / both-fail
#   Phase B: _recent_bootstrap_sid — zero / one / two / tmp-skip / stale
#   Phase C: _resolve_session_id end-to-end with REAL OS-level cwd deletion
#   Phase D: thin-wrapper contracts for _get_session_id_fast / _slow_path_newest_sid
#   Phase E: insight-saver bash prelude integration under wedged cwd
#
# For the live-CC steps (real worktree deletion, real /retro), see
# ./DEV-TEST-ISSUE-105.md.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }

CACHE_DIR=$(find ~/.claude/plugins/cache -type d -path "*/obsidian-brain/*" \
    -not -path "*.bak*" 2>/dev/null | sort -V | tail -1 | xargs dirname 2>/dev/null || true)
if [ -z "$CACHE_DIR" ] || [ ! -d "$CACHE_DIR" ]; then
    echo "❌ Could not locate obsidian-brain plugin cache."
    echo "   Run /dev-test install first."
    exit 1
fi

HOOK_DIR=$(find "$CACHE_DIR" -maxdepth 2 -type d -name hooks | sort -V | tail -1)
if [ -z "$HOOK_DIR" ] || [ ! -d "$HOOK_DIR" ] || [ ! -r "$HOOK_DIR/obsidian_utils.py" ]; then
    echo "❌ Could not locate a valid hooks directory in the obsidian-brain plugin cache."
    echo "   Expected a readable file at: $HOOK_DIR/obsidian_utils.py"
    echo "   Run /dev-test install first, or verify the plugin cache layout under:"
    echo "   $CACHE_DIR"
    exit 1
fi

# Sanity-check that the cache has the issue #105 functions before running
# Phase A-E. Without this, AttributeErrors get swallowed by the per-assertion
# `2>/dev/null` and surface as misleading "expected '<X>', got ''" failures.
PYTHONPATH="$HOOK_DIR" python3 -c \
    'import obsidian_utils; assert hasattr(obsidian_utils, "_resolve_project_basename"), "missing _resolve_project_basename"' \
    >/dev/null 2>&1 || {
    echo "❌ Plugin cache at $HOOK_DIR is missing issue #105 functions."
    echo "   Run /dev-test install in a sibling Claude Code session to sync"
    echo "   the feature branch into the cache, then re-run this script."
    exit 1
}

echo "═══════════════════════════════════════════════════════════════"
echo "Issue #105 — cwd-gone session-id resolution"
echo "═══════════════════════════════════════════════════════════════"
echo "Plugin cache: $CACHE_DIR"
echo "Hooks dir:    $HOOK_DIR"
echo ""

# Throwaway fixture root — isolated HOME so sid-* bootstraps don't pollute.
FIXTURE=$(mktemp -d -t ob-issue-105.XXXXXX)
trap 'cd "$HOME" 2>/dev/null; rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/home/.claude/obsidian-brain"
chmod 700 "$FIXTURE/home/.claude/obsidian-brain"

run_py() {
    # Run python3 with HOME and PYTHONPATH redirected so the installed
    # cache's obsidian_utils sees our fixture's secure dir.
    HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 "$@"
}

# ─── Phase A: _resolve_project_basename ───────────────────────────────
echo "Phase A: _resolve_project_basename"

# A1: happy path
mkdir -p "$FIXTURE/some-project"
A1=$(cd "$FIXTURE/some-project" && run_py -c \
    'import obsidian_utils; print(obsidian_utils._resolve_project_basename())' 2>/dev/null || true)
if [ "$A1" = "some-project" ]; then
    pass "A1 happy path returns cwd basename"
else
    fail "A1 happy path: expected 'some-project', got '$A1'"
fi

# A2: env fallback (cwd raises → CLAUDE_PROJECT_DIR basename)
A2=$(CLAUDE_PROJECT_DIR="/tmp/fake-dir/my-proj" run_py -c '
import os, obsidian_utils
def _raise(*a, **kw): raise FileNotFoundError("cwd")
os.getcwd = _raise
print(obsidian_utils._resolve_project_basename())
' 2>/dev/null || true)
if [ "$A2" = "my-proj" ]; then
    pass "A2 env-fallback returns CLAUDE_PROJECT_DIR basename"
else
    fail "A2 env-fallback: expected 'my-proj', got '$A2'"
fi

# A3: both unavailable → None
A3=$(unset CLAUDE_PROJECT_DIR; run_py -c '
import os, obsidian_utils
def _raise(*a, **kw): raise FileNotFoundError("cwd")
os.getcwd = _raise
print(repr(obsidian_utils._resolve_project_basename()))
' 2>/dev/null || true)
if [ "$A3" = "None" ]; then
    pass "A3 both-fail returns None"
else
    fail "A3 both-fail: expected 'None', got '$A3'"
fi
echo ""

# ─── Phase B: _recent_bootstrap_sid ───────────────────────────────────
echo "Phase B: _recent_bootstrap_sid"

BDIR="$FIXTURE/home/.claude/obsidian-brain"

# B1: zero recent files → None
rm -f "$BDIR"/sid-*  # ensure clean
B1=$(run_py -c \
    'import obsidian_utils; print(repr(obsidian_utils._recent_bootstrap_sid()))' 2>/dev/null || true)
if [ "$B1" = "None" ]; then
    pass "B1 zero-recent returns None"
else
    fail "B1 zero-recent: expected 'None', got '$B1'"
fi

# B2: exactly one recent → returns the SID
echo -n "test-sid-b2" > "$BDIR/sid-projB2"
B2=$(run_py -c \
    'import obsidian_utils; print(obsidian_utils._recent_bootstrap_sid())' 2>/dev/null || true)
if [ "$B2" = "test-sid-b2" ]; then
    pass "B2 exactly-one returns SID"
else
    fail "B2 exactly-one: expected 'test-sid-b2', got '$B2'"
fi

# B3: two recent → None (strict)
echo -n "test-sid-b3" > "$BDIR/sid-projB3"
B3=$(run_py -c \
    'import obsidian_utils; print(repr(obsidian_utils._recent_bootstrap_sid()))' 2>/dev/null || true)
if [ "$B3" = "None" ]; then
    pass "B3 two-recent returns None (strict)"
else
    fail "B3 two-recent: expected 'None', got '$B3'"
fi

# B4: tmp partial alongside one recent → still exactly-one
rm -f "$BDIR"/sid-*
echo -n "test-sid-b4" > "$BDIR/sid-projB4"
echo -n "garbage" > "$BDIR/.ob-sid-b4.tmp"
B4=$(run_py -c \
    'import obsidian_utils; print(obsidian_utils._recent_bootstrap_sid())' 2>/dev/null || true)
if [ "$B4" = "test-sid-b4" ]; then
    pass "B4 tmp-partial skipped"
else
    fail "B4 tmp-partial: expected 'test-sid-b4', got '$B4'"
fi

# B5: stale (mtime > window seconds ago) → None
rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
echo -n "test-sid-b5" > "$BDIR/sid-projB5"
# Set mtime to 700 seconds ago (window default = 600)
touch -t "$(date -v-700S +%Y%m%d%H%M.%S 2>/dev/null || date -d '700 seconds ago' +%Y%m%d%H%M.%S)" "$BDIR/sid-projB5"
B5=$(run_py -c \
    'import obsidian_utils; print(repr(obsidian_utils._recent_bootstrap_sid()))' 2>/dev/null || true)
if [ "$B5" = "None" ]; then
    pass "B5 stale-mtime returns None"
else
    fail "B5 stale-mtime: expected 'None', got '$B5'"
fi
echo ""

# ─── Phase C: _resolve_session_id with REAL cwd deletion ──────────────
echo "Phase C: _resolve_session_id (real OS deletion)"

# Each Phase C assertion runs in a subshell so cwd-deletion fallout doesn't
# wedge the parent script.

# C1: cwd-gone + recent bootstrap → returns SID
C1=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    echo -n "test-sid-c1" > "$BDIR/sid-projC1"
    (
        TMP=$(mktemp -d -t ob-c1.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"  # cwd is now gone
        unset CLAUDE_PROJECT_DIR
        HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; print(obsidian_utils._resolve_session_id())' 2>/dev/null || true
    )
)
if [ "$C1" = "test-sid-c1" ]; then
    pass "C1 cwd-gone + recent bootstrap → SID via layer 4"
else
    fail "C1 cwd-gone + bootstrap: expected 'test-sid-c1', got '$C1'"
fi

# C2: cwd-gone + no recent bootstrap → 'unknown'
C2=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    (
        TMP=$(mktemp -d -t ob-c2.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"
        unset CLAUDE_PROJECT_DIR
        HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; print(obsidian_utils._resolve_session_id())' 2>/dev/null || true
    )
)
if [ "$C2" = "unknown" ]; then
    pass "C2 cwd-gone + no bootstrap → 'unknown'"
else
    fail "C2 cwd-gone + no bootstrap: expected 'unknown', got '$C2'"
fi

# C3: cwd-gone + CLAUDE_PROJECT_DIR set + matching JSONL → returns via slow path
C3=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    PROJ="projC3"
    CC_DIR="$FIXTURE/home/.claude/projects/-Users-test-$PROJ"
    mkdir -p "$CC_DIR"
    echo "{}" > "$CC_DIR/test-sid-c3.jsonl"
    (
        TMP=$(mktemp -d -t ob-c3.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"
        CLAUDE_PROJECT_DIR="/tmp/fake/$PROJ" HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; print(obsidian_utils._resolve_session_id())' 2>/dev/null || true
    )
)
if [ "$C3" = "test-sid-c3" ]; then
    pass "C3 cwd-gone + env + JSONL → SID via layer 1+3"
else
    fail "C3 cwd-gone + env + JSONL: expected 'test-sid-c3', got '$C3'"
fi

# C4: cwd valid + bootstrap valid → no behavior change (happy path)
C4=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    PROJ="projC4"
    CC_DIR="$FIXTURE/home/.claude/projects/-Users-test-$PROJ"
    mkdir -p "$CC_DIR"
    echo "{}" > "$CC_DIR/test-sid-c4.jsonl"
    echo -n "test-sid-c4" > "$BDIR/sid-$PROJ"
    mkdir -p "$FIXTURE/$PROJ"
    cd "$FIXTURE/$PROJ"
    HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
        'import obsidian_utils; print(obsidian_utils._resolve_session_id())' 2>/dev/null || true
)
if [ "$C4" = "test-sid-c4" ]; then
    pass "C4 happy path → SID via layer 2 (no behavior change)"
else
    fail "C4 happy path: expected 'test-sid-c4', got '$C4'"
fi
echo ""

# ─── Phase D: thin-wrapper contracts ──────────────────────────────────
echo "Phase D: thin-wrapper contracts unchanged"

# D1: _get_session_id_fast still callable, returns string
D1=$(cd "$FIXTURE" && run_py -c \
    'import obsidian_utils; r = obsidian_utils._get_session_id_fast(); print(type(r).__name__)' 2>/dev/null || true)
if [ "$D1" = "str" ]; then
    pass "D1 _get_session_id_fast returns str"
else
    fail "D1 _get_session_id_fast: expected 'str', got '$D1'"
fi

# D2: _slow_path_newest_sid still callable, returns string
D2=$(cd "$FIXTURE" && run_py -c \
    'import obsidian_utils; r = obsidian_utils._slow_path_newest_sid(); print(type(r).__name__)' 2>/dev/null || true)
if [ "$D2" = "str" ]; then
    pass "D2 _slow_path_newest_sid returns str"
else
    fail "D2 _slow_path_newest_sid: expected 'str', got '$D2'"
fi

# D3: 'unknown' sentinel preserved when no signal at all
rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
D3=$(cd "$FIXTURE/some-project" && run_py -c '
import obsidian_utils
print(obsidian_utils._slow_path_newest_sid())
' 2>/dev/null || true)
if [ "$D3" = "unknown" ]; then
    pass "D3 'unknown' sentinel preserved"
else
    fail "D3 'unknown' sentinel: expected 'unknown', got '$D3'"
fi
echo ""

# ─── Phase E: insight-saver bash prelude under wedged cwd ─────────────
echo "Phase E: insight-saver bash prelude integration"

# Replicates the exact bash prelude from compress/decide/error-log/retro
# SKILL.md: cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; python3 -c '...'

# E1: bash prelude under wedged cwd + recent bootstrap → real SID (NOT 'unknown')
E1=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    echo -n "test-sid-e1" > "$BDIR/sid-projE1"
    (
        TMP=$(mktemp -d -t ob-e1.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"
        unset CLAUDE_PROJECT_DIR
        # Defensive variant of the SKILL.md prelude (the SKILL.md form is
        # `cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"`; here we
        # add `|| echo /` so the cd lands at / instead of no-op'ing under
        # `set -euo pipefail` + wedged-cwd, allowing python3 to launch and
        # exercise the resolver chain — that's what we're actually testing).
        cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd 2>/dev/null || echo /)" 2>/dev/null
        HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; print(obsidian_utils._get_session_id_fast())' 2>/dev/null || true
    )
)
if [ "$E1" = "test-sid-e1" ]; then
    pass "E1 bash prelude + cwd-gone + bootstrap → real SID (no metadata loss)"
else
    fail "E1 bash prelude integration: expected 'test-sid-e1', got '$E1'"
fi

# E2: same scenario without recent bootstrap → 'unknown' (graceful, no crash)
E2=$(
    rm -f "$BDIR"/sid-* "$BDIR"/.ob-sid-*.tmp
    (
        TMP=$(mktemp -d -t ob-e2.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"
        unset CLAUDE_PROJECT_DIR
        cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd 2>/dev/null || echo /)" 2>/dev/null
        HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; print(obsidian_utils._get_session_id_fast())' 2>/dev/null || true
    )
)
if [ "$E2" = "unknown" ]; then
    pass "E2 bash prelude + cwd-gone + no bootstrap → 'unknown' (graceful)"
else
    fail "E2 bash prelude graceful: expected 'unknown', got '$E2'"
fi

# E3: confirm Python subprocess exits cleanly (no traceback bleed)
E3_EXIT=$(
    (
        TMP=$(mktemp -d -t ob-e3.XXXXXX)
        cd "$TMP"
        rmdir "$TMP"
        unset CLAUDE_PROJECT_DIR
        cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd 2>/dev/null || echo /)" 2>/dev/null
        HOME="$FIXTURE/home" PYTHONPATH="$HOOK_DIR" python3 -c \
            'import obsidian_utils; obsidian_utils._get_session_id_fast()' >/dev/null 2>&1
        echo $?
    )
)
if [ "$E3_EXIT" = "0" ]; then
    pass "E3 Python exits cleanly under wedged cwd (no FileNotFoundError)"
else
    fail "E3 Python exit: expected 0, got $E3_EXIT"
fi
echo ""

# ─── Summary ──────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo "Issue #105 fixture: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════════════"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
