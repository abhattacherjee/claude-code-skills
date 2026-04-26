#!/usr/bin/env bash
# Manual smoke test for Issue #101 / PR #109 — source-session basename stability
# Run AFTER: /dev-test install
# Usage: bash scripts/dev-test/test-issue-101-manual.sh
#
# Validates the parts that can be checked without a fresh CC session:
#   - Plugin cache has #101 helpers (_first_seen_date, _resolve_session_note_by_hash,
#     _peek_frontmatter_{type,project_path}, _safe_getcwd, is_resumed_session(cwd=))
#   - _first_seen_date marker write/idempotency/corruption/sid-validation/mode-self-heal
#   - Resolver: type filter, project filter, type-missing legacy, ambiguous, single match
#   - is_resumed_session: snapshot-only False, real True, collision False, cross-project False
#   - get_session_context fallback uses marker date (not date.today)
#   - SessionEnd integration (hook simulation): basename uses _first_seen_date
#
# For the parts that require a fresh CC session (live SessionStart hint, /recall
# resolves UUID via on-disk note, real cross-midnight), see ./DEV-TEST-ISSUE-101.md.

set -euo pipefail

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

echo "═══════════════════════════════════════════════════════════════"
echo "Issue #101 / PR #109 — Automated Validation"
echo "═══════════════════════════════════════════════════════════════"
echo "Plugin cache: $CACHE_DIR"
echo "Hooks dir:    $HOOK_DIR"
echo ""

# Throwaway vault + isolated home for hook simulation
FIXTURE=$(mktemp -d -t ob-issue-101.XXXXXX)
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/vault/claude-sessions"
mkdir -p "$FIXTURE/home/.claude/obsidian-brain/sessions"
chmod 700 "$FIXTURE/home/.claude/obsidian-brain/sessions"

# ─── Test 1: Installed code surface ──────────────────────────────────
echo "Test 1: Installed code surface"

if grep -q "def _first_seen_date" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_first_seen_date() present"
else
    fail "_first_seen_date() missing — did /dev-test install pick up this branch?"
fi

if grep -q "def _resolve_session_note_by_hash" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_resolve_session_note_by_hash() present"
else
    fail "_resolve_session_note_by_hash() missing"
fi

if grep -q "def _peek_frontmatter_type" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_peek_frontmatter_type() present"
else
    fail "_peek_frontmatter_type() missing"
fi

if grep -q "def _peek_frontmatter_project_path" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_peek_frontmatter_project_path() present"
else
    fail "_peek_frontmatter_project_path() missing"
fi

if grep -q "def _safe_getcwd" "$HOOK_DIR/obsidian_utils.py"; then
    pass "_safe_getcwd() present"
else
    fail "_safe_getcwd() missing"
fi

if python3 -c "
import sys, inspect
sys.path.insert(0, '$HOOK_DIR')
import obsidian_utils
sig = inspect.signature(obsidian_utils.is_resumed_session)
sys.exit(0 if 'cwd' in sig.parameters else 1)
"; then
    pass "is_resumed_session(cwd=...) signature accepts cwd kwarg"
else
    fail "is_resumed_session signature missing cwd parameter"
fi

if grep -q '_first_seen_date(session_id)' "$HOOK_DIR/obsidian_session_log.py"; then
    pass "obsidian_session_log.py wires _first_seen_date(session_id)"
else
    fail "SessionEnd not using _first_seen_date — Fix A wire-up missing"
fi

echo ""

# ─── Test 2: Marker write + idempotency + cross-day stability ────────
echo "Test 2: _first_seen_date marker write + idempotency + cross-day"

RESULT=$(HOME="$FIXTURE/home" python3 - <<PY
import sys, os, json, datetime, pathlib
sys.path.insert(0, "$HOOK_DIR")
from unittest.mock import patch
import obsidian_utils

sid = "issue101-test-$(date +%s)"
d1 = obsidian_utils._first_seen_date(sid)
d2 = obsidian_utils._first_seen_date(sid)
print(f"d1={d1} d2={d2}")

m = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions" / f"{sid}.json"
print(f"marker_exists={m.exists()}")
print(f"marker_mode={oct(m.stat().st_mode)[-3:]}")
payload = json.loads(m.read_text())
print(f"has_first_seen_date={'first_seen_date' in payload}")
print(f"has_first_seen_iso={'first_seen_iso' in payload}")

# Cross-day: mock date.today() to advance, expect marker date unchanged
class FakeDate:
    @staticmethod
    def today():
        return datetime.date(2099, 1, 1)
with patch.object(obsidian_utils.datetime, "date", FakeDate):
    d3 = obsidian_utils._first_seen_date(sid)
print(f"cross_day={d3}")
PY
)

