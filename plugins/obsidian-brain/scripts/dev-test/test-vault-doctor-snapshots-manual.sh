#!/usr/bin/env bash
# Manual smoke test for vault-doctor Phase B + C (PR #63)
# Run AFTER: /dev-test install + start a new Claude Code session
# Usage: bash scripts/dev-test/test-vault-doctor-snapshots-manual.sh
#
# Validates the snapshot-integrity and snapshot-migration check modules
# end-to-end against a throwaway fixture vault. Does NOT touch the user's
# real vault.
#
# For the live-session parts (running /vault-doctor against the real
# vault and watching /recall pick up the recovered snapshots), see
# ./DEV-TEST-VAULT-DOCTOR-SNAPSHOTS.md.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }

# ─── Locate code surface ────────────────────────────────────────────
# Prefer the installed plugin cache (validates the distribution path).
# Fall back to the local repo so this script works before /dev-test install,
# emitting a warning so the user knows what's being exercised.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS_ROOT=""
SKILL_ROOT=""

CACHE_DIR=$(find ~/.claude/plugins/cache -type d -path "*/obsidian-brain/*" \
    -not -path "*.bak*" 2>/dev/null | sort -V | tail -1 | xargs dirname 2>/dev/null || true)

if [ -n "$CACHE_DIR" ] && [ -d "$CACHE_DIR" ]; then
    CACHE_SCRIPTS=$(find "$CACHE_DIR" -maxdepth 2 -type d -name scripts | sort -V | tail -1)
    if [ -f "$CACHE_SCRIPTS/vault_doctor_checks/snapshot_integrity.py" ]; then
        SCRIPTS_ROOT="$CACHE_SCRIPTS"
        SKILL_ROOT=$(find "$CACHE_DIR" -maxdepth 2 -type d -name skills | sort -V | tail -1)
        echo "Using installed plugin cache: $CACHE_DIR"
    else
        echo "⚠️  Installed plugin cache does NOT contain snapshot_integrity.py yet."
        echo "    Run /dev-test install in a fresh Claude Code session to copy"
        echo "    the feature-branch code into the cache. Falling back to local repo."
    fi
fi

if [ -z "$SCRIPTS_ROOT" ]; then
    if [ -f "$REPO_ROOT/scripts/vault_doctor_checks/snapshot_integrity.py" ]; then
        SCRIPTS_ROOT="$REPO_ROOT/scripts"
        SKILL_ROOT="$REPO_ROOT/skills"
        echo "Using local repo: $REPO_ROOT"
    else
        echo "❌ Could not locate snapshot_integrity.py in cache OR local repo."
        echo "   Are you on the feature/snapshot-phase-b-c branch?"
        exit 1
    fi
fi

echo "═══════════════════════════════════════════════════════════════"
echo "vault-doctor snapshot Phase B + C — Automated Validation"
echo "═══════════════════════════════════════════════════════════════"
echo "Plugin cache: $CACHE_DIR"
echo "Scripts dir:  $SCRIPTS_ROOT"
echo "Skills dir:   $SKILL_ROOT"
echo ""

# ─── Throwaway fixture vault ────────────────────────────────────────
FIXTURE=$(mktemp -d -t ob-vd-snapshots.XXXXXX)
trap 'rm -rf "$FIXTURE"' EXIT
SESS="$FIXTURE/claude-sessions"
INSIGHTS="$FIXTURE/claude-insights"
mkdir -p "$SESS" "$INSIGHTS"
BACKUP_ROOT="$FIXTURE/.backup"

# ─── Test 1: Module discovery via registry ──────────────────────────
echo "Test 1: Module registry exposes both new checks"

DISCOVERED=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPTS_ROOT/../scripts' if '$SCRIPTS_ROOT/../scripts' else '$SCRIPTS_ROOT')
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import list_checks
print(' '.join(list_checks()))
" 2>&1)

if echo "$DISCOVERED" | grep -q "snapshot-integrity"; then
    pass "snapshot-integrity registered"
else
    fail "snapshot-integrity NOT registered. Discovered: $DISCOVERED"
fi

if echo "$DISCOVERED" | grep -q "snapshot-migration"; then
    pass "snapshot-migration registered"
else
    fail "snapshot-migration NOT registered. Discovered: $DISCOVERED"
fi

# ─── Test 2: Seed legacy snapshot fixture ───────────────────────────
echo ""
echo "Test 2: Seed legacy fixture (pre-spec snapshot + parent session)"

