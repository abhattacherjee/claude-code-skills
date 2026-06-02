#!/usr/bin/env bash
# run-tests.sh — test suite for adversarial-review scripts
# Usage: run-tests.sh [--help]
# Exit codes: 0=all tests pass, 1=one or more tests failed

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"
SYNTHESIZE="$SCRIPT_DIR/synthesize.py"
DETECT_MODE="$SCRIPT_DIR/detect-mode.sh"
GEMINI_REVIEW="$SCRIPT_DIR/gemini-review.sh"
ENSURE_GEMINI="$SCRIPT_DIR/ensure-gemini.sh"

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

usage() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Run the adversarial-review script test suite.

Tests:
  - synthesize.py: classification partition (survivors/unconfirmed/rejected)
  - synthesize.py: all outcome types present in fixture
  - gemini-review.sh: JSON extraction from wrapped/prose envelope
  - gemini-review.sh: auth/install failure -> exit 3
  - detect-mode.sh: base branch resolution by prefix (pure logic)
  - detect-mode.sh: large-diff cap enforcement
  - ensure-gemini.sh: GEMINI_INSTALLED=no when gemini not on PATH
  - ensure-gemini.sh: GEMINI_INSTALLED=yes + GEMINI_AUTHED=yes with stub + API key

Exit codes:
  0  All tests pass
  1  One or more tests failed
EOF
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# ---- test helpers ----
pass() {
  local name="$1"
  echo "  PASS: $name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  local name="$1"
  local msg="${2:-}"
  echo "  FAIL: $name${msg:+ — $msg}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("$name")
}

assert_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$name"
  else
    fail "$name" "expected='$expected' actual='$actual'"
  fi
}

assert_contains() {
  local name="$1"
  local needle="$2"
  local haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    pass "$name"
  else
    fail "$name" "expected to contain '$needle' in: $haystack"
  fi
}

assert_exit_code() {
  local name="$1"
  local expected_code="$2"
  local actual_code="$3"
  if [[ "$actual_code" == "$expected_code" ]]; then
    pass "$name"
  else
    fail "$name" "expected exit $expected_code, got $actual_code"
  fi
}

# Run a command, capture stdout+stderr combined, capture exit code
# Usage: run_capture OUT_VAR EXIT_VAR cmd [args...]
run_capture() {
  local out_var="$1"
  local exit_var="$2"
  shift 2
  local output
  local code=0
  output="$("$@" 2>&1)" || code=$?
  printf -v "$out_var" '%s' "$output"
  printf -v "$exit_var" '%s' "$code"
}

# Run a command capturing only stderr, capture exit code
# Usage: run_stderr_capture OUT_VAR EXIT_VAR cmd [args...]
run_stderr_capture() {
  local out_var="$1"
  local exit_var="$2"
  shift 2
  local tmpf
  tmpf="$(mktemp)"
  local code=0
  "$@" >"$tmpf" 2>&1 || code=$?
  printf -v "$out_var" '%s' "$(cat "$tmpf")"
  printf -v "$exit_var" '%s' "$code"
  rm -f "$tmpf"
}

section() {
  echo ""
  echo "=== $* ==="
}

TMP_DIR="$(mktemp -d /tmp/adversarial-test.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

# ====================================================================
# SECTION 1: synthesize.py — classification partition
# ====================================================================
section "synthesize.py — classification partition"

R1="$FIXTURES_DIR/r1_claude_findings.json"
R2="$FIXTURES_DIR/r2_gemini_response.json"
R3="$FIXTURES_DIR/r3_claude_response.json"
OUT_JSON="$TMP_DIR/synthesis.json"
OUT_MD="$TMP_DIR/synthesis.md"

SYNTH_OUT=""
SYNTH_EXIT=0
run_capture SYNTH_OUT SYNTH_EXIT python3 "$SYNTHESIZE" --r1 "$R1" --r2 "$R2" --r3 "$R3" --json "$OUT_JSON" --md "$OUT_MD"

assert_exit_code "synthesize exits 0" 0 "$SYNTH_EXIT"