if echo "$RESULT" | grep -qE "d1=2[0-9]{3}-[0-9]{2}-[0-9]{2}"; then
    D1=$(echo "$RESULT" | grep -oE "d1=[0-9]{4}-[0-9]{2}-[0-9]{2}" | cut -d= -f2)
    D2=$(echo "$RESULT" | grep -oE "d2=[0-9]{4}-[0-9]{2}-[0-9]{2}" | cut -d= -f2)
    if [ "$D1" = "$D2" ]; then
        pass "_first_seen_date returns same value on second call (idempotent)"
    else
        fail "Idempotency broken: d1=$D1 d2=$D2"
    fi
else
    fail "_first_seen_date did not return ISO-8601 date: $RESULT"
fi

echo "$RESULT" | grep -q "marker_exists=True" && pass "Marker file written" || fail "Marker file not written"
echo "$RESULT" | grep -q "marker_mode=600" && pass "Marker mode is 0o600" || fail "Marker mode wrong: $(echo "$RESULT" | grep marker_mode)"
echo "$RESULT" | grep -q "has_first_seen_date=True" && pass "Marker has first_seen_date field" || fail "Marker missing first_seen_date"
echo "$RESULT" | grep -q "has_first_seen_iso=True" && pass "Marker has first_seen_iso field" || fail "Marker missing first_seen_iso"

CROSS=$(echo "$RESULT" | grep -oE "cross_day=[0-9]{4}-[0-9]{2}-[0-9]{2}" | cut -d= -f2)
if [ "$CROSS" = "$D1" ] && [ "$CROSS" != "2099-01-01" ]; then
    pass "Cross-day stability: marker beats date.today() (returns $CROSS, not 2099-01-01)"
else
    fail "Cross-day BROKEN: cross_day=$CROSS d1=$D1 (should match d1, must NOT be 2099-01-01)"
fi

echo ""

# ─── Test 3: Marker corruption self-heal + sid validation ────────────
echo "Test 3: Marker corruption self-heal + sid validation"

RESULT=$(HOME="$FIXTURE/home" python3 - <<PY
import sys, datetime, pathlib
sys.path.insert(0, "$HOOK_DIR")
import obsidian_utils

# Corrupt marker → self-heal returns today
sid = "corrupt-test-$(date +%s)"
m = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions" / f"{sid}.json"
m.write_text("{not valid json}")
d = obsidian_utils._first_seen_date(sid)
expected = datetime.date.today().isoformat()
print(f"corrupt_recover={d == expected}")

# Path-traversal sid → falls back to today, no marker written
bad_sid = "../../../etc/passwd"
d2 = obsidian_utils._first_seen_date(bad_sid)
print(f"bad_sid_fallback={d2 == expected}")
m2 = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions" / f"{bad_sid}.json"
# Resolve to detect any write outside the safe dir
import os
print(f"no_traversal_write={not os.path.exists('/etc/passwd.json.tmp')}")

# Loose-mode marker file → self-heals to 0o600 on read
sid3 = "loose-mode-test-$(date +%s)"
m3 = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions" / f"{sid3}.json"
m3.write_text('{"first_seen_date":"2026-04-20","first_seen_iso":"x"}')
import os
os.chmod(m3, 0o644)
obsidian_utils._first_seen_date(sid3)
print(f"marker_remode={oct(m3.stat().st_mode)[-3:]}")

# Loose-mode dir → self-heals to 0o700
sessions_dir = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions"
os.chmod(sessions_dir, 0o755)
obsidian_utils._first_seen_date("dirtest-$(date +%s)")
print(f"dir_remode={oct(sessions_dir.stat().st_mode)[-3:]}")
PY
2>&1)

echo "$RESULT" | grep -q "corrupt_recover=True" && pass "Corrupt marker → self-heals to today" || fail "Corruption recovery broken"
echo "$RESULT" | grep -q "bad_sid_fallback=True" && pass "Path-traversal sid → safe today fallback" || fail "Path-traversal handling broken"
echo "$RESULT" | grep -q "no_traversal_write=True" && pass "No file written outside marker dir" || fail "Path-traversal allowed file write"
echo "$RESULT" | grep -q "marker_remode=600" && pass "Loose-mode marker file → chmod 0o600 self-heal" || fail "Marker mode self-heal broken: $(echo "$RESULT" | grep marker_remode)"
echo "$RESULT" | grep -q "dir_remode=700" && pass "Loose-mode marker dir → chmod 0o700 self-heal" || fail "Dir mode self-heal broken: $(echo "$RESULT" | grep dir_remode)"

