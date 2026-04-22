#!/usr/bin/env bash
# Manual smoke test for Snapshot Summary Integration (PR #43, Phase A + D)
# Run AFTER: /dev-test install + start a new Claude Code session
# Usage: bash scripts/dev-test/test-snapshots-manual.sh
#
# Validates what can be checked without live /compact or /recall:
#   - Plugin cache contains expected code and skill markers
#   - Python helpers (_snapshot_stats, fetch_snapshot_summaries,
#     find_snapshots_for_session, collect_vault_corpus default,
#     collect_open_items type filter, log_access cascade) behave correctly
#   - DB schema untouched (no new tables/columns required by this PR)
#
# For the live-session parts (/compact creates a snapshot, /recall nested
# rendering, /vault-search markers, /vault-stats Snapshots section),
# see ./DEV-TEST-SNAPSHOTS.md.

set -euo pipefail

DB="$HOME/.claude/obsidian-brain-vault.db"
PASS=0
FAIL=0
SKIP=0

pass() { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  ⏭️  $1"; SKIP=$((SKIP + 1)); }

# Locate the currently-installed plugin cache (the `dev-test install` target)
CACHE_DIR=$(find ~/.claude/plugins/cache -type d -path "*/obsidian-brain/*" \
    -not -path "*.bak*" 2>/dev/null | sort -V | tail -1 | xargs dirname 2>/dev/null || true)
if [ -z "$CACHE_DIR" ] || [ ! -d "$CACHE_DIR" ]; then
    echo "❌ Could not locate obsidian-brain plugin cache."
    echo "   Run /dev-test install first."
    exit 1
fi

HOOK_DIR=$(find "$CACHE_DIR" -maxdepth 2 -type d -name hooks | sort -V | tail -1)
SKILL_ROOT=$(find "$CACHE_DIR" -maxdepth 2 -type d -name skills | sort -V | tail -1)

echo "═══════════════════════════════════════════════════════════════"
echo "Snapshot Summary Integration — Automated Validation"
echo "═══════════════════════════════════════════════════════════════"
echo "Plugin cache: $CACHE_DIR"
echo "Hooks dir:    $HOOK_DIR"
echo "Skills dir:   $SKILL_ROOT"
echo ""

# ─── Test 1: Installed code surface ──────────────────────────────────
echo "Test 1: Installed code surface"

if grep -q "def fetch_snapshot_summaries" "$HOOK_DIR/obsidian_utils.py"; then
    pass "fetch_snapshot_summaries() present in obsidian_utils.py"
else
    fail "fetch_snapshot_summaries() missing — did /dev-test install pick up this branch?"
fi

if grep -q "def find_snapshots_for_session" "$HOOK_DIR/obsidian_utils.py"; then
    pass "find_snapshots_for_session() present (public name — no underscore)"
else
    fail "find_snapshots_for_session() missing"
fi

if grep -q "SNAPSHOT_SUMMARY_PROMPT" "$HOOK_DIR/obsidian_utils.py"; then
    pass "SNAPSHOT_SUMMARY_PROMPT constant present"
else
    fail "SNAPSHOT_SUMMARY_PROMPT constant missing"
fi

if grep -q "_augment_session_input_with_snapshots" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_augment_session_input_with_snapshots() present"
else
    fail "_augment_session_input_with_snapshots() missing"
fi

if grep -q "def _snapshot_stats" "$HOOK_DIR/vault_stats.py"; then
    pass "_snapshot_stats() present in vault_stats.py"
else
    fail "_snapshot_stats() missing"
fi

if grep -q "_parent_session_for_snapshot" "$HOOK_DIR/vault_index.py"; then
    pass "log_access cascade helper present"
else
    fail "log_access cascade helper missing"
fi

if grep -q "exclude_types.*claude-snapshot" "$HOOK_DIR/obsidian_utils.py"; then
    pass "collect_vault_corpus excludes claude-snapshot by default"
else
    fail "collect_vault_corpus default exclusion missing"
fi

echo ""

# ─── Test 2: Skill markers ──────────────────────────────────────────
echo "Test 2: Skill markers"

RECALL_SKILL="$SKILL_ROOT/recall/SKILL.md"
if [ -f "$RECALL_SKILL" ] && grep -q "snapshot_count" "$RECALL_SKILL"; then
    pass "/recall SKILL.md mentions snapshot_count (LOAD_MANIFEST key)"
else
    fail "/recall SKILL.md missing snapshot_count references"
fi

SEARCH_SKILL="$SKILL_ROOT/vault-search/SKILL.md"
if [ -f "$SEARCH_SKILL" ] && grep -q "📸" "$SEARCH_SKILL"; then
    pass "/vault-search SKILL.md has snapshot marker documentation"
else
    fail "/vault-search SKILL.md missing snapshot marker"
fi

ASK_SKILL="$SKILL_ROOT/vault-ask/SKILL.md"
if [ -f "$ASK_SKILL" ] && grep -q "source_session_note\|snapshot" "$ASK_SKILL"; then
    pass "/vault-ask SKILL.md mentions snapshot citation handling"
else
    fail "/vault-ask SKILL.md missing snapshot citation guidance"
fi

STATS_SKILL="$SKILL_ROOT/vault-stats/SKILL.md"
if [ -f "$STATS_SKILL" ] && grep -q "## Snapshots" "$STATS_SKILL"; then
    pass "/vault-stats SKILL.md has Snapshots rendering section"
else
    fail "/vault-stats SKILL.md missing Snapshots section"
fi

EMERGE_SKILL="$SKILL_ROOT/emerge/SKILL.md"
if [ -f "$EMERGE_SKILL" ] && grep -q "include-snapshots" "$EMERGE_SKILL"; then
    pass "/emerge SKILL.md documents --include-snapshots"
else
    fail "/emerge SKILL.md missing --include-snapshots flag"
fi

CHECKITEMS_SKILL="$SKILL_ROOT/check-items/SKILL.md"
if [ -f "$CHECKITEMS_SKILL" ] && grep -q "claude-session\|Scope:" "$CHECKITEMS_SKILL"; then
    pass "/check-items SKILL.md scope note present"
else
    fail "/check-items SKILL.md missing scope note"
fi

VAULTCFG_SKILL="$SKILL_ROOT/vault-config/SKILL.md"
if [ -f "$VAULTCFG_SKILL" ] && grep -q "snapshot_on_compact\|snapshot_on_clear" "$VAULTCFG_SKILL"; then
    pass "/vault-config SKILL.md exposes snapshot toggles"
else
    fail "/vault-config SKILL.md missing snapshot toggle rows"
fi

echo ""

# ─── Test 3: Python behavior — fixture vault ─────────────────────────
echo "Test 3: Python behavior against a fresh fixture vault"

# Build a throwaway vault in /tmp, exercise the helpers, clean up.
FIXTURE=$(mktemp -d -t ob-snapshot-test.XXXXXX)
trap "rm -rf '$FIXTURE'" EXIT

mkdir -p "$FIXTURE/v/claude-sessions" "$FIXTURE/v/claude-insights"

# Session note
cat > "$FIXTURE/v/claude-sessions/2026-04-18-demo-abcd.md" <<'EOF'
---
type: claude-session
date: 2026-04-18
session_id: s-abcd-1111
project: demo
status: summarized
---

# Demo Session

## Summary
A short session summary body.
EOF

# Snapshot backed by the session
cat > "$FIXTURE/v/claude-sessions/2026-04-18-demo-abcd-snapshot-140000.md" <<'EOF'
---
type: claude-snapshot
date: 2026-04-18
session_id: s-abcd-1111
project: demo
trigger: compact
status: summarized
source_session_note: "[[2026-04-18-demo-abcd]]"
---

# Snapshot

## Summary
Pre-compact snapshot body.
EOF

# Orphan snapshot (no matching session)
cat > "$FIXTURE/v/claude-sessions/2026-04-18-demo-zzzz-snapshot-180000.md" <<'EOF'
---
type: claude-snapshot
date: 2026-04-18
session_id: missing-parent
project: demo
trigger: compact
status: auto-logged
source_session_note: "[[does-not-exist]]"
---

# Orphan
EOF

FIXTURE_DB="$FIXTURE/fixture.db"

# --- 3a: find_snapshots_for_session picks up the snapshot by id ---
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os
sys.path.insert(0, "$HOOK_DIR")
from pathlib import Path
from obsidian_utils import find_snapshots_for_session
snaps = find_snapshots_for_session(
    Path("$FIXTURE/v/claude-sessions"),
    "s-abcd-1111",
    "2026-04-18",
    "demo",
)
print(len(snaps))
PY
)
if [ "$RESULT" = "1" ]; then
    pass "find_snapshots_for_session returns 1 snapshot for session s-abcd-1111"
