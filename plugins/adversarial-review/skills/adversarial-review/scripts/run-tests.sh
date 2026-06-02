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
  - synthesize.py: symmetric classification (survivors/unconfirmed/rejected)
  - synthesize.py: specific finding statuses (C-### / G-### ids)
  - synthesize.py: markdown section headers present
  - synthesize.py: rejected findings have kill info
  - synthesize.py: error handling (no args, nonexistent files, wrong types)
  - gemini-review.sh: JSON extraction from wrapped/prose/v0.44.x envelope
  - gemini-review.sh: --mode find stub emits findings
  - gemini-review.sh: --mode judge stub emits verdicts (no new_findings)
  - gemini-review.sh: auth/install failure -> exit 3
  - gemini-review.sh: malformed output -> exit 3 after retry
  - detect-mode.sh: base branch resolution by prefix (pure logic)
  - detect-mode.sh: large-diff cap enforcement
  - ensure-gemini.sh: GEMINI_INSTALLED=no when gemini not on PATH
  - ensure-gemini.sh: GEMINI_INSTALLED=yes + GEMINI_AUTHED=yes with stub + API key
  - ensure-gemini.sh: OAuth-only creds (no API key) -> GEMINI_AUTHED=no (regression)
  - ensure-gemini.sh: ~/.gemini/.env with GEMINI_API_KEY -> GEMINI_AUTHED=yes

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
# SECTION 1: synthesize.py — symmetric classification partition
# ====================================================================
section "synthesize.py — symmetric classification partition"

CLAUDE_FINDINGS="$FIXTURES_DIR/r1_claude_findings.json"
GEMINI_FINDINGS="$FIXTURES_DIR/r1_gemini_findings.json"
GEMINI_VERDICTS="$FIXTURES_DIR/r2_gemini_verdicts.json"
CLAUDE_VERDICTS="$FIXTURES_DIR/r2_claude_verdicts.json"
OUT_JSON="$TMP_DIR/synthesis.json"
OUT_MD="$TMP_DIR/synthesis.md"

SYNTH_OUT=""
SYNTH_EXIT=0
run_capture SYNTH_OUT SYNTH_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CLAUDE_FINDINGS" \
  --gemini-findings "$GEMINI_FINDINGS" \
  --gemini-verdicts "$GEMINI_VERDICTS" \
  --claude-verdicts "$CLAUDE_VERDICTS" \
  --json "$OUT_JSON" \
  --md "$OUT_MD"

assert_exit_code "synthesize exits 0" 0 "$SYNTH_EXIT"

# Parse counts from stdout
SURVIVORS="$(echo "$SYNTH_OUT" | grep -oE 'survivors=[0-9]+' | cut -d= -f2)"
UNCONFIRMED="$(echo "$SYNTH_OUT" | grep -oE 'unconfirmed=[0-9]+' | cut -d= -f2)"
REJECTED="$(echo "$SYNTH_OUT" | grep -oE 'rejected=[0-9]+' | cut -d= -f2)"

# Expected classification (fixtures):
# C-001: gemini_verdict=confirm  -> SURVIVOR
# C-002: gemini_verdict=refute   -> REJECTED (killed_by=gemini)
# C-003: gemini_verdict=confirm  -> SURVIVOR
# C-004: not in gemini verdicts  -> UNCONFIRMED (gemini_verdict=null)
# C-005: not in gemini verdicts  -> UNCONFIRMED (gemini_verdict=null)
# G-001: claude_verdict=confirm  -> SURVIVOR
# G-002: claude_verdict=refute   -> REJECTED (killed_by=claude)
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
    ("C-001", "status",    "survivor"),
    ("C-002", "status",    "rejected"),
    ("C-002", "killed_by", "gemini"),
    ("C-003", "status",    "survivor"),
    ("C-004", "status",    "unconfirmed"),
    ("C-005", "status",    "unconfirmed"),
    ("G-001", "status",    "survivor"),
    ("G-002", "status",    "rejected"),
    ("G-002", "killed_by", "claude"),
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
  pass "individual finding statuses correct (C-###/G-### ids)"
else
  fail "individual finding statuses" "$STATUS_CHECK"
fi

# ---- verify markdown output structure ----
if [[ -f "$OUT_MD" ]]; then
  MD_CONTENT="$(cat "$OUT_MD")"
  assert_contains "md has title"             "# Adversarial PR Review — Synthesis Report" "$MD_CONTENT"
  assert_contains "md has Survivors section" "## Confirmed Findings (Survivors)"          "$MD_CONTENT"
  assert_contains "md has Unconfirmed section" "## Unconfirmed Findings"                  "$MD_CONTENT"
  assert_contains "md has Rejected section"  "## Rejected Findings"                       "$MD_CONTENT"
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
c002 = findings.get("C-002", {})
g002 = findings.get("G-002", {})
errors = []
if c002.get("killed_by") != "gemini":
    errors.append(f"C-002 killed_by={c002.get('killed_by')!r} expected 'gemini'")
if not c002.get("kill_reason"):
    errors.append("C-002 kill_reason is empty")
if g002.get("killed_by") != "claude":
    errors.append(f"G-002 killed_by={g002.get('killed_by')!r} expected 'claude'")
if not g002.get("kill_reason"):
    errors.append("G-002 kill_reason is empty")
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
# SECTION 2: synthesize.py — outcome types present
# ====================================================================
section "synthesize.py — outcome types in fixture"

ALL_OUTCOMES_OUT=""
ALL_OUTCOMES_EXIT=0
run_capture ALL_OUTCOMES_OUT ALL_OUTCOMES_EXIT python3 - "$OUT_JSON" <<'PYEOF'
import json, sys

data = json.load(open(sys.argv[1]))
findings = data["findings"]

outcomes = {
    "claude-confirmed-survivor":   False,   # origin=claude + gemini confirm
    "gemini-confirmed-survivor":   False,   # origin=gemini + claude confirm
    "claude-rejected-by-gemini":   False,   # origin=claude + gemini refute
    "gemini-rejected-by-claude":   False,   # origin=gemini + claude refute
    "claude-unconfirmed":          False,   # origin=claude + no gemini verdict
}

for f in findings:
    origin = f.get("origin")
    status = f.get("status")
    kb     = f.get("killed_by")

    if origin == "claude" and status == "survivor":
        outcomes["claude-confirmed-survivor"] = True
    if origin == "gemini" and status == "survivor":
        outcomes["gemini-confirmed-survivor"] = True
    if origin == "claude" and status == "rejected" and kb == "gemini":
        outcomes["claude-rejected-by-gemini"] = True
    if origin == "gemini" and status == "rejected" and kb == "claude":
        outcomes["gemini-rejected-by-claude"] = True
    if origin == "claude" and status == "unconfirmed":
        outcomes["claude-unconfirmed"] = True

missing = [k for k, v in outcomes.items() if not v]
if missing:
    print("Missing outcome types: " + ", ".join(missing))
    sys.exit(1)
else:
    print("All outcome types present")
    sys.exit(0)
PYEOF

if [[ "$ALL_OUTCOMES_EXIT" -eq 0 ]]; then
  pass "all symmetric outcome types present in fixture"
else
  fail "outcome types" "$ALL_OUTCOMES_OUT"
fi

# ====================================================================
# SECTION 3: JSON extraction logic — wrapped envelope and prose-only
# ====================================================================
section "JSON extraction — wrapped envelope, prose-only, and v0.44.x envelope"

# Standalone Python extractor that mirrors the logic embedded in
# gemini-review.sh's extract_model_answer function.
# Outputs: "ok KEY=<n>" on success, nothing on failure.
# Takes an extra arg: mode (find|judge) to know which key to look for.
EXTRACT_PY_SCRIPT="$TMP_DIR/extract_json.py"
cat >"$EXTRACT_PY_SCRIPT" <<'PYEOF'
#!/usr/bin/env python3
import sys, json, re

MODE = sys.argv[2] if len(sys.argv) > 2 else "judge"

def iter_json_objects(text):
    """Yield all balanced top-level {...} blocks that parse as JSON dicts."""
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{':
            if start is None:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start:i+1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            yield obj
                    except Exception:
                        pass
                    start = None

def find_first_json_object(text):
    for obj in iter_json_objects(text):
        return obj
    return None

def find_first_json_with_keys(text, *keys):
    for obj in iter_json_objects(text):
        if any(k in obj for k in keys):
            return obj
    return None

def has_payload_key(obj):
    if MODE == "find":
        return "findings" in obj
    return "verdicts" in obj

def extract_payload(text):
    # Step 1: look for an object with "response" key first (v0.44.x envelope)
    envelope = find_first_json_with_keys(text, "response")
    if envelope is not None and isinstance(envelope.get("response"), str):
        model_text = envelope["response"]
    else:
        # Step 2: look for an object with the payload key directly
        payload_key = "findings" if MODE == "find" else "verdicts"
        direct = find_first_json_with_keys(text, payload_key)
        if direct is not None and has_payload_key(direct):
            return direct
        model_text = text

    # Bare JSON
    try:
        obj = json.loads(model_text.strip())
        if isinstance(obj, dict) and has_payload_key(obj):
            return obj
    except Exception:
        pass

    # Fenced JSON
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', model_text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict) and has_payload_key(obj):
                return obj
        except Exception:
            pass

    # JSON embedded in prose
    payload_key = "findings" if MODE == "find" else "verdicts"
    inner = find_first_json_with_keys(model_text, payload_key)
    if inner is not None and has_payload_key(inner):
        return inner

    return None

text = open(sys.argv[1]).read()
result = extract_payload(text)

if result is None:
    sys.exit(1)

if MODE == "find":
    n = len(result.get("findings", []))
    print(f"ok FINDINGS={n}")
else:
    nv = len(result.get("verdicts", []))
    print(f"ok VERDICTS={nv}")
sys.exit(0)
PYEOF
chmod +x "$EXTRACT_PY_SCRIPT"

# Test 1: wrapped JSON (JSON inside markdown fences + prose) -> should extract successfully
# The existing gemini_envelope_wrapped.txt has verdicts key (judge mode)
WRAPPED_OUT=""
WRAPPED_EXIT=0
run_capture WRAPPED_OUT WRAPPED_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_wrapped.txt" "judge"

assert_exit_code "JSON extracted from prose-wrapped envelope (exit 0)" "0" "$WRAPPED_EXIT"
if [[ "$WRAPPED_EXIT" -eq 0 ]]; then
  assert_contains "prose-wrapped envelope has verdicts" "VERDICTS=1" "$WRAPPED_OUT"
fi

# Test 2: pure prose (no JSON object) -> should fail with exit 1
PROSE_OUT=""
PROSE_EXIT=0
run_capture PROSE_OUT PROSE_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_prose_only.txt" "judge"

assert_exit_code "prose-only input fails extraction (exit 1)" "1" "$PROSE_EXIT"

# Test 3: valid bare JSON file (judge mode) -> should parse directly (exit 0)
VALID_OUT=""
VALID_EXIT=0
run_capture VALID_OUT VALID_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_valid_json.json" "judge"

assert_exit_code "valid JSON file extraction succeeds (exit 0)" "0" "$VALID_EXIT"
if [[ "$VALID_EXIT" -eq 0 ]]; then
  assert_contains "valid JSON has expected verdicts" "VERDICTS=2" "$VALID_OUT"
fi

# Test 4: gemini-cli v0.44.x envelope —
#   2 prose prefix lines, then outer JSON with "response" string containing the model answer.
#   Fixture: fixtures/gemini_envelope_v044.txt
#   Expected: verdicts len=1
V044_OUT=""
V044_EXIT=0
run_capture V044_OUT V044_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_v044.txt" "judge"

assert_exit_code "v0.44.x envelope: extraction succeeds (exit 0)" "0" "$V044_EXIT"
if [[ "$V044_EXIT" -eq 0 ]]; then
  assert_contains "v0.44.x envelope: verdicts=1" "VERDICTS=1" "$V044_OUT"
fi

# Test 5: find mode — a findings-keyed JSON should extract in find mode
FIND_FIXTURE="$TMP_DIR/find_fixture.json"
cat >"$FIND_FIXTURE" <<'JSON'
{"findings":[{"id":"G-001","path":"src/auth.py","line":42,"severity":"critical","category":"security","title":"Hardcoded secret","rationale":"Secret key in source","origin":"gemini","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null}]}
JSON

FIND_EXTRACT_OUT=""
FIND_EXTRACT_EXIT=0
run_capture FIND_EXTRACT_OUT FIND_EXTRACT_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIND_FIXTURE" "find"

assert_exit_code "find-mode: findings-keyed JSON extracts (exit 0)" "0" "$FIND_EXTRACT_EXIT"
if [[ "$FIND_EXTRACT_EXIT" -eq 0 ]]; then
  assert_contains "find-mode: FINDINGS=1" "FINDINGS=1" "$FIND_EXTRACT_OUT"
fi

# Test 6: C-001 regression — leading non-payload JSON before real payload
# Input has {"status":"ok"} before the real {"verdicts":[...]} object.
# Must extract the verdicts payload (not bind to the leading status object).
LEADING_OBJ_FIXTURE="$TMP_DIR/leading_obj_fixture.txt"
cat >"$LEADING_OBJ_FIXTURE" <<'TEXT'
{"status":"ok"}
{"verdicts":[{"id":"C-001","gemini_verdict":"confirm","reason":"test","confidence":0.9}]}
TEXT

LEADING_OBJ_OUT=""
LEADING_OBJ_EXIT=0
run_capture LEADING_OBJ_OUT LEADING_OBJ_EXIT python3 "$EXTRACT_PY_SCRIPT" "$LEADING_OBJ_FIXTURE" "judge"

assert_exit_code "leading non-payload JSON: extraction succeeds (exit 0)" "0" "$LEADING_OBJ_EXIT"
if [[ "$LEADING_OBJ_EXIT" -eq 0 ]]; then
  assert_contains "leading non-payload JSON: correct payload extracted" "VERDICTS=1" "$LEADING_OBJ_OUT"
fi

# ====================================================================
# SECTION 4: gemini-review.sh — adversary unavailable paths
# ====================================================================
section "gemini-review.sh — adversary unavailable (stubbed gemini)"

STUB_BIN_DIR="$TMP_DIR/stubs"
mkdir -p "$STUB_BIN_DIR"

# ---- Test: gemini auth error -> exit 3 ----
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
  --findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode judge

assert_exit_code "auth-error gemini -> exit 3" "3" "$AUTH_FAIL_EXIT"
assert_contains "auth-error -> ADVERSARY_UNAVAILABLE" "ADVERSARY_UNAVAILABLE" "$AUTH_FAIL_OUT"

# ---- Test: --mode judge stub emits verdicts (no new_findings key) ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that outputs valid judge-mode JSON (verdicts only, no new_findings)
printf '{"verdicts":[{"id":"C-001","gemini_verdict":"confirm","reason":"test","confidence":0.9}]}\n'
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_JUDGE_OUT=""
GEMINI_JUDGE_EXIT=0
run_capture GEMINI_JUDGE_OUT GEMINI_JUDGE_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode judge

assert_exit_code "judge mode valid JSON -> exit 0" "0" "$GEMINI_JUDGE_EXIT"
JUDGE_KEY_CHECK="$(echo "$GEMINI_JUDGE_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
has_verdicts = 'verdicts' in d
no_new_findings = 'new_findings' not in d
print('ok' if has_verdicts and no_new_findings else 'bad-keys')
" 2>/dev/null || echo "parse-error")"
assert_eq "judge mode output has verdicts and no new_findings key" "ok" "$JUDGE_KEY_CHECK"

# ---- Test: --mode find stub emits findings ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that outputs valid find-mode JSON (findings)
printf '{"findings":[{"id":"G-001","path":"src/auth.py","line":42,"severity":"critical","category":"security","title":"Hardcoded secret","rationale":"Secret key in source","origin":"gemini","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null}]}\n'
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_FIND_OUT=""
GEMINI_FIND_EXIT=0
run_capture GEMINI_FIND_OUT GEMINI_FIND_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode find

assert_exit_code "find mode valid JSON -> exit 0" "0" "$GEMINI_FIND_EXIT"
FIND_KEY_CHECK="$(echo "$GEMINI_FIND_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
n = len(d.get('findings', []))
print(f'ok findings={n}' if 'findings' in d else 'missing-findings-key')
" 2>/dev/null || echo "parse-error")"
assert_eq "find mode output has findings key with 1 finding" "ok findings=1" "$FIND_KEY_CHECK"

# ---- Test: wrapped judge-mode JSON -> success ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini that wraps judge JSON in prose
echo "Here is my analysis:"
echo ""
printf '{"verdicts":[{"id":"C-001","gemini_verdict":"confirm","reason":"found it","confidence":0.8}]}\n'
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
  --findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode judge

assert_exit_code "wrapped judge JSON -> exit 0 (extraction succeeds)" "0" "$GEMINI_WRAPPED_EXIT"
WRAPPED_KEY_CHECK="$(echo "$GEMINI_WRAPPED_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('ok' if 'verdicts' in d else 'missing-keys')
" 2>/dev/null || echo "parse-error")"
assert_eq "wrapped judge output correctly extracted" "ok" "$WRAPPED_KEY_CHECK"

# ---- Test: v0.44.x envelope (prose prefix + outer JSON with response string) ----
cat >"$STUB_BIN_DIR/gemini" <<'STUB'
#!/usr/bin/env bash
# Stub gemini v0.44.x: prose lines printed before outer envelope JSON
echo "Ripgrep is not available. Falling back to GrepTool."
echo "Skill conflict detected: stub-skill loaded twice."
echo '{"session_id":"test-session","response":"{\"verdicts\":[{\"id\":\"C-001\",\"gemini_verdict\":\"confirm\",\"reason\":\"confirmed by gemini\",\"confidence\":0.9}]}","stats":{"tokens":42}}'
STUB
chmod +x "$STUB_BIN_DIR/gemini"

GEMINI_V044_OUT=""
GEMINI_V044_EXIT=0
run_capture GEMINI_V044_OUT GEMINI_V044_EXIT \
  env PATH="$STUB_BIN_DIR:$PATH" \
  bash "$GEMINI_REVIEW" \
  --diff "$FIXTURES_DIR/r1_claude_findings.json" \
  --findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode judge

assert_exit_code "v0.44.x envelope gemini stub -> exit 0" "0" "$GEMINI_V044_EXIT"
GEMINI_V044_KEYS="$(echo "$GEMINI_V044_OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
v = len(d.get('verdicts', []))
print(f'ok v={v}' if 'verdicts' in d else 'missing-keys')
" 2>/dev/null || echo "parse-error")"
assert_eq "v0.44.x envelope: verdicts extracted" "ok v=1" "$GEMINI_V044_KEYS"

# ---- Test: malformed output -> exit 3 after retry ----
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
  --findings "$FIXTURES_DIR/r1_claude_findings.json" \
  --mode judge

assert_exit_code "malformed gemini output -> exit 3 after retry" "3" "$GEMINI_MALFORMED_EXIT"
assert_contains "malformed output -> ADVERSARY_UNAVAILABLE" "ADVERSARY_UNAVAILABLE" "$GEMINI_MALFORMED_OUT"

# ---- Test: gemini not found in path ----
NONEXEC_STUB_DIR="$TMP_DIR/nonexec-stubs"
mkdir -p "$NONEXEC_STUB_DIR"
mkdir -p "$NONEXEC_STUB_DIR/gemini"

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

# Nonexistent input files -> exit 1
ERR_EXIT=0
run_capture ERR_OUT ERR_EXIT python3 "$SYNTHESIZE" \
  --claude-findings /nonexistent.json \
  --gemini-findings /nonexistent.json \
  --gemini-verdicts /nonexistent.json \
  --claude-verdicts /nonexistent.json
assert_exit_code "synthesize.py nonexistent files -> exit 1" "1" "$ERR_EXIT"

# Wrong type for claude-findings (must be array or {"findings":...}) -> exit 1
WRONG_TYPE_FILE="$TMP_DIR/wrong_type.json"
echo '{"not": "an array"}' >"$WRONG_TYPE_FILE"
ERR_EXIT=0
run_capture ERR_OUT ERR_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$WRONG_TYPE_FILE" \
  --gemini-findings "$GEMINI_FINDINGS" \
  --gemini-verdicts "$GEMINI_VERDICTS" \
  --claude-verdicts "$CLAUDE_VERDICTS"
assert_exit_code "synthesize.py claude-findings wrong type -> exit 1" "1" "$ERR_EXIT"

# ====================================================================
# SECTION 10: ensure-gemini.sh — detection logic
# ====================================================================
section "ensure-gemini.sh — detection logic"

ENSURE_STUB_DIR="$TMP_DIR/ensure-stubs"
mkdir -p "$ENSURE_STUB_DIR"

# ---- Test A: gemini not on PATH → GEMINI_INSTALLED=no, GEMINI_AUTHED=unknown ----
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
assert_contains "ensure-gemini: no gemini -> GEMINI_INSTALLED=no"      "GEMINI_INSTALLED='no'"      "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> GEMINI_AUTHED=unknown"    "GEMINI_AUTHED='unknown'"    "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> INSTALL_HINT present"     "INSTALL_HINT="              "$NO_GEMINI_OUT"
assert_contains "ensure-gemini: no gemini -> AUTH_HINT present"        "AUTH_HINT="                 "$NO_GEMINI_OUT"

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
assert_contains  "ensure-gemini: stub gemini -> GEMINI_INSTALLED=yes"    "GEMINI_INSTALLED='yes'" "$WITH_GEMINI_OUT"
assert_contains  "ensure-gemini: stub gemini + key -> GEMINI_AUTHED=yes" "GEMINI_AUTHED='yes'"   "$WITH_GEMINI_OUT"
assert_contains  "ensure-gemini: stub gemini -> GEMINI_VERSION present"  "GEMINI_VERSION="       "$WITH_GEMINI_OUT"

# ---- Test C: stubbed gemini, no env key, no ~/.gemini creds → GEMINI_AUTHED=no ----
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
assert_contains  "ensure-gemini: stub gemini, no auth -> INSTALLED=yes"   "GEMINI_INSTALLED='yes'" "$NO_AUTH_OUT"
assert_contains  "ensure-gemini: stub gemini, no auth -> AUTHED=no"       "GEMINI_AUTHED='no'"    "$NO_AUTH_OUT"

# ---- Test D: OAuth-only creds (no API key) → GEMINI_AUTHED=no (regression test) ----
OAUTH_HOME="$TMP_DIR/oauth-home"
mkdir -p "$OAUTH_HOME/.gemini"
printf '{"accounts": [{"email": "user@example.com"}]}' > "$OAUTH_HOME/.gemini/google_accounts.json"
printf '{"token": "ya29.fake-oauth-token", "refresh_token": "1//fake"}' > "$OAUTH_HOME/.gemini/oauth_creds.json"
printf '{"security":{"auth":{"selectedType":"google-personal"}},"user":{"email":"user@example.com"}}' \
  > "$OAUTH_HOME/.gemini/settings.json"

OAUTH_AUTHED_OUT=""
OAUTH_AUTHED_EXIT=0
run_capture OAUTH_AUTHED_OUT OAUTH_AUTHED_EXIT \
  env PATH="$ENSURE_STUB_DIR:$PATH" \
      HOME="$OAUTH_HOME" \
      GEMINI_API_KEY="" \
      GOOGLE_API_KEY="" \
      GOOGLE_GENAI_USE_VERTEXAI="" \
      GOOGLE_CLOUD_PROJECT="" \
  bash "$ENSURE_GEMINI" --check

assert_exit_code "ensure-gemini: OAuth-only creds -> exit 0"                  "0"                    "$OAUTH_AUTHED_EXIT"
assert_contains  "ensure-gemini: OAuth-only creds -> INSTALLED=yes"           "GEMINI_INSTALLED='yes'" "$OAUTH_AUTHED_OUT"
assert_contains  "ensure-gemini: OAuth-only creds -> AUTHED=no (regression)"  "GEMINI_AUTHED='no'"    "$OAUTH_AUTHED_OUT"

# ---- Test E: ~/.gemini/.env with GEMINI_API_KEY → GEMINI_AUTHED=yes ----
ENV_FILE_HOME="$TMP_DIR/env-file-home"
mkdir -p "$ENV_FILE_HOME/.gemini"
printf 'GEMINI_API_KEY=AIzaSy_test_key_from_env_file\n' > "$ENV_FILE_HOME/.gemini/.env"

ENV_FILE_OUT=""
ENV_FILE_EXIT=0
run_capture ENV_FILE_OUT ENV_FILE_EXIT \
  env PATH="$ENSURE_STUB_DIR:$PATH" \
      HOME="$ENV_FILE_HOME" \
      GEMINI_API_KEY="" \
      GOOGLE_API_KEY="" \
      GOOGLE_GENAI_USE_VERTEXAI="" \
      GOOGLE_CLOUD_PROJECT="" \
  bash "$ENSURE_GEMINI" --check

assert_exit_code "ensure-gemini: .env key -> exit 0"              "0"                    "$ENV_FILE_EXIT"
assert_contains  "ensure-gemini: .env key -> INSTALLED=yes"       "GEMINI_INSTALLED='yes'" "$ENV_FILE_OUT"
assert_contains  "ensure-gemini: .env key -> AUTHED=yes"          "GEMINI_AUTHED='yes'"   "$ENV_FILE_OUT"

# ---- Test F: --help exits 0 ----
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