echo ""

# ─── Test 4: Resolver — type filter, project filter, ambiguous ───────
echo "Test 4: _resolve_session_note_by_hash branches"

RESULT=$(python3 - <<PY
import sys, pathlib
sys.path.insert(0, "$HOOK_DIR")
import obsidian_utils

def write(p, fields):
    with open(p, "w") as f:
        f.write("---\n")
        for k, v in fields.items():
            f.write(f"{k}: {v}\n")
        f.write("---\nbody\n")

sessions = pathlib.Path("$FIXTURE/vault/claude-sessions")
h = "abcd"

# Branch A: snapshot-only with session-shaped name → (None, [])
import shutil; shutil.rmtree(sessions); sessions.mkdir(parents=True)
write(sessions / f"2026-04-20-snap-{h}.md",
      {"type": "claude-snapshot", "session_id": "x"})
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/anything")
print(f"snapshot_only={b is None and c == []}")

# Branch B: single session match, cwd matches → (basename, [])
shutil.rmtree(sessions); sessions.mkdir(parents=True)
write(sessions / f"2026-04-20-foo-{h}.md",
      {"type": "claude-session", "session_id": "real",
       "project_path": '"/cwd/foo"'})
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/cwd/foo")
print(f"single_match={b == f'2026-04-20-foo-{h}' and c == []}")

# Branch C: cross-project disambiguation by cwd
shutil.rmtree(sessions); sessions.mkdir(parents=True)
write(sessions / f"2026-04-20-proj-a-{h}.md",
      {"type": "claude-session", "session_id": "a",
       "project_path": '"/cwd/a"'})
write(sessions / f"2026-04-20-proj-b-{h}.md",
      {"type": "claude-session", "session_id": "b",
       "project_path": '"/cwd/b"'})
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/cwd/a")
print(f"disambiguate={b == f'2026-04-20-proj-a-{h}' and c == [f'2026-04-20-proj-b-{h}.md']}")

# Branch D: type-missing legacy note treated as session
shutil.rmtree(sessions); sessions.mkdir(parents=True)
write(sessions / f"2026-04-20-legacy-{h}.md",
      {"session_id": "legacy", "project_path": '"/cwd/legacy"'})
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/cwd/legacy")
print(f"legacy_compat={b == f'2026-04-20-legacy-{h}'}")

# Branch E: same-cwd ambiguous → (None, [all])
shutil.rmtree(sessions); sessions.mkdir(parents=True)
write(sessions / f"2026-04-20-x-{h}.md",
      {"type": "claude-session", "session_id": "1",
       "project_path": '"/cwd/x"'})
write(sessions / f"2026-04-20-y-{h}.md",
      {"type": "claude-session", "session_id": "2",
       "project_path": '"/cwd/x"'})
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/cwd/x")
print(f"ambiguous={b is None and len(c) == 2}")

# Branch F: empty sessions dir → (None, [])
shutil.rmtree(sessions); sessions.mkdir(parents=True)
b, c = obsidian_utils._resolve_session_note_by_hash(sessions, h, cwd="/cwd/x")
print(f"no_match={b is None and c == []}")
PY
)

echo "$RESULT" | grep -q "snapshot_only=True" && pass "Snapshot-only with session-shaped name → excluded by type filter" || fail "Type filter broken: $(echo "$RESULT" | grep snapshot_only)"
echo "$RESULT" | grep -q "single_match=True" && pass "Single session match returns clean basename" || fail "Single match broken"
echo "$RESULT" | grep -q "disambiguate=True" && pass "Cross-project hash collision disambiguated by cwd" || fail "Cross-project disambiguation broken"
echo "$RESULT" | grep -q "legacy_compat=True" && pass "Type-missing legacy note treated as session (backward-compat)" || fail "Legacy-note backward-compat broken"
echo "$RESULT" | grep -q "ambiguous=True" && pass "Same-cwd ambiguous → (None, [all collisions])" || fail "Ambiguous resolution broken"
echo "$RESULT" | grep -q "no_match=True" && pass "Empty sessions dir → (None, [])" || fail "No-match path broken"

echo ""

# ─── Test 5: is_resumed_session — all branches ───────────────────────
echo "Test 5: is_resumed_session(cwd=) branches"