# Legacy snapshot: no -HHMMSS suffix, no status field, no source_session_note
cat > "$SESS/2026-04-05-demo-aaaa-snapshot.md" <<'EOF'
---
type: claude-snapshot
date: 2026-04-05
session_id: aaaa-1111-2222
project: demo
trigger: compact
---

# Snapshot

## What was happening
test body
EOF

# Set deterministic mtime so HHMMSS derivation is predictable
python3 -c "
import os, datetime
ts = datetime.datetime(2026, 4, 5, 14, 30, 27).timestamp()
os.utime('$SESS/2026-04-05-demo-aaaa-snapshot.md', (ts, ts))
"

# Compute parent stem the way the migration check does
PARENT_STEM=$(python3 -c "
import hashlib
sid = 'aaaa-1111-2222'
proj = 'demo'
date = '2026-04-05'
hash4 = hashlib.sha256(sid.encode()).hexdigest()[:4]
print(f'{date}-{proj}-{hash4}')
")

# Parent session WITHOUT snapshots: list (Phase C check 4 will backfill)
cat > "$SESS/${PARENT_STEM}.md" <<EOF
---
type: claude-session
date: 2026-04-05
session_id: aaaa-1111-2222
project: demo
status: summarized
---

# Session: demo
EOF

# Reference to the legacy stem in an insight (Phase C wikilink rewrite target)
cat > "$INSIGHTS/2026-04-05-ref.md" <<EOF
---
type: claude-insight
date: 2026-04-05
project: demo
---

See [[2026-04-05-demo-aaaa-snapshot]] for context.
EOF

if [ -f "$SESS/2026-04-05-demo-aaaa-snapshot.md" ] && [ -f "$SESS/${PARENT_STEM}.md" ]; then
    pass "Fixture vault seeded (legacy snapshot + parent + insight ref)"
else
    fail "Fixture seeding broken"
    exit 1
fi

# ─── Test 3: snapshot-migration scan finds all 4 issue classes ──────
echo ""
echo "Test 3: snapshot-migration scan detects 4 issue kinds"

SCAN_JSON=$(python3 -c "
import sys, json
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_migration
issues = snapshot_migration.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 3650)
print(json.dumps([{'check': i.check, 'note_path': i.note_path, 'extra': dict(i.extra)} for i in issues]))
")

for check in snapshot-legacy-filename snapshot-missing-status snapshot-missing-backlink session-missing-snapshots-list; do
    if echo "$SCAN_JSON" | grep -q "\"check\": \"$check\""; then
        pass "scan emits $check"
    else
        fail "scan did NOT emit $check. Output: $SCAN_JSON"
    fi
done

# ─── Test 4: snapshot-migration apply renames + backfills + rewrites ─
echo ""
echo "Test 4: snapshot-migration apply produces post-spec state"

python3 -c "
import sys
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_migration
issues = snapshot_migration.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 3650)
results = snapshot_migration.apply(issues, '$BACKUP_ROOT')
applied = [r for r in results if r.status == 'applied']
print(f'Applied: {len(applied)} of {len(results)}')
for r in results:
    print(f'  {r.status}: {r.check} on {r.note_path}')
"

# Renamed file exists with HHMMSS=143027
if [ -f "$SESS/2026-04-05-demo-aaaa-snapshot-143027.md" ]; then
    pass "Legacy file renamed with HHMMSS suffix"
else
    fail "Legacy rename did not produce -snapshot-143027.md"
fi

# Original legacy file gone
if [ ! -f "$SESS/2026-04-05-demo-aaaa-snapshot.md" ]; then
    pass "Original legacy filename removed"
else
    fail "Legacy file still present after rename"
fi

# status: auto-logged injected
if grep -q "^status: auto-logged" "$SESS/2026-04-05-demo-aaaa-snapshot-143027.md" 2>/dev/null; then
    pass "status: auto-logged injected"
else
    fail "status: auto-logged not in renamed file"
fi

# source_session_note backlink injected
if grep -q "source_session_note: \"\[\[${PARENT_STEM}\]\]\"" "$SESS/2026-04-05-demo-aaaa-snapshot-143027.md" 2>/dev/null; then
    pass "source_session_note backlink injected"
else
    fail "source_session_note backlink missing"
fi

# Parent session gained snapshots: list pointing at new stem
if grep -q "snapshots:" "$SESS/${PARENT_STEM}.md" && \
   grep -q "2026-04-05-demo-aaaa-snapshot-143027" "$SESS/${PARENT_STEM}.md"; then
    pass "Parent session backfilled with snapshots: list (post-rename stem)"
