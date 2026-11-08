#!/usr/bin/env bash
set -euo pipefail

# test-check-needs-results.sh — fixtures for the merge-blocking needs check (#291).
# Usage: bash scripts/test-check-needs-results.sh (NEEDS_CHECKER=<path> overrides)
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEEDS_CHECKER="${NEEDS_CHECKER:-$REPO_ROOT/scripts/check-needs-results.sh}"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

[[ -f "$NEEDS_CHECKER" ]] || { echo "FATAL: check-needs-results.sh not found at $NEEDS_CHECKER" >&2; exit 1; }
command -v jq > /dev/null || { echo "FATAL: jq not found" >&2; exit 1; }

# run <json>: sets RC, OUT (stdout + stderr).
run() {
  OUT="$(RESULTS="$1" bash "$NEEDS_CHECKER" 2>&1)" && RC=0 || RC=$?
}
expect_rc() {
  local label="$1" want="$2"; shift 2
  local t
  [[ $RC -eq $want ]] || { bad "$label" "rc=$RC want=$want out=$OUT"; return 0; }
  for t in "$@"; do
    [[ "$OUT" == *"$t"* ]] || { bad "$label" "output lacks [$t]: $OUT"; return 0; }
  done
  ok "$label"
}

run '{"build":{"result":"success"},"test":{"result":"success"}}'
expect_rc 'all success' 0 'build: success' 'test: success'

run '{"build":{"result":"success"},"test":{"result":"skipped"}}'
expect_rc 'success and skipped' 0 'test: skipped'

run '{"build":{"result":"success"},"test":{"result":"failure"}}'
expect_rc 'one failure' 1 '::error::These jobs did not pass: test'

run '{"build":{"result":"cancelled"},"test":{"result":"success"}}'
expect_rc 'one cancelled' 1 '::error::These jobs did not pass: build'

run '{"build":{"result":"timed_out"},"test":{"result":"success"}}'
expect_rc 'unknown result value' 1 'did not pass: build'

run '{"build":{"outputs":{}},"test":{"result":"success"}}'
expect_rc 'entry without a result' 1 'did not pass: build'

run '{}'
expect_rc 'empty needs object' 1 'no needed jobs in RESULTS'

run 'not json'
[[ $RC -ne 0 && $RC -ne 127 ]] && ok 'invalid JSON' || bad 'invalid JSON' "rc=$RC out=$OUT"

run '[]'
[[ $RC -ne 0 ]] && ok 'JSON array' || bad 'JSON array' "rc=$RC out=$OUT"

# A non-empty array passes the length check, so only the object check rejects it.
run '[{"result":"success"}]'
[[ $RC -ne 0 ]] && ok 'non-empty JSON array' || bad 'non-empty JSON array' "rc=$RC out=$OUT"

run ''
[[ $RC -ne 0 ]] && ok 'empty RESULTS' || bad 'empty RESULTS' "rc=$RC out=$OUT"

OUT="$(env -u RESULTS bash "$NEEDS_CHECKER" 2>&1)" && RC=0 || RC=$?
[[ $RC -ne 0 ]] && ok 'unset RESULTS' || bad 'unset RESULTS' "rc=$RC out=$OUT"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