else
    fail "find_snapshots_for_session returned '$RESULT' (expected 1)"
fi

# --- 3b: fetch_snapshot_summaries returns enriched dicts ---
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os, json
sys.path.insert(0, "$HOOK_DIR")
from pathlib import Path
from obsidian_utils import fetch_snapshot_summaries
snaps = fetch_snapshot_summaries(
    Path("$FIXTURE/v/claude-sessions"),
    "s-abcd-1111",
    "2026-04-18",
    "demo",
)
print(json.dumps([{
    "hhmmss": s["hhmmss"],
    "trigger": s["trigger"],
    "has_summary": bool(s.get("summary")),
} for s in snaps]))
PY
)
if echo "$RESULT" | grep -q '"hhmmss": "140000"' && echo "$RESULT" | grep -q '"trigger": "compact"'; then
    pass "fetch_snapshot_summaries returns HHMMSS+trigger correctly"
else
    fail "fetch_snapshot_summaries result unexpected: $RESULT"
fi

# --- 3c: collect_vault_corpus default excludes snapshots ---
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os, json
sys.path.insert(0, "$HOOK_DIR")
from obsidian_utils import collect_vault_corpus
raw = collect_vault_corpus("$FIXTURE/v", "claude-sessions", "claude-insights", days=30)
types = sorted({n["type"] for n in json.loads(raw)["notes"]})
print(",".join(types))
PY
)
if [ "$RESULT" = "claude-session" ]; then
    pass "collect_vault_corpus default excludes claude-snapshot"