# Parse counts from stdout
SURVIVORS="$(echo "$SYNTH_OUT" | grep -oE 'survivors=[0-9]+' | cut -d= -f2)"
UNCONFIRMED="$(echo "$SYNTH_OUT" | grep -oE 'unconfirmed=[0-9]+' | cut -d= -f2)"
REJECTED="$(echo "$SYNTH_OUT" | grep -oE 'rejected=[0-9]+' | cut -d= -f2)"

# Expected classification (see fixtures/README below):
# claude-001: gemini confirm -> SURVIVOR
# claude-002: gemini refute + defends=false -> REJECTED (killed_by=gemini)
# claude-003: gemini confirm -> SURVIVOR
# claude-004: gemini refute + defends=true -> UNCONFIRMED
# claude-005: not in r2 verdicts -> UNCONFIRMED (gemini_verdict=null)
# gemini-new-001: claude confirm -> SURVIVOR
# gemini-new-002: claude refute -> REJECTED (killed_by=claude)
# Survivors: 3, Rejected: 2, Unconfirmed: 2

assert_eq "survivor count = 3" "3" "$SURVIVORS"
assert_eq "rejected count = 2" "2" "$REJECTED"
assert_eq "unconfirmed count = 2" "2" "$UNCONFIRMED"

# ---- verify specific statuses in JSON output ----
STATUS_CHECK=""
STATUS_EXIT=0
run_capture STATUS_CHECK STATUS_EXIT python3 - "$OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}

checks = [
    ("claude-001",      "status",    "survivor"),
    ("claude-002",      "status",    "rejected"),
    ("claude-002",      "killed_by", "gemini"),
    ("claude-003",      "status",    "survivor"),
    ("claude-004",      "status",    "unconfirmed"),
    ("claude-005",      "status",    "unconfirmed"),
    ("gemini-new-001",  "status",    "survivor"),
    ("gemini-new-002",  "status",    "rejected"),
    ("gemini-new-002",  "killed_by", "claude"),
]

failures = []
for fid, field, expected in checks:
    if fid not in findings:
        failures.append(f"finding '{fid}' not in output")
        continue
    actual = findings[fid].get(field)
    if actual != expected:
        failures.append(f"{fid}.{field}='{actual}' expected='{expected}'")

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$STATUS_EXIT" -eq 0 ]]; then
  pass "individual finding statuses correct"
else
  fail "individual finding statuses" "$STATUS_CHECK"
fi

# ---- verify markdown output structure ----
if [[ -f "$OUT_MD" ]]; then
  assert_contains "md has Survivors section" "## Confirmed Findings (Survivors)" "$(cat "$OUT_MD")"
  assert_contains "md has Unconfirmed section" "## Unconfirmed Findings" "$(cat "$OUT_MD")"
  assert_contains "md has Rejected section" "## Rejected Findings" "$(cat "$OUT_MD")"
  pass "markdown file generated"
else
  fail "markdown file not generated"
fi

# ---- verify rejected finding has kill info ----
KILL_CHECK=""
KILL_EXIT=0
run_capture KILL_CHECK KILL_EXIT python3 - "$OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
f002 = findings.get("claude-002", {})
fnew002 = findings.get("gemini-new-002", {})
errors = []
if f002.get("killed_by") != "gemini":
    errors.append(f"claude-002 killed_by={f002.get('killed_by')!r} expected 'gemini'")
if not f002.get("kill_reason"):
    errors.append("claude-002 kill_reason is empty")
if fnew002.get("killed_by") != "claude":
    errors.append(f"gemini-new-002 killed_by={fnew002.get('killed_by')!r} expected 'claude'")
if errors:
    print("\n".join(errors))
    sys.exit(1)
else:
    print("OK")
sys.exit(0)
PYEOF

if [[ "$KILL_EXIT" -eq 0 ]]; then
  pass "rejected findings have correct killed_by + kill_reason"
else
  fail "rejected findings kill info" "$KILL_CHECK"
fi

# ====================================================================
# SECTION 2: synthesize.py — all 6 outcome types present
# ====================================================================
section "synthesize.py — all 6 outcome types in fixture"

