#!/usr/bin/env bash
# Usage: ./scripts/test-security.sh
# Run after /dev-test install to validate security hardening.
# Does NOT require a Claude Code session — tests Python directly.
# Set OB_HOOKS_DIR=hooks to test repo hooks directly (used in CI).
set -euo pipefail

if [ -n "${OB_HOOKS_DIR:-}" ]; then
    HOOKS_DIR="$OB_HOOKS_DIR"
else
    HOOKS_DIR=$(python3 -c '
import glob, os
dirs = glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/obsidian-brain/*/hooks"))
print(max(dirs) if dirs else "")
')
fi

if [ -z "$HOOKS_DIR" ]; then
    echo "FAIL: No installed obsidian-brain hooks found. Run /dev-test install first."
    exit 1
fi

echo "Testing against: $HOOKS_DIR"
echo "================================"

PASS=0
FAIL=0

run_test() {
    local name="$1"
    shift
    if "$@"; then
        echo "PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $name"
        FAIL=$((FAIL + 1))
    fi
}

# --- Test 1: Secure directory (C1) ---
run_test "C1: _SECURE_DIR points to ~/.claude/obsidian-brain" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import _SECURE_DIR
import os
expected = os.path.expanduser('~/.claude/obsidian-brain')
assert _SECURE_DIR == expected, f'{_SECURE_DIR} != {expected}'
"

run_test "C1: _CACHE_PREFIX under secure dir" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import _CACHE_PREFIX
import os
secure = os.path.expanduser('~/.claude/obsidian-brain')
assert _CACHE_PREFIX.startswith(secure), f'{_CACHE_PREFIX} not under {secure}'
"

run_test "C1: _BOOTSTRAP_PREFIX under secure dir" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import _BOOTSTRAP_PREFIX
import os
secure = os.path.expanduser('~/.claude/obsidian-brain')
assert _BOOTSTRAP_PREFIX.startswith(secure), f'{_BOOTSTRAP_PREFIX} not under {secure}'
"

run_test "C1: _ensure_secure_dir creates 0o700 directory" \
    python3 -c "
import sys, os, stat; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import _ensure_secure_dir
d = _ensure_secure_dir()
mode = stat.S_IMODE(os.stat(d).st_mode)
assert mode == 0o700, f'expected 0o700, got {oct(mode)}'
"

# --- Test 2: Env var override removed (C2) ---
run_test "C2: OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX env var ignored" \
    env OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX=/tmp/evil- python3 -c "
import sys, os; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import _bootstrap_prefix
prefix = _bootstrap_prefix()
assert '/tmp/evil-' not in prefix, f'env var override still active: {prefix}'
secure = os.path.expanduser('~/.claude/obsidian-brain')
assert prefix.startswith(secure), f'{prefix} not under {secure}'
"

# --- Test 3: Path traversal blocked (H1) ---
run_test "H1: write_vault_note blocks ../ traversal" \
    python3 -c "
import sys, os, tempfile; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import write_vault_note
with tempfile.TemporaryDirectory() as vault:
    result = write_vault_note(vault, '../../etc', 'evil.md', 'payload')
    assert result is False, 'traversal was NOT blocked'
"

run_test "H1: write_vault_note allows normal subfolders" \
    python3 -c "
import sys, os, tempfile; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import write_vault_note
with tempfile.TemporaryDirectory() as vault:
    result = write_vault_note(vault, 'claude-sessions', 'test.md', '---\ntest\n---\n')
    assert result is True, 'normal write was blocked'
    assert os.path.exists(os.path.join(vault, 'claude-sessions', 'test.md'))
"

# --- Test 3b: Transcript path validation (H3) ---
run_test "H3: transcript_path validation function exists" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect, obsidian_session_log
src = inspect.getsource(obsidian_session_log)
assert '~/.claude/projects' in src or 'claude/projects' in src, 'transcript_path validation missing'
"

# --- Test 3c: find_transcript_jsonl containment (M8) ---
run_test "M8: find_transcript_jsonl validates path containment" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect
from obsidian_utils import find_transcript_jsonl
src = inspect.getsource(find_transcript_jsonl)
assert 'realpath' in src or 'resolve' in src, 'path containment check missing in find_transcript_jsonl'
assert 'startswith' in src or 'is_relative_to' in src, 'containment comparison missing'
"

# --- Test 4: Secret scrubbing (H2) ---
run_test "H2: scrub_secrets redacts GitHub tokens" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
result = scrub_secrets('token: ghp_abc123def456ghi789jkl012mno345pqr678stu9')
assert 'ghp_' not in result, f'GitHub token not redacted: {result}'
assert 'REDACTED' in result
"

run_test "H2: scrub_secrets redacts AWS keys" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
result = scrub_secrets('key=AKIAIOSFODNN7EXAMPLE')
assert 'AKIA' not in result, f'AWS key not redacted: {result}'
"

run_test "H2: scrub_secrets redacts password= patterns" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
result = scrub_secrets('password=hunter2')
assert 'hunter2' not in result, f'password not redacted: {result}'
"

run_test "H2: scrub_secrets redacts Bearer tokens" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
result = scrub_secrets('Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def')
assert 'eyJhb' not in result, f'Bearer token not redacted: {result}'
"

run_test "H2: scrub_secrets redacts PEM headers" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
result = scrub_secrets('-----BEGIN RSA PRIVATE KEY-----')
assert 'BEGIN RSA' not in result, f'PEM header not redacted: {result}'
"

run_test "H2: scrub_secrets preserves normal text" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import scrub_secrets
text = 'normal conversation about code review and debugging'
result = scrub_secrets(text)
assert result == text, f'normal text was modified: {result}'
"

run_test "H2: build_raw_fallback applies scrub_secrets" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect
from obsidian_utils import build_raw_fallback
src = inspect.getsource(build_raw_fallback)
assert 'scrub_secrets' in src, 'build_raw_fallback does not call scrub_secrets'
"

run_test "H2: build_raw_fallback respects log_raw_messages=false" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import build_raw_fallback
result = build_raw_fallback(
    ['user message 1'], {'project': 'test', 'duration_minutes': 5},
    assistant_msgs=['assistant reply'], config={'log_raw_messages': False}
)
assert '## Conversation (raw)' not in result, 'raw conversation present despite log_raw_messages=false'
"

run_test "H2: build_raw_fallback includes conversation when enabled" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import build_raw_fallback
result = build_raw_fallback(
    ['user message 1'], {'project': 'test', 'duration_minutes': 5},
    assistant_msgs=['assistant reply'], config={'log_raw_messages': True}
)
assert '## Conversation (raw)' in result, 'raw conversation missing despite log_raw_messages=true'
"

# --- Test 5: File permissions (M1, M2) ---
run_test "M1: vault_index uses 0o600 for DB" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect
from vault_index import ensure_index
src = inspect.getsource(ensure_index)
assert '0o600' in src, 'DB permission not set to 0o600'
assert '0o644' not in src, 'DB still using 0o644'
"

run_test "M2: write_vault_note uses 0o600 for files" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect
from obsidian_utils import write_vault_note
src = inspect.getsource(write_vault_note)
assert '0o600' in src, 'vault note permission not 0o600'
assert '0o644' not in src, 'vault note still using 0o644'
"

run_test "M2: load_config auto-fixes permissions" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
import inspect
from obsidian_utils import load_config
src = inspect.getsource(load_config)
assert '0o077' in src or '0o600' in src, 'config permission auto-fix missing'
"

# --- Test 6: Stdin cap (M6) ---
run_test "M6: session_log stdin capped" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
with open('$HOOKS_DIR/obsidian_session_log.py') as f:
    src = f.read()
assert 'read(1_000_000)' in src or 'read(1000000)' in src, 'stdin not capped in session_log'
"

run_test "M6: session_hint stdin capped" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
with open('$HOOKS_DIR/obsidian_session_hint.py') as f:
    src = f.read()
assert 'read(1_000_000)' in src or 'read(1000000)' in src, 'stdin not capped in session_hint'
"

run_test "M6: context_snapshot stdin capped" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
with open('$HOOKS_DIR/obsidian_context_snapshot.py') as f:
    src = f.read()
assert 'read(1_000_000)' in src or 'read(1000000)' in src, 'stdin not capped in context_snapshot'
"

# --- Test 7: LIKE escaping (M7) ---
run_test "M7: vault_index escapes LIKE wildcards" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
with open('$HOOKS_DIR/vault_index.py') as f:
    src = f.read()
assert 'ESCAPE' in src, 'LIKE ESCAPE clause missing in vault_index'
"

# --- Test 8: commit-preflight.sh injection fix (H4) ---
run_test "H4: commit-preflight.sh uses sys.argv for PROJECT_HASH" \
    python3 -c "
with open('scripts/commit-preflight.sh') as f:
    src = f.read()
assert 'sys.argv[1]' in src, 'commit-preflight still interpolates path'
# Verify old vulnerable pattern is gone
assert \"hashlib.md5('\$(realpath\" not in src, 'old vulnerable pattern still present'
"

# --- Test 9: flip_note_status exists (M5) ---
run_test "M5: flip_note_status function exists" \
    python3 -c "
import sys; sys.path.insert(0, '$HOOKS_DIR')
from obsidian_utils import flip_note_status
import inspect
src = inspect.getsource(flip_note_status)
assert 'rename' in src or 'replace' in src, 'flip_note_status does not use atomic rename'
"

# --- Summary ---
echo ""
echo "================================"
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "SECURITY TESTS FAILED"
    exit 1
else
    echo "ALL SECURITY TESTS PASSED"
    exit 0
fi