else
    fail "collect_vault_corpus emitted types '$RESULT' (expected 'claude-session')"
fi

# --- 3d: exclude_types=() opts back in ---
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os, json
sys.path.insert(0, "$HOOK_DIR")
from obsidian_utils import collect_vault_corpus
raw = collect_vault_corpus("$FIXTURE/v", "claude-sessions", "claude-insights",
                           days=30, exclude_types=())
types = sorted({n["type"] for n in json.loads(raw)["notes"]})
print(",".join(types))
PY
)
if echo "$RESULT" | grep -q "claude-snapshot" && echo "$RESULT" | grep -q "claude-session"; then
    pass "collect_vault_corpus with exclude_types=() includes snapshots"
else
    fail "collect_vault_corpus opt-in returned '$RESULT'"
fi

# --- 3e: collect_open_items filters to claude-session ---
cat > "$FIXTURE/v/claude-sessions/2026-04-18-demo-open.md" <<'EOF'
---
type: claude-session
date: 2026-04-18
session_id: s-open
project: demo
---

# Session

## Open Questions / Next Steps
- [ ] Session open item that should appear
EOF
cat > "$FIXTURE/v/claude-sessions/2026-04-18-demo-open-snapshot-150000.md" <<'EOF'
---
type: claude-snapshot
date: 2026-04-18
session_id: s-open
project: demo
trigger: compact
status: auto-logged
---

# Snap

## Open Questions / Next Steps
- [ ] Snapshot bullet that MUST be ignored
EOF
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os
sys.path.insert(0, "$HOOK_DIR")
from open_item_dedup import collect_open_items
items = collect_open_items("$FIXTURE/v", "claude-sessions", "demo")
texts = [t for _, _, t in items]
has_session = any("should appear" in t for t in texts)
has_snap = any("MUST be ignored" in t for t in texts)
print(f"session={has_session} snap={has_snap}")
PY
)
if [ "$RESULT" = "session=True snap=False" ]; then
    pass "collect_open_items keeps session items, skips snapshot items"