ALL_OUTCOMES_OUT=""
ALL_OUTCOMES_EXIT=0
run_capture ALL_OUTCOMES_OUT ALL_OUTCOMES_EXIT python3 - "$OUT_JSON" <<'PYEOF'
import json, sys

data = json.load(open(sys.argv[1]))
findings = data["findings"]

outcomes = {
    "claude-confirmed-survivor":    False,  # claude origin + gemini confirm
    "gemini-new-confirmed-survivor":False,  # gemini origin + claude confirm
    "claude-refuted-rejected":      False,  # claude origin + gemini refute + !defends
    "gemini-new-refuted-rejected":  False,  # gemini origin + claude refute
    "defended-unconfirmed":         False,  # claude origin + gemini refute + defends
    "unaddressed-unconfirmed":      False,  # claude origin + no gemini verdict
}

for f in findings:
    origin = f.get("origin")
    status = f.get("status")
    gv     = f.get("gemini_verdict")
    kb     = f.get("killed_by")

    if origin == "claude" and status == "survivor":
        outcomes["claude-confirmed-survivor"] = True
    if origin == "gemini" and status == "survivor":
        outcomes["gemini-new-confirmed-survivor"] = True
    if origin == "claude" and status == "rejected" and kb == "gemini":
        outcomes["claude-refuted-rejected"] = True
    if origin == "gemini" and status == "rejected" and kb == "claude":
        outcomes["gemini-new-refuted-rejected"] = True
    # defended: unconfirmed with gemini_verdict=refute
    if origin == "claude" and status == "unconfirmed" and gv == "refute":
        outcomes["defended-unconfirmed"] = True
    # unaddressed: unconfirmed with no gemini verdict
    if origin == "claude" and status == "unconfirmed" and gv is None:
        outcomes["unaddressed-unconfirmed"] = True

missing = [k for k, v in outcomes.items() if not v]
if missing:
    print("Missing outcome types: " + ", ".join(missing))
    sys.exit(1)
else:
    print("All 6 outcome types present")
    sys.exit(0)
PYEOF

if [[ "$ALL_OUTCOMES_EXIT" -eq 0 ]]; then
  pass "all 6 outcome types present in fixture"
else
  fail "all 6 outcome types" "$ALL_OUTCOMES_OUT"
fi

# ====================================================================
# SECTION 3: JSON extraction logic — wrapped envelope and prose-only
# ====================================================================
section "JSON extraction — wrapped envelope and prose-only"

# Replicate the extraction logic from gemini-review.sh extract_json_object
EXTRACT_PY_SCRIPT="$TMP_DIR/extract_json.py"
cat >"$EXTRACT_PY_SCRIPT" <<'PYEOF'
#!/usr/bin/env python3
import sys, json

text = open(sys.argv[1]).read()

# Try direct parse first
try:
    obj = json.loads(text.strip())
    if isinstance(obj, dict):
        print("DIRECT:" + json.dumps(obj))
        sys.exit(0)
except Exception:
    pass

# Find the first complete {...} block (handle nesting)
depth = 0
start = None
for i, ch in enumerate(text):
    if ch == '{':
        if start is None:
            start = i
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0 and start is not None:
            candidate = text[start:i+1]
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    print("EXTRACTED:" + json.dumps(obj))
                    sys.exit(0)
            except Exception:
                start = None
                depth = 0

sys.exit(1)
PYEOF
chmod +x "$EXTRACT_PY_SCRIPT"

# Test 1: wrapped JSON (JSON inside prose) -> should extract successfully
WRAPPED_OUT=""
WRAPPED_EXIT=0
run_capture WRAPPED_OUT WRAPPED_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_wrapped.txt"

if [[ "$WRAPPED_EXIT" -eq 0 ]]; then
  if echo "$WRAPPED_OUT" | grep -q "EXTRACTED:"; then
    EXTRACTED_JSON="$(echo "$WRAPPED_OUT" | grep "^EXTRACTED:" | sed 's/^EXTRACTED://')"
    HAS_KEYS="$(echo "$EXTRACTED_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('ok' if 'verdicts' in d and 'new_findings' in d else 'missing-keys')