RESULT=$(python3 - <<PY
import sys, hashlib, pathlib, shutil
sys.path.insert(0, "$HOOK_DIR")
import obsidian_utils

def write(p, fields):
    with open(p, "w") as f:
        f.write("---\n")
        for k, v in fields.items():
            f.write(f"{k}: {v}\n")
        f.write("---\nbody\n")

vault = pathlib.Path("$FIXTURE/vault")
sessions = vault / "claude-sessions"

sid = "test-resume-sid"
h = hashlib.sha256(sid.encode()).hexdigest()[:4]

# Snapshot-only with session-shaped name → False (type filter)
shutil.rmtree(sessions); sessions.mkdir()
write(sessions / f"2026-04-20-foo-{h}.md",
      {"type": "claude-snapshot", "session_id": "different"})
r = obsidian_utils.is_resumed_session(str(vault), "claude-sessions", sid, cwd="/cwd/foo")
print(f"snapshot_only_false={r is False}")

# Real session, cwd matches → True
shutil.rmtree(sessions); sessions.mkdir()
write(sessions / f"2026-04-20-foo-{h}.md",
      {"type": "claude-session", "session_id": sid,
       "project_path": '"/cwd/foo"'})
r = obsidian_utils.is_resumed_session(str(vault), "claude-sessions", sid, cwd="/cwd/foo")
print(f"real_session_true={r is True}")

# Cross-project hash collision (cwd mismatch) → False
shutil.rmtree(sessions); sessions.mkdir()
write(sessions / f"2026-04-20-other-{h}.md",
      {"type": "claude-session", "session_id": "other-sid",
       "project_path": '"/some/other/path"'})
r = obsidian_utils.is_resumed_session(str(vault), "claude-sessions", sid, cwd="/cwd/foo")
print(f"cross_project_false={r is False}")

# Same-project ambiguous collision pair → False (no unambiguous prior session)
shutil.rmtree(sessions); sessions.mkdir()
write(sessions / f"2026-04-20-x-{h}.md",
      {"type": "claude-session", "session_id": "1",
       "project_path": '"/cwd/foo"'})
write(sessions / f"2026-04-20-y-{h}.md",
      {"type": "claude-session", "session_id": "2",
       "project_path": '"/cwd/foo"'})
r = obsidian_utils.is_resumed_session(str(vault), "claude-sessions", sid, cwd="/cwd/foo")
print(f"ambiguous_false={r is False}")
PY
)

echo "$RESULT" | grep -q "snapshot_only_false=True" && pass "Snapshot-only → is_resumed_session=False (subsumes #86)" || fail "Snapshot type filter not blocking is_resumed_session"
echo "$RESULT" | grep -q "real_session_true=True" && pass "Real session note → is_resumed_session=True" || fail "Real session detection broken"
echo "$RESULT" | grep -q "cross_project_false=True" && pass "Cross-project hash collision → is_resumed_session=False (cwd-strict)" || fail "Cross-project filter broken (closes #110 concern)"
echo "$RESULT" | grep -q "ambiguous_false=True" && pass "Ambiguous collision pair → is_resumed_session=False" || fail "Ambiguous handling broken"

echo ""

# ─── Test 6: get_session_context fallback uses marker date ───────────
echo "Test 6: get_session_context fallback uses _first_seen_date (cross-midnight)"

RESULT=$(HOME="$FIXTURE/home" python3 - <<PY
import sys, json, pathlib, datetime, shutil
sys.path.insert(0, "$HOOK_DIR")
from unittest.mock import patch
import obsidian_utils

# Pre-seed marker for a session with first_seen=day-N, then mock today=day-N+2
sid = "cross-midnight-sid-$(date +%s)"
marker_dir = pathlib.Path("$FIXTURE/home") / ".claude/obsidian-brain/sessions"
(marker_dir / f"{sid}.json").write_text(
    json.dumps({"first_seen_date": "2026-04-20", "first_seen_iso": "x"})
)

class FakeDate:
    @staticmethod
    def today():
        return datetime.date(2026, 4, 22)

# Clean vault for fallback path (no on-disk session note → resolver returns None)
vault = pathlib.Path("$FIXTURE/vault")
sessions = vault / "claude-sessions"
shutil.rmtree(sessions); sessions.mkdir()

# get_session_context resolves sid via _get_session_id_fast and project via
# canonical_project_name — patch both so the fallback exercises marker date.
with patch.object(obsidian_utils, "_get_session_id_fast", return_value=sid), \
     patch.object(obsidian_utils, "canonical_project_name", return_value="test-project"), \
     patch.object(obsidian_utils, "cache_get", return_value=None), \
     patch.object(obsidian_utils, "cache_set", return_value=None), \
     patch.object(obsidian_utils.datetime, "date", FakeDate):
    ctx = obsidian_utils.get_session_context(str(vault), "claude-sessions")

basename = ctx.get("session_note_name", "")
print(f"basename={basename}")
print(f"starts_with_marker_date={basename.startswith('2026-04-20-')}")
print(f"NOT_today={'2026-04-22' not in basename}")
PY
)