else
    fail "collect_open_items filter wrong: $RESULT"
fi

# --- 3f: log_access cascade — snapshot access writes 2 rows ---
RESULT=$(python3 - <<PY 2>&1 || true
import sqlite3, sys, os
sys.path.insert(0, "$HOOK_DIR")
from vault_index import ensure_index, log_access, _PARENT_CACHE

db = ensure_index("$FIXTURE/v", ["claude-sessions", "claude-insights"],
                  db_path="$FIXTURE_DB")
_PARENT_CACHE.clear()
snap_path = "$FIXTURE/v/claude-sessions/2026-04-18-demo-abcd-snapshot-140000.md"
log_access(db, snap_path, "search", "demo")

conn = sqlite3.connect(db)
rows = conn.execute("SELECT note_path FROM access_log").fetchall()
conn.close()
paths = sorted({r[0] for r in rows})
print(f"count={len(paths)} session_present={any(p.endswith('2026-04-18-demo-abcd.md') for p in paths)}")
PY
)
if echo "$RESULT" | grep -q "count=2" && echo "$RESULT" | grep -q "session_present=True"; then
    pass "log_access cascade: snapshot access writes both self + parent rows"
else
    fail "log_access cascade wrong: $RESULT"
fi

# --- 3g: _snapshot_stats computes the 8-field dict ---
RESULT=$(python3 - <<PY 2>&1 || true
import sys, os, json
sys.path.insert(0, "$HOOK_DIR")
from vault_index import ensure_index
from vault_stats import compute_stats

db = ensure_index("$FIXTURE/v", ["claude-sessions", "claude-insights"],
                  db_path="$FIXTURE_DB")
payload = json.loads(compute_stats(db, "demo"))
snap = payload["vault_wide"].get("snapshots", {})
keys = sorted(snap.keys())
print(",".join(keys))
print(f"orphaned={snap.get('orphaned_snapshots')} broken={snap.get('broken_backlinks')} read_errors={snap.get('read_errors')}")
PY
)
EXPECTED_KEYS="broken_backlinks,by_trigger,max_snapshots_per_session,orphaned_snapshots,read_errors,sessions_with_snapshots,summarized_fraction,total_snapshots"
if echo "$RESULT" | head -1 | grep -qx "$EXPECTED_KEYS"; then
    pass "_snapshot_stats emits all 8 expected fields"
else
    fail "_snapshot_stats field set mismatch: $(echo "$RESULT" | head -1)"
fi
if echo "$RESULT" | tail -1 | grep -q "orphaned=1" && echo "$RESULT" | tail -1 | grep -q "read_errors=0"; then
    pass "_snapshot_stats counts orphan correctly, no spurious read_errors"
else
    fail "_snapshot_stats counters wrong: $(echo "$RESULT" | tail -1)"
fi

echo ""

# ─── Test 4: Schema unchanged ───────────────────────────────────────
echo "Test 4: Vault DB schema untouched by this PR"

if [ -f "$DB" ]; then
    # No new tables/columns required — confirm none accidentally introduced
    if sqlite3 "$DB" "PRAGMA table_info(notes)" 2>/dev/null | grep -q "snapshot_"; then
        fail "notes table gained an unexpected snapshot_ column"
    else
        pass "notes table shape preserved (no snapshot_* columns)"
    fi
else
    skip "Live vault DB not yet created — skip schema-drift check"
fi

echo ""

# ─── Summary ────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
echo "═══════════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "❌ One or more checks failed. Inspect the log above, fix, and re-run."
    exit 1
fi

cat <<'NEXT'

✅ Automated checks passed. Next: run the live Claude Code smoke flow in
   ./DEV-TEST-SNAPSHOTS.md (the parts that require an
   actual /compact, /recall, /vault-search, /vault-stats, and /emerge).
NEXT