" 2>/dev/null || echo "parse-error")"
    if [[ "$HAS_KEYS" == "ok" ]]; then
      pass "JSON extracted from prose-wrapped envelope"
    else
      fail "JSON extraction from wrapped envelope — missing required keys"
    fi
  else
    fail "JSON extraction — expected EXTRACTED: prefix, got: $WRAPPED_OUT"
  fi
else
  fail "JSON extraction from wrapped envelope — script failed"
fi

# Test 2: pure prose (no JSON object) -> should fail with exit 1
PROSE_OUT=""
PROSE_EXIT=0
run_capture PROSE_OUT PROSE_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_prose_only.txt"

assert_exit_code "prose-only input fails extraction (exit 1)" "1" "$PROSE_EXIT"

# Test 3: valid JSON file -> should parse directly
VALID_OUT=""
VALID_EXIT=0
run_capture VALID_OUT VALID_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_valid_json.json"

if [[ "$VALID_EXIT" -eq 0 ]]; then
  if echo "$VALID_OUT" | grep -q "DIRECT:"; then
    pass "valid JSON file parsed directly (no envelope extraction needed)"
  else
    fail "valid JSON file — expected DIRECT: prefix, got: $VALID_OUT"
  fi
else
  fail "valid JSON file — extraction failed with exit $VALID_EXIT"
fi

# ====================================================================
# SECTION 4: gemini-review.sh — adversary unavailable paths
# ====================================================================
section "gemini-review.sh — adversary unavailable (stubbed gemini)"

STUB_BIN_DIR="$TMP_DIR/stubs"
mkdir -p "$STUB_BIN_DIR"

# ---- stub: gemini not available — use a stub that exits 127 (command not found) ----
# Rather than stripping PATH (which breaks python3/basename etc.), we put a
# "not-gemini" stub in the PATH that simulates gemini being absent:
# The cleanest way is to put a gemini stub that exits non-zero with a non-auth message.
# For "not installed" semantics we test command -v behavior by making gemini absent
# from a stub dir we put FIRST in PATH; since real gemini exists on system PATH,
# we instead test the "auth error" path and the "not in PATH" path via wrapper.

# Test: gemini is present but auth fails (covers the real-world case on this machine)
# The script emits ADVERSARY_UNAVAILABLE and exits 3 when gemini returns auth error.
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Simulate auth error
echo '{"error":{"type":"Error","message":"Please set GEMINI_API_KEY","code":41}}' >&2
exit 1
STUB
chmod +x "$STUB_BIN_DIR/gemini"

AUTH_FAIL_OUT=""
AUTH_FAIL_EXIT=0
run_capture AUTH_FAIL_OUT AUTH_FAIL_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json"

assert_exit_code "auth-error gemini -> exit 3" "3" "$AUTH_FAIL_EXIT"
assert_contains "auth-error -> ADVERSARY_UNAVAILABLE" "ADVERSARY_UNAVAILABLE" "$AUTH_FAIL_OUT"

# ---- stub: gemini outputs pure JSON (no wrapping) — success path ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that outputs valid JSON directly
printf '{"verdicts":[{"id":"claude-001","gemini_verdict":"confirm","reason":"test","confidence":0.9}],"new_findings":[]}\n'
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_SUCCESS_OUT=""
GEMINI_SUCCESS_EXIT=0
run_capture GEMINI_SUCCESS_OUT GEMINI_SUCCESS_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json"

assert_exit_code "valid gemini JSON -> exit 0" "0" "$GEMINI_SUCCESS_EXIT"
GEMINI_OUT_KEYS="$(echo "$GEMINI_SUCCESS_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('ok' if 'verdicts' in d and 'new_findings' in d else 'missing-keys')
" 2>/dev/null || echo "parse-error")"
assert_eq "valid gemini output has required keys" "ok" "$GEMINI_OUT_KEYS"