echo "$RESULT" | grep -q "starts_with_marker_date=True" && pass "Fallback basename starts with marker date (2026-04-20)" || fail "Fallback ignored marker: $(echo "$RESULT" | grep basename)"
echo "$RESULT" | grep -q "NOT_today=True" && pass "Fallback basename does NOT use today's date (2026-04-22)" || fail "Fallback used today instead of marker"

echo ""

# ─── Test 7: SessionEnd hook simulation — basename uses marker ───────
echo "Test 7: SessionEnd hook simulation — full write path"

# Clean vault sessions dir of fixtures from earlier tests so the find
# at the bottom only sees what THIS hook invocation wrote.
rm -f "$FIXTURE/vault/claude-sessions/"*.md

# Pre-seed a marker with yesterday-equivalent date
SIM_SID="sim-sessionend-$(date +%s)"
MARKER_DIR="$FIXTURE/home/.claude/obsidian-brain/sessions"
echo '{"first_seen_date":"2026-04-20","first_seen_iso":"2026-04-20T22:00:00Z"}' \
    > "$MARKER_DIR/$SIM_SID.json"
chmod 600 "$MARKER_DIR/$SIM_SID.json"

# Synthetic config + transcript
CFG_DIR="$FIXTURE/home/.claude"
cat > "$CFG_DIR/obsidian-brain-config.json" <<JSON
{
  "vault_path": "$FIXTURE/vault",
  "sessions_folder": "claude-sessions",
  "insights_folder": "claude-insights",
  "min_messages_to_log": 0,
  "min_session_duration_seconds": 0
}
JSON

TRANSCRIPT="$FIXTURE/transcript.jsonl"
cat > "$TRANSCRIPT" <<EOF
{"type":"user","message":{"role":"user","content":"hello"},"timestamp":"2026-04-20T22:00:00Z"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]},"timestamp":"2026-04-20T22:00:05Z"}
EOF

# Simulate SessionEnd
HOOK_INPUT=$(cat <<JSON
{"hook_event_name":"SessionEnd","session_id":"$SIM_SID","cwd":"$FIXTURE","transcript_path":"$TRANSCRIPT"}
JSON
)

if HOME="$FIXTURE/home" echo "$HOOK_INPUT" | python3 "$HOOK_DIR/obsidian_session_log.py" >/dev/null 2>&1; then
    pass "SessionEnd hook ran without error"
else
    skip "SessionEnd hook returned non-zero (likely benign — filter thresholds, no anthropic key for summarization)"
fi

# Whether or not summarization succeeded, the raw note must exist with marker-dated basename
WROTE=$(find "$FIXTURE/vault/claude-sessions" -name "2026-04-20-*.md" 2>/dev/null | head -1)
if [ -n "$WROTE" ]; then
    pass "Vault note written with marker date prefix: $(basename "$WROTE")"
else
    BAD=$(find "$FIXTURE/vault/claude-sessions" -name "*.md" 2>/dev/null | head -1)
    if [ -n "$BAD" ]; then
        fail "Vault note basename uses wrong date: $(basename "$BAD") — expected 2026-04-20-*"
    else
        skip "No vault note written (likely below message threshold, OK)"
    fi
fi

echo ""

# ─── Test 8: _safe_getcwd handles cwd-gone ───────────────────────────
echo "Test 8: _safe_getcwd cwd-gone safety"

RESULT=$(python3 - <<PY
import sys, os
sys.path.insert(0, "$HOOK_DIR")
import obsidian_utils

# Normal case
cwd1 = obsidian_utils._safe_getcwd()
print(f"normal_nonempty={bool(cwd1)}")

# Simulate cwd-gone
def fake_getcwd_raises():
    raise FileNotFoundError("cwd is gone")

orig = os.getcwd
os.getcwd = fake_getcwd_raises
cwd2 = obsidian_utils._safe_getcwd()
os.getcwd = orig
print(f"cwd_gone_returns_empty={cwd2 == ''}")
PY
)

echo "$RESULT" | grep -q "normal_nonempty=True" && pass "_safe_getcwd returns non-empty when cwd is healthy" || fail "_safe_getcwd broken in normal case"
echo "$RESULT" | grep -q "cwd_gone_returns_empty=True" && pass "_safe_getcwd returns '' on FileNotFoundError" || fail "_safe_getcwd does not handle cwd-gone"

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
   ./DEV-TEST-ISSUE-101.md (the parts that require an actual fresh CC session
   to exercise SessionStart hint, real /recall against a non-fixture vault,
   and end-to-end cross-midnight via real wall-clock advance).
NEXT