else
    fail "Parent session snapshots: backfill missing or stale"
fi

# Insight wikilink rewritten to new stem
if grep -q "\[\[2026-04-05-demo-aaaa-snapshot-143027\]\]" "$INSIGHTS/2026-04-05-ref.md" && \
   ! grep -q "\[\[2026-04-05-demo-aaaa-snapshot\]\]" "$INSIGHTS/2026-04-05-ref.md"; then
    pass "Insight wikilink rewritten to post-rename stem"
else
    fail "Insight wikilink not rewritten correctly"
fi

# Backup file retains pre-migration content (legacy stem reference)
BACKUP_DIR="$BACKUP_ROOT/snapshot-legacy-filename"
if [ -f "$BACKUP_DIR/2026-04-05-demo-aaaa-snapshot.md" ]; then
    pass "Backup file exists at <backup_root>/snapshot-legacy-filename/<basename>"
else
    fail "Backup file missing"
fi

# ─── Test 5: Idempotency — second migration scan returns no actionable issues ─
echo ""
echo "Test 5: snapshot-migration is idempotent"

REISSUES=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_migration
issues = snapshot_migration.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 3650)
actionable = [i for i in issues if not i.extra.get('unresolved')]
print(len(actionable))
")

if [ "$REISSUES" -eq 0 ]; then
    pass "Re-scan returns 0 actionable issues (idempotent)"
else
    fail "Re-scan returned $REISSUES actionable issues — not idempotent"
fi

# ─── Test 6: snapshot-integrity scan on the post-migration state ────
echo ""
echo "Test 6: snapshot-integrity scan finds no issues on clean post-migration vault"

INTEGRITY_ISSUES=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_integrity
issues = snapshot_integrity.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 30)
print(len(issues))
")

if [ "$INTEGRITY_ISSUES" -eq 0 ]; then
    pass "Integrity scan reports 0 issues on freshly-migrated vault"
else
    fail "Integrity scan found $INTEGRITY_ISSUES unexpected issues"
fi

# ─── Test 7: snapshot-integrity detects + auto-fixes broken backlink ─
echo ""
echo "Test 7: snapshot-integrity broken-backlink scan + apply round-trip"

# Corrupt the backlink in the migrated snapshot
python3 -c "
import re
p = '$SESS/2026-04-05-demo-aaaa-snapshot-143027.md'
text = open(p).read()
text = re.sub(r'source_session_note:.*', 'source_session_note: \"[[wrong-stem-here]]\"', text, count=1)
open(p, 'w').write(text)
"

BROKEN=$(python3 -c "
import sys, json
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_integrity
issues = snapshot_integrity.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 30)
broken = [i for i in issues if i.check == 'snapshot-broken-backlink']
print(len(broken))
")

if [ "$BROKEN" -eq 1 ]; then
    pass "Broken-backlink detected after corruption"
else
    fail "Broken-backlink scan returned $BROKEN (expected 1)"
fi

python3 -c "
import sys
sys.path.insert(0, '$SCRIPTS_ROOT')
from vault_doctor_checks import snapshot_integrity
issues = snapshot_integrity.scan('$FIXTURE', 'claude-sessions', 'claude-insights', 30)
broken = [i for i in issues if i.check == 'snapshot-broken-backlink']
snapshot_integrity.apply(broken, '$BACKUP_ROOT')
"

if grep -q "source_session_note: \"\[\[${PARENT_STEM}\]\]\"" "$SESS/2026-04-05-demo-aaaa-snapshot-143027.md"; then
    pass "Broken backlink auto-repaired to correct parent stem"
else
    fail "Broken backlink fix did not restore correct stem"
fi

# ─── Test 8: SKILL.md documents both new checks ─────────────────────
echo ""
echo "Test 8: SKILL.md documents both checks"

SKILL_MD="$SKILL_ROOT/vault-doctor/SKILL.md"
if grep -q "snapshot-integrity" "$SKILL_MD"; then
    pass "SKILL.md mentions snapshot-integrity"
else
    fail "SKILL.md missing snapshot-integrity invocation"
fi

if grep -q "snapshot-migration" "$SKILL_MD"; then
    pass "SKILL.md mentions snapshot-migration"
else
    fail "SKILL.md missing snapshot-migration invocation"
fi

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