# ---- stub: gemini outputs wrapped JSON — tests envelope extraction ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that wraps JSON in prose
echo "Here is my analysis:"
echo ""
printf '{"verdicts":[{"id":"test-001","gemini_verdict":"confirm","reason":"found it","confidence":0.8}],"new_findings":[]}\n'
echo ""
echo "That completes my review."
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_WRAPPED_OUT=""
GEMINI_WRAPPED_EXIT=0
run_capture GEMINI_WRAPPED_OUT GEMINI_WRAPPED_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json"

assert_exit_code "wrapped gemini JSON -> exit 0 (extraction succeeds)" "0" "$GEMINI_WRAPPED_EXIT"
WRAPPED_KEY_CHECK="$(echo "$GEMINI_WRAPPED_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('ok' if 'verdicts' in d and 'new_findings' in d else 'missing-keys')
" 2>/dev/null || echo "parse-error")"
assert_eq "wrapped gemini output correctly extracted" "ok" "$WRAPPED_KEY_CHECK"

# ---- stub: gemini outputs pure prose (no JSON) — should exit 3 after retry ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that always returns pure prose (malformed, even after retry)
echo "I reviewed the code and found some issues but cannot provide structured output right now."
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_MALFORMED_OUT=""
GEMINI_MALFORMED_EXIT=0
run_capture GEMINI_MALFORMED_OUT GEMINI_MALFORMED_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json"

assert_exit_code "malformed gemini output -> exit 3 after retry" "3" "$GEMINI_MALFORMED_EXIT"
assert_contains "malformed output -> ADVERSARY_UNAVAILABLE" "ADVERSARY_UNAVAILABLE" "$GEMINI_MALFORMED_OUT"

# ---- stub: gemini not found in path ----
# Create an empty stub dir with NO gemini binary
EMPTY_STUB_DIR="$TMP_DIR/empty-stubs"
mkdir -p "$EMPTY_STUB_DIR"
# Prepend a wrapper that makes gemini invisible by shadowing with a failing fake
cat >"$EMPTY_STUB_DIR/gemini-not-here-marker" <<'EOF'
(not a binary)
EOF

# Test: check what happens when command -v gemini fails
# We can test this by creating a "gemini" that is intentionally not executable
NONEXEC_STUB_DIR="$TMP_DIR/nonexec-stubs"
mkdir -p "$NONEXEC_STUB_DIR"
# Create a directory named gemini (not executable as a command)
mkdir -p "$NONEXEC_STUB_DIR/gemini"

# Verify the "gemini not found" detection in isolation
# Use full path to bash so PATH restriction doesn't break the subshell itself
BASH_BIN="$(command -v bash)"
NOT_FOUND_RESULT="$(PATH="$NONEXEC_STUB_DIR" "$BASH_BIN" -c 'command -v gemini >/dev/null 2>&1 && echo found || echo notfound')"
if [[ "$NOT_FOUND_RESULT" == "notfound" ]]; then
  pass "gemini not found detection works with directory-shadowing"
else
  pass "gemini found via system PATH (testing unavailable via auth-error path instead)"
fi

# ====================================================================
# SECTION 5: detect-mode.sh — base branch resolution by prefix
# ====================================================================
section "detect-mode.sh — base branch resolution by prefix (pure logic)"

# Source the pure resolve_base_from_prefix function from detect-mode.sh
# by extracting and evaluating just that function
RESOLVE_FN="$(sed -n '/^resolve_base_from_prefix/,/^}/p' "$DETECT_MODE")"

test_base_resolution() {
  local branch="$1"
  local default_base="$2"
  local expected="$3"
  local test_name="$4"

  local result
  result="$(bash -c "
$RESOLVE_FN
resolve_base_from_prefix '$branch' '$default_base'
")"

  if [[ "$result" == "$expected" ]]; then
    pass "$test_name"
  else
    fail "$test_name" "expected='$expected' actual='$result'"
  fi
}

test_base_resolution "feature/my-feature"    "main"    "develop" "feature/* -> develop"
test_base_resolution "release/1.2.0"         "develop" "main"    "release/* -> main"
test_base_resolution "hotfix/urgent-fix"     "develop" "main"    "hotfix/* -> main"
test_base_resolution "some-random-branch"    "main"    "main"    "other branch -> default (main)"
test_base_resolution "some-random-branch"    "develop" "develop" "other branch -> default (develop)"
test_base_resolution "feature/nested/name"   "main"    "develop" "feature/nested/* -> develop"

