#!/usr/bin/env bash
# Manual smoke test for Phase 1: ACT-R Access Tracking + 7-Signal Scorer
# Run AFTER: /dev-test install + start a new CC session
# Usage: bash scripts/test-phase1-manual.sh

set -euo pipefail

DB="$HOME/.claude/obsidian-brain-vault.db"
PASS=0
FAIL=0
SKIP=0

pass() { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  ⏭️  $1"; SKIP=$((SKIP + 1)); }

echo "═══════════════════════════════════════════════════"
echo "Phase 1 Smoke Test: ACT-R Access Tracking"
echo "═══════════════════════════════════════════════════"
echo ""

# ─── Test 1: Schema ───────────────────────────────────
echo "Test 1: Schema migration"

if [ ! -f "$DB" ]; then
    fail "DB does not exist at $DB — run a vault operation first (e.g. /vault-search test)"
    echo "Aborting."
    exit 1
fi

if sqlite3 "$DB" ".tables" | grep -q "access_log"; then
    pass "access_log table exists"
else
    fail "access_log table missing"
fi

if sqlite3 "$DB" "PRAGMA table_info(notes)" | grep -q "importance"; then
    pass "importance column exists on notes table"
else
    fail "importance column missing"
fi

IDX=$(sqlite3 "$DB" ".indices access_log" 2>/dev/null || echo "")
if echo "$IDX" | grep -q "idx_access_note"; then
    pass "idx_access_note index exists"
else
    fail "idx_access_note index missing"
fi
if echo "$IDX" | grep -q "idx_access_time"; then
    pass "idx_access_time index exists"
else
    fail "idx_access_time index missing"
fi

echo ""

# ─── Test 2: Access log has entries ───────────────────
echo "Test 2: Access logging"

TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log" 2>/dev/null || echo "0")
echo "  Current access_log entries: $TOTAL"

SEARCH_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log WHERE context_type='search'" 2>/dev/null || echo "0")
RECALL_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log WHERE context_type='recall'" 2>/dev/null || echo "0")
RELATED_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log WHERE context_type='related'" 2>/dev/null || echo "0")

echo "  Breakdown: search=$SEARCH_COUNT, recall=$RECALL_COUNT, related=$RELATED_COUNT"

if [ "$TOTAL" -gt 0 ]; then
    pass "Access log has entries (run /vault-search and /recall to populate more)"
else
    skip "Access log empty — run /vault-search and /recall first, then re-run this script"
fi

# Check project is populated
WITH_PROJECT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM access_log WHERE project IS NOT NULL" 2>/dev/null || echo "0")
if [ "$TOTAL" -gt 0 ] && [ "$WITH_PROJECT" -gt 0 ]; then
    pass "Access log entries have project field populated ($WITH_PROJECT/$TOTAL)"
elif [ "$TOTAL" -gt 0 ]; then
    fail "Access log entries have no project field populated"
fi

echo ""

# ─── Test 3: Importance column ────────────────────────
echo "Test 3: Importance scoring"

NON_DEFAULT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes WHERE importance != 5" 2>/dev/null || echo "0")
TOTAL_NOTES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM notes" 2>/dev/null || echo "0")
echo "  Notes with non-default importance: $NON_DEFAULT / $TOTAL_NOTES"

if [ "$NON_DEFAULT" -gt 0 ]; then
    pass "Some notes have importance != 5 (scoring is active)"
    sqlite3 "$DB" "SELECT importance, substr(path, -40) FROM notes WHERE importance != 5 ORDER BY importance DESC LIMIT 5" 2>/dev/null || true
else
    skip "All notes have default importance=5 — will populate when /recall upgrades unsummarized notes"
fi

echo ""

# ─── Test 4: Importance preserved on re-index ─────────
echo "Test 4: Importance preservation"

# Pick a note and set importance to 9
TEST_NOTE=$(sqlite3 "$DB" "SELECT path FROM notes LIMIT 1" 2>/dev/null || echo "")
if [ -z "$TEST_NOTE" ]; then
    skip "No notes in DB — cannot test importance preservation"
else
    # Save original value
    ORIG_IMP=$(sqlite3 "$DB" "SELECT importance FROM notes WHERE path = '$TEST_NOTE'" 2>/dev/null || echo "5")

    # Set to 9
    sqlite3 "$DB" "UPDATE notes SET importance = 9 WHERE path = '$TEST_NOTE'"
    BEFORE=$(sqlite3 "$DB" "SELECT importance FROM notes WHERE path = '$TEST_NOTE'")

    if [ "$BEFORE" != "9" ]; then
        fail "Could not set importance to 9"
    else
        # Trigger re-index by touching the note (bump mtime)
        if [ -f "$TEST_NOTE" ]; then
            touch "$TEST_NOTE"
            # Run ensure_index via Python
            python3 -c "
import sys, os, glob
sys.path.insert(0, max(glob.glob(os.path.expanduser('~/.claude/plugins/cache/*/obsidian-brain/*/hooks')), default='hooks'))
from obsidian_utils import load_config
from vault_index import ensure_index
c = load_config()
ensure_index(c['vault_path'], [c.get('sessions_folder', 'claude-sessions'), c.get('insights_folder', 'claude-insights')])
" 2>/dev/null

            AFTER=$(sqlite3 "$DB" "SELECT importance FROM notes WHERE path = '$TEST_NOTE'" 2>/dev/null || echo "?")
            if [ "$AFTER" = "9" ]; then
                pass "Importance preserved after re-index (9 → $AFTER)"
            else
                fail "Importance reset after re-index (9 → $AFTER)"
            fi
        else
            skip "Note file not found on disk — cannot test re-index preservation"
        fi

        # Restore original value
        sqlite3 "$DB" "UPDATE notes SET importance = $ORIG_IMP WHERE path = '$TEST_NOTE'" 2>/dev/null || true
    fi
fi

echo ""

# ─── Test 5: SKILL.md has IMPORTANCE prompt ───────────
echo "Test 5: IMPORTANCE in SKILL.md"

SKILL_PATH=$(find ~/.claude/plugins/cache -path "*/obsidian-brain/*/skills/recall/SKILL.md" -not -path "*.bak*" 2>/dev/null | sort -V | tail -1)
if [ -z "$SKILL_PATH" ]; then
    fail "recall SKILL.md not found in plugin cache"
else
    IMP_COUNT=$(grep -c "IMPORTANCE" "$SKILL_PATH" 2>/dev/null || echo "0")
    if [ "$IMP_COUNT" -ge 2 ]; then
        pass "IMPORTANCE keyword found $IMP_COUNT times in recall SKILL.md"
    else
        fail "IMPORTANCE keyword found only $IMP_COUNT times (expected >= 2)"
    fi
fi

echo ""

# ─── Test 6: stderr logging (non-destructive) ────────
echo "Test 6: stderr logging on bad DB"

HOOKS_PATH=$(find ~/.claude/plugins/cache -path "*/obsidian-brain/*/hooks" -type d -not -path "*.bak*" 2>/dev/null | sort -V | tail -1)
if [ -z "$HOOKS_PATH" ]; then
    HOOKS_PATH="hooks"
fi

STDERR_OUTPUT=$(python3 -c "
import sys, os
sys.path.insert(0, '$HOOKS_PATH')
import vault_index
vault_index.log_access('/tmp/nonexistent-dir-phase1-test/fake.db', '/test', 'test')
" 2>&1 || true)

if echo "$STDERR_OUTPUT" | grep -q "vault-index.*log_access failed"; then
    pass "log_access logs to stderr on bad DB"
else
    fail "log_access did not log to stderr (got: '$STDERR_OUTPUT')"
fi

STDERR_OUTPUT2=$(python3 -c "
import sys, os
sys.path.insert(0, '$HOOKS_PATH')
import vault_index
result = vault_index.batch_activations('/tmp/nonexistent-dir-phase1-test/fake.db', ['/test'])
print(result, file=sys.stderr)
" 2>&1 || true)

if echo "$STDERR_OUTPUT2" | grep -q "0.0"; then
    pass "batch_activations returns 0.0 on bad DB"
else
    fail "batch_activations unexpected output: '$STDERR_OUTPUT2'"
fi

echo ""

# ─── Test 7: Recent access log entries ────────────────
echo "Test 7: Recent access log entries"

RECENT=$(sqlite3 "$DB" "SELECT note_path, context_type, project, datetime(timestamp, 'unixepoch', 'localtime') FROM access_log ORDER BY timestamp DESC LIMIT 5" 2>/dev/null || echo "")
if [ -n "$RECENT" ]; then
    pass "Recent access log entries:"
    echo "$RECENT" | while IFS='|' read -r path ctx proj ts; do
        echo "    $ts | $ctx | $proj | ...${path: -50}"
    done
else
    skip "No recent entries — run /vault-search and /recall first"
fi

echo ""

# ─── Summary ──────────────────────────────────────────
echo "═══════════════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
echo "═══════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "⚠️  Some tests failed. Investigate before merging."
    exit 1
elif [ "$SKIP" -gt 0 ]; then
    echo ""
    echo "💡 Some tests skipped — run /vault-search and /recall in a"
    echo "   fresh CC session, then re-run this script to verify those."
    exit 0
else
    echo ""
    echo "🎉 All tests passed!"
    exit 0
fi