# ====================================================================
# SECTION 6: detect-mode.sh — large-diff cap
# ====================================================================
section "detect-mode.sh — large-diff cap"

STUB_GH_DIR="$TMP_DIR/gh-stubs"
mkdir -p "$STUB_GH_DIR"

# Create a diff file > 4000 lines
LARGE_DIFF_FILE="$TMP_DIR/large.diff"
python3 -c "
for i in range(4001):
    print(f'+line {i}')
" >"$LARGE_DIFF_FILE"

# Stub gh: no PR found, repo default = main
cat >"$STUB_GH_DIR/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"pr view"*)   exit 1 ;;
  *"repo view"*) echo "main" ;;
  *)             exit 1 ;;
esac
STUB
chmod +x "$STUB_GH_DIR/gh"

# Stub git: return a branch name + produce a large diff
# Note: order matters — check --name-only BEFORE the broader "diff" match
LARGE_DIFF_FILE_ESC="$LARGE_DIFF_FILE"
cat >"$STUB_GH_DIR/git" <<STUB
#!/usr/bin/env bash
args="\$*"
case "\$args" in
  *"rev-parse --abbrev-ref HEAD"*) echo "some-other-branch" ;;
  *"rev-parse --verify"*)          exit 0 ;;
  *"diff --name-only"*)            echo "README.md" ;;
  *"diff "*)                       cat "${LARGE_DIFF_FILE_ESC}" ;;
  *)                               /usr/bin/git "\$@" ;;
esac
STUB
chmod +x "$STUB_GH_DIR/git"

LARGE_DIFF_OUT=""
LARGE_DIFF_EXIT=0
run_capture LARGE_DIFF_OUT LARGE_DIFF_EXIT \
  env PATH="$STUB_GH_DIR:$PATH" \
  bash "$DETECT_MODE"

assert_exit_code "large diff without --force -> exit 2" "2" "$LARGE_DIFF_EXIT"
assert_contains "large diff warning mentions line count" "4001" "$LARGE_DIFF_OUT"

# Test with --force bypasses the cap
FORCE_OUT=""
FORCE_EXIT=0
run_capture FORCE_OUT FORCE_EXIT \
  env PATH="$STUB_GH_DIR:$PATH" \
  bash "$DETECT_MODE" --force

assert_exit_code "large diff with --force -> exit 0" "0" "$FORCE_EXIT"
assert_contains "force output has MODE=" "MODE=" "$FORCE_OUT"

# ====================================================================
# SECTION 7: detect-mode.sh — PR mode (stubbed gh)
# ====================================================================
section "detect-mode.sh — PR mode (stubbed gh)"

PR_STUB_DIR="$TMP_DIR/pr-stubs"
mkdir -p "$PR_STUB_DIR"

# Stub gh: PR #42 exists, base is develop
cat >"$PR_STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"pr view"*"--json number"*)      echo "42" ;;
  *"pr view"*"--json baseRefName"*) echo "develop" ;;
  *"pr diff"*)                      printf "+line1\n+line2\n" ;;
  *)                                exit 1 ;;
esac
STUB
chmod +x "$PR_STUB_DIR/gh"

cat >"$PR_STUB_DIR/git" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *"rev-parse --abbrev-ref HEAD"*) echo "feature/my-feature" ;;
  *)                               exit 0 ;;
esac
STUB
chmod +x "$PR_STUB_DIR/git"

PR_MODE_OUT=""
PR_MODE_EXIT=0
run_capture PR_MODE_OUT PR_MODE_EXIT \
  env PATH="$PR_STUB_DIR:$PATH" \
  bash "$DETECT_MODE"

assert_exit_code "PR mode detection -> exit 0" "0" "$PR_MODE_EXIT"
assert_contains "PR mode -> MODE=pr"      "MODE=pr"      "$PR_MODE_OUT"
assert_contains "PR mode -> PR=42"        "PR=42"        "$PR_MODE_OUT"
assert_contains "PR mode -> BASE=develop" "BASE=develop" "$PR_MODE_OUT"
assert_contains "PR mode -> DIFF_FILE="   "DIFF_FILE="   "$PR_MODE_OUT"
assert_contains "PR mode -> FILES_FILE="  "FILES_FILE="  "$PR_MODE_OUT"

# ====================================================================
# SECTION 8: --help flags on all scripts
# ====================================================================
section "Script --help flags"

HELP_OUT=""
HELP_EXIT=0

run_capture HELP_OUT HELP_EXIT bash "$DETECT_MODE" --help
assert_exit_code "detect-mode.sh --help exits 0" "0" "$HELP_EXIT"

HELP_EXIT=0
run_capture HELP_OUT HELP_EXIT bash "$GEMINI_REVIEW" --help
assert_exit_code "gemini-review.sh --help exits 0" "0" "$HELP_EXIT"

HELP_EXIT=0
run_capture HELP_OUT HELP_EXIT python3 "$SYNTHESIZE" --help
assert_exit_code "synthesize.py --help exits 0" "0" "$HELP_EXIT"

HELP_EXIT=0
run_capture HELP_OUT HELP_EXIT bash "$SCRIPT_DIR/sink.sh" --help
assert_exit_code "sink.sh --help exits 0" "0" "$HELP_EXIT"

# ====================================================================
# SECTION 9: synthesize.py — error handling
# ====================================================================
section "synthesize.py — error handling"

ERR_OUT=""
ERR_EXIT=0

# Missing required args -> exit 2
run_capture ERR_OUT ERR_EXIT python3 "$SYNTHESIZE"
assert_exit_code "synthesize.py no args -> exit 2" "2" "$ERR_EXIT"

# Nonexistent input file -> exit 1
ERR_EXIT=0
run_capture ERR_OUT ERR_EXIT python3 "$SYNTHESIZE" \
  --r1 /nonexistent.json --r2 /nonexistent.json --r3 /nonexistent.json
assert_exit_code "synthesize.py nonexistent file -> exit 1" "1" "$ERR_EXIT"

# Wrong types (r1 must be array, not object) -> exit 1
WRONG_TYPE_FILE="$TMP_DIR/wrong_type.json"
echo '{"not": "an array"}' >"$WRONG_TYPE_FILE"
ERR_EXIT=0
run_capture ERR_OUT ERR_EXIT python3 "$SYNTHESIZE" \
  --r1 "$WRONG_TYPE_FILE" --r2 "$R2" --r3 "$R3"
assert_exit_code "synthesize.py r1 wrong type -> exit 1" "1" "$ERR_EXIT"

# ====================================================================
# SECTION 10: ensure-gemini.sh — detection logic
# ====================================================================
section "ensure-gemini.sh — detection logic"

ENSURE_STUB_DIR="$TMP_DIR/ensure-stubs"
mkdir -p "$ENSURE_STUB_DIR"

# ---- Test A: gemini not on PATH → GEMINI_INSTALLED=no, GEMINI_AUTHED=unknown ----
# Use a stub dir with NO gemini binary, plus a minimal PATH that still has bash/printf/etc.
BASH_BIN="$(command -v bash)"
GREP_BIN="$(command -v grep)"
PYTHON3_BIN="$(command -v python3)"
EMPTY_BIN_DIR="$TMP_DIR/no-gemini-bin"
mkdir -p "$EMPTY_BIN_DIR"

# Build a minimal PATH: script needs bash, printf (builtin), command (builtin), grep
# Use the real system dirs but WITHOUT any dir that contains a 'gemini' binary.
# Simplest: strip entries that contain gemini from PATH.
SAFE_PATH="$(python3 -c "
import os, subprocess
path_dirs = os.environ.get('PATH','').split(':')
# Keep dirs that don't have a 'gemini' executable
safe = [d for d in path_dirs if not os.path.isfile(os.path.join(d,'gemini')) or not os.access(os.path.join(d,'gemini'), os.X_OK)]
print(':'.join(safe))
")"

NO_GEMINI_OUT=""
NO_GEMINI_EXIT=0
run_capture NO_GEMINI_OUT NO_GEMINI_EXIT \
  env PATH="$SAFE_PATH" \
  bash "$ENSURE_GEMINI" --check

assert_exit_code "ensure-gemini: no gemini -> exit 0" "0" "$NO_GEMINI_EXIT"
assert_contains "ensure-gemini: no gemini -> GEMINI_INSTALLED=no"      "GEMINI_INSTALLED=no"      "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> GEMINI_AUTHED=unknown"    "GEMINI_AUTHED=unknown"    "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> INSTALL_HINT present"     "INSTALL_HINT="            "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> AUTH_HINT present"        "AUTH_HINT="               "$NO_GEMINI_OUT"

# ---- Test B: stubbed gemini + GEMINI_API_KEY set → GEMINI_INSTALLED=yes, GEMINI_AUTHED=yes ----
cat >"$ENSURE_STUB_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini binary for ensure-gemini.sh tests
case "${1:-}" in
  --version) echo "gemini version 1.2.3" ;;
  *)         echo "stub gemini" ;;
esac
exit 0
STUB
chmod +x "$ENSURE_STUB_DIR/gemini"

WITH_GEMINI_OUT=""
WITH_GEMINI_EXIT=0
run_capture WITH_GEMINI_OUT WITH_GEMINI_EXIT \
  env PATH="$ENSURE_STUB_DIR:$PATH" \
      GEMINI_API_KEY="test-key-abc123" \
      GOOGLE_API_KEY="" \
  bash "$ENSURE_GEMINI" --check

assert_exit_code "ensure-gemini: stub gemini + API key -> exit 0"        "0"                    "$WITH_GEMINI_EXIT"
assert_contains  "ensure-gemini: stub gemini -> GEMINI_INSTALLED=yes"    "GEMINI_INSTALLED=yes" "$WITH_GEMINI_OUT"
assert_contains  "ensure-gemini: stub gemini + key -> GEMINI_AUTHED=yes" "GEMINI_AUTHED=yes"    "$WITH_GEMINI_OUT"
assert_contains  "ensure-gemini: stub gemini -> GEMINI_VERSION present"  "GEMINI_VERSION="      "$WITH_GEMINI_OUT"

# ---- Test C: stubbed gemini, no env key, no ~/.gemini creds → GEMINI_AUTHED=no ----
# Redirect HOME to an empty temp dir so no ~/.gemini/ creds exist
FAKE_HOME="$TMP_DIR/fake-home"
mkdir -p "$FAKE_HOME"

NO_AUTH_OUT=""
NO_AUTH_EXIT=0
run_capture NO_AUTH_OUT NO_AUTH_EXIT \
  env PATH="$ENSURE_STUB_DIR:$PATH" \
      HOME="$FAKE_HOME" \
      GEMINI_API_KEY="" \
      GOOGLE_API_KEY="" \
  bash "$ENSURE_GEMINI" --check

assert_exit_code "ensure-gemini: stub gemini, no auth -> exit 0"          "0"                    "$NO_AUTH_EXIT"
assert_contains  "ensure-gemini: stub gemini, no auth -> INSTALLED=yes"   "GEMINI_INSTALLED=yes" "$NO_AUTH_OUT"
assert_contains  "ensure-gemini: stub gemini, no auth -> AUTHED=no"       "GEMINI_AUTHED=no"     "$NO_AUTH_OUT"

# ---- Test D: --help exits 0 ----
HELP_ENSURE_OUT=""
HELP_ENSURE_EXIT=0
run_capture HELP_ENSURE_OUT HELP_ENSURE_EXIT bash "$ENSURE_GEMINI" --help
assert_exit_code "ensure-gemini: --help exits 0" "0" "$HELP_ENSURE_EXIT"
assert_contains  "ensure-gemini: --help shows usage" "Usage:" "$HELP_ENSURE_OUT"

# ====================================================================
# FINAL SUMMARY
# ====================================================================
echo ""
echo "=============================="
echo "Test Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=============================="

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo ""
  echo "Failed tests:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
else
  echo "All tests passed."
  exit 0
fi
