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
  - gemini-review.sh: JSON extraction from wrapped/prose/v0.44.x/fenced-.response envelope
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
  - synthesize.py: slug-keyed claude verdict still rejects (G-### recovery)
  - synthesize.py: reason-location recovery for unmatched verdict id
  - synthesize.py: truly-unmatched verdict id warns on stderr
  - synthesize.py: ambiguous slug does NOT mis-match (both stay unconfirmed)
  - synthesize.py: exact-id verdict wins over contending slug fallback
  - synthesize.py: id-less finding is skipped, not fatal (no KeyError)
  - synthesize.py: duplicate canonical verdict id warns accurately
  - synthesize.py: empty findings lists exit cleanly
  - synthesize.py: multi-location reason abstains (no mis-match)
  - synthesize.py: exact-id confirm not clobbered by reason-location refute
  - synthesize.py: conflicting slug vs reason-location signals abstain (no mis-match)

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
# SECTION 3: JSON extraction logic — wrapped envelope, prose-only, v0.44.x envelope, and fenced-.response envelope
# ====================================================================
section "JSON extraction — wrapped envelope, prose-only, v0.44.x envelope, and fenced-.response envelope"

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

# Test 7: fenced JSON inside .response envelope (end-to-end input-shape guard)
#   Outer JSON with "response" string containing a ```json fenced block.
#   Fixture: fixtures/gemini_envelope_fenced_response.txt
#   Exercises the envelope-unwrap path; the fence-strip sub-path is shadowed
#   by the prose-fallback (iter_json_objects finds the braces regardless of
#   surrounding backticks), so fence-strip isolation is NOT separately proven here.
FENCED_OUT=""
FENCED_EXIT=0
run_capture FENCED_OUT FENCED_EXIT python3 "$EXTRACT_PY_SCRIPT" "$FIXTURES_DIR/gemini_envelope_fenced_response.txt" "judge"

assert_exit_code "fenced-.response envelope: end-to-end extraction succeeds (exit 0)" "0" "$FENCED_EXIT"
if [[ "$FENCED_EXIT" -eq 0 ]]; then
  assert_contains "fenced-.response envelope: verdicts=1" "VERDICTS=1" "$FENCED_OUT"
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
# SECTION 11: synthesize.py — slug/location fallback matching (bug #30 regression)
# ====================================================================
section "synthesize.py — slug/location fallback matching (bug #30 regression)"

# G-002 facts (from r1_gemini_findings.json):
#   title: "Unhandled None return from parse_record()"
#   path:  src/processor.py
#   line:  22
#   slug:  unhandled-none-return-from-parse-record
#            (lowercase; non-alphanumeric runs -> single hyphen; trim hyphens)

SLUG_VERDICTS_FILE="$TMP_DIR/slug_claude_verdicts.json"
SLUG_OUT_JSON="$TMP_DIR/slug_synthesis.json"

# ---- Test A: slug-keyed claude verdict still rejects G-002 ----
# Build a claude-verdicts JSON identical to the canonical one EXCEPT the G-002
# refute entry uses the slug "unhandled-none-return-from-parse-record" as id
# instead of "G-002". The fix will add slug-based fallback matching so this
# still resolves to G-002 and marks it rejected.
cat >"$SLUG_VERDICTS_FILE" <<'JSON'
{
  "verdicts": [
    {
      "id": "G-001",
      "claude_verdict": "confirm",
      "reason": "Confirmed: 'super-secret-key-123' is present on line 78. This is a critical security issue."
    },
    {
      "id": "unhandled-none-return-from-parse-record",
      "claude_verdict": "refute",
      "reason": "parse_record() was updated in a prior commit to always return a dict (possibly empty), never None; the docstring is stale. The .get() call is safe."
    }
  ]
}
JSON

SLUG_A_OUT=""
SLUG_A_EXIT=0
run_capture SLUG_A_OUT SLUG_A_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CLAUDE_FINDINGS" \
  --gemini-findings "$GEMINI_FINDINGS" \
  --gemini-verdicts "$GEMINI_VERDICTS" \
  --claude-verdicts "$SLUG_VERDICTS_FILE" \
  --json "$SLUG_OUT_JSON"

assert_exit_code "slug-keyed verdict: synthesize exits 0" 0 "$SLUG_A_EXIT"

SLUG_A_CHECK=""
SLUG_A_CHECK_EXIT=0
run_capture SLUG_A_CHECK SLUG_A_CHECK_EXIT python3 - "$SLUG_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g002 = findings.get("G-002", {})
errors = []
if g002.get("status") != "rejected":
    errors.append(f"G-002.status='{g002.get('status')}' expected='rejected'")
if g002.get("killed_by") != "claude":
    errors.append(f"G-002.killed_by='{g002.get('killed_by')}' expected='claude'")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$SLUG_A_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: slug-keyed claude verdict still rejects (G-### recovery)"
else
  fail "synthesize.py: slug-keyed claude verdict still rejects (G-### recovery)" "$SLUG_A_CHECK"
fi

# ---- Test B: reason-location recovery for unmatched verdict id ----
# Build a claude-verdicts JSON where G-002's refute entry has a gibberish id
# AND a reason string containing G-002's exact "path:line" token.
# The fix will parse "src/processor.py:22" from the reason and match it to G-002.
LOCATION_VERDICTS_FILE="$TMP_DIR/location_claude_verdicts.json"
LOCATION_OUT_JSON="$TMP_DIR/location_synthesis.json"

cat >"$LOCATION_VERDICTS_FILE" <<'JSON'
{
  "verdicts": [
    {
      "id": "G-001",
      "claude_verdict": "confirm",
      "reason": "Confirmed: 'super-secret-key-123' is present on line 78. This is a critical security issue."
    },
    {
      "id": "totally-wrong-xyz",
      "claude_verdict": "refute",
      "reason": "At src/processor.py:22 the .get() call is safe because parse_record() never returns None since a prior commit."
    }
  ]
}
JSON

SLUG_B_OUT=""
SLUG_B_EXIT=0
run_capture SLUG_B_OUT SLUG_B_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CLAUDE_FINDINGS" \
  --gemini-findings "$GEMINI_FINDINGS" \
  --gemini-verdicts "$GEMINI_VERDICTS" \
  --claude-verdicts "$LOCATION_VERDICTS_FILE" \
  --json "$LOCATION_OUT_JSON"

assert_exit_code "reason-location recovery: synthesize exits 0" 0 "$SLUG_B_EXIT"

SLUG_B_CHECK=""
SLUG_B_CHECK_EXIT=0
run_capture SLUG_B_CHECK SLUG_B_CHECK_EXIT python3 - "$LOCATION_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g002 = findings.get("G-002", {})
errors = []
if g002.get("status") != "rejected":
    errors.append(f"G-002.status='{g002.get('status')}' expected='rejected'")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$SLUG_B_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: reason-location recovery for unmatched verdict id"
else
  fail "synthesize.py: reason-location recovery for unmatched verdict id" "$SLUG_B_CHECK"
fi

# ---- Test C: truly-unmatched verdict id warns on stderr ----
# Build a claude-verdicts JSON where one verdict has a gibberish id AND a reason
# with NO file:line token matching any finding. The fix will emit a WARNING to
# stderr for the unmatched id. Current code emits nothing -> captured output
# will NOT contain "WARNING" -> assertion fails (correct fail-first behavior).
UNMATCHED_VERDICTS_FILE="$TMP_DIR/unmatched_claude_verdicts.json"
UNMATCHED_OUT_JSON="$TMP_DIR/unmatched_synthesis.json"

cat >"$UNMATCHED_VERDICTS_FILE" <<'JSON'
{
  "verdicts": [
    {
      "id": "G-001",
      "claude_verdict": "confirm",
      "reason": "Confirmed: 'super-secret-key-123' is present on line 78. This is a critical security issue."
    },
    {
      "id": "no-such-finding-zzz",
      "claude_verdict": "refute",
      "reason": "This finding does not exist and has no file:line location anchor in this reason text."
    }
  ]
}
JSON

SLUG_C_OUT=""
SLUG_C_EXIT=0
run_capture SLUG_C_OUT SLUG_C_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CLAUDE_FINDINGS" \
  --gemini-findings "$GEMINI_FINDINGS" \
  --gemini-verdicts "$GEMINI_VERDICTS" \
  --claude-verdicts "$UNMATCHED_VERDICTS_FILE" \
  --json "$UNMATCHED_OUT_JSON"

assert_exit_code "truly-unmatched verdict: synthesize exits 0" 0 "$SLUG_C_EXIT"

# The fix will emit: [synthesize] WARNING: verdict id 'no-such-finding-zzz' ...
# on stderr (captured via run_capture's 2>&1 merge).
assert_contains "synthesize.py: truly-unmatched verdict id warns on stderr (id present)" \
  "no-such-finding-zzz" "$SLUG_C_OUT"
assert_contains "synthesize.py: truly-unmatched verdict id warns on stderr (WARNING present)" \
  "WARNING" "$SLUG_C_OUT"

# ---- Test D: ambiguous slug does NOT mis-match (both stay unconfirmed) ----
# Two gemini findings share the slug "duplicate-title". A claude-verdict keyed
# by that slug (and no file:line anchor) must NOT be assigned to either finding.
# Both G-101 and G-102 must stay "unconfirmed" and stderr must mention recovery failure.
DTEST_GEMINI_FINDINGS="$TMP_DIR/d_gemini_findings.json"
DTEST_CLAUDE_VERDICTS="$TMP_DIR/d_claude_verdicts.json"
DTEST_CLAUDE_FINDINGS="$TMP_DIR/d_claude_findings.json"
DTEST_GEMINI_VERDICTS="$TMP_DIR/d_gemini_verdicts.json"
DTEST_OUT_JSON="$TMP_DIR/d_synthesis.json"

cat >"$DTEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-101","title":"Duplicate Title","path":"a.py","line":1,"severity":"minor","category":"bug","rationale":"first"},
    {"id":"G-102","title":"Duplicate Title","path":"b.py","line":2,"severity":"minor","category":"bug","rationale":"second"}
  ]
}
JSON

cat >"$DTEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"duplicate-title","claude_verdict":"refute","reason":"no location anchor in this reason text at all"}
  ]
}
JSON

cat >"$DTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$DTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

DTEST_OUT=""
DTEST_EXIT=0
run_capture DTEST_OUT DTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$DTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$DTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$DTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$DTEST_CLAUDE_VERDICTS" \
  --json "$DTEST_OUT_JSON"

assert_exit_code "Test D: ambiguous slug synthesize exits 0" 0 "$DTEST_EXIT"

DTEST_CHECK=""
DTEST_CHECK_EXIT=0
run_capture DTEST_CHECK DTEST_CHECK_EXIT python3 - "$DTEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
errors = []
g101 = findings.get("G-101", {})
g102 = findings.get("G-102", {})
if g101.get("status") == "rejected":
    errors.append(f"G-101.status='{g101.get('status')}' but expected NOT rejected (ambiguous slug must not mis-match)")
if g102.get("status") == "rejected":
    errors.append(f"G-102.status='{g102.get('status')}' but expected NOT rejected (ambiguous slug must not mis-match)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$DTEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: ambiguous slug does NOT mis-match (both stay unconfirmed)"
else
  fail "synthesize.py: ambiguous slug does NOT mis-match (both stay unconfirmed)" "$DTEST_CHECK"
fi

assert_contains "Test D: ambiguous slug stderr mentions could not be recovered" \
  "could not be recovered" "$DTEST_OUT"

# ---- Test E: exact-id verdict wins over contending slug fallback ----
# G-201 (title "Alpha") has an exact-id confirm verdict AND a slug-keyed refute.
# The exact-id confirm must win; G-201 must be "survivor".
ETEST_GEMINI_FINDINGS="$TMP_DIR/e_gemini_findings.json"
ETEST_CLAUDE_VERDICTS="$TMP_DIR/e_claude_verdicts.json"
ETEST_CLAUDE_FINDINGS="$TMP_DIR/e_claude_findings.json"
ETEST_GEMINI_VERDICTS="$TMP_DIR/e_gemini_verdicts.json"
ETEST_OUT_JSON="$TMP_DIR/e_synthesis.json"

cat >"$ETEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-201","title":"Alpha","path":"a.py","line":1,"severity":"minor","category":"bug","rationale":"alpha finding"}
  ]
}
JSON

cat >"$ETEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"G-201","claude_verdict":"confirm","reason":"ok"},
    {"id":"alpha","claude_verdict":"refute","reason":"no loc here"}
  ]
}
JSON

cat >"$ETEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$ETEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

ETEST_OUT=""
ETEST_EXIT=0
run_capture ETEST_OUT ETEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$ETEST_CLAUDE_FINDINGS" \
  --gemini-findings "$ETEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$ETEST_GEMINI_VERDICTS" \
  --claude-verdicts "$ETEST_CLAUDE_VERDICTS" \
  --json "$ETEST_OUT_JSON"

assert_exit_code "Test E: exact-id wins synthesize exits 0" 0 "$ETEST_EXIT"

ETEST_CHECK=""
ETEST_CHECK_EXIT=0
run_capture ETEST_CHECK ETEST_CHECK_EXIT python3 - "$ETEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g201 = findings.get("G-201", {})
errors = []
if g201.get("status") != "survivor":
    errors.append(f"G-201.status='{g201.get('status')}' expected='survivor' (exact-id confirm must win over slug refute)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$ETEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: exact-id verdict wins over contending slug fallback"
else
  fail "synthesize.py: exact-id verdict wins over contending slug fallback" "$ETEST_CHECK"
fi

assert_contains "Test E: slug refute could not be recovered (exact-id claimed the slot)" \
  "could not be recovered" "$ETEST_OUT"

# ---- Test F: id-less finding is skipped, not fatal (no KeyError) ----
# A findings list with one entry missing "id" must not cause a KeyError;
# exit code must be 0 and the valid finding G-301 must appear as survivor.
FTEST_GEMINI_FINDINGS="$TMP_DIR/f_gemini_findings.json"
FTEST_CLAUDE_VERDICTS="$TMP_DIR/f_claude_verdicts.json"
FTEST_CLAUDE_FINDINGS="$TMP_DIR/f_claude_findings.json"
FTEST_GEMINI_VERDICTS="$TMP_DIR/f_gemini_verdicts.json"
FTEST_OUT_JSON="$TMP_DIR/f_synthesis.json"

cat >"$FTEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-301","title":"Real","path":"r.py","line":1,"severity":"minor","category":"bug","rationale":"real finding"},
    {"title":"No Id","path":"n.py","line":2,"severity":"minor","category":"bug","rationale":"id-less finding"}
  ]
}
JSON

cat >"$FTEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"G-301","claude_verdict":"confirm","reason":"ok"}
  ]
}
JSON

cat >"$FTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$FTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

FTEST_OUT=""
FTEST_EXIT=0
run_capture FTEST_OUT FTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$FTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$FTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$FTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$FTEST_CLAUDE_VERDICTS" \
  --json "$FTEST_OUT_JSON"

assert_exit_code "synthesize.py: id-less finding is skipped, not fatal (no KeyError)" 0 "$FTEST_EXIT"

FTEST_CHECK=""
FTEST_CHECK_EXIT=0
run_capture FTEST_CHECK FTEST_CHECK_EXIT python3 - "$FTEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"] if f.get("id")}
g301 = findings.get("G-301", {})
errors = []
if g301.get("status") != "survivor":
    errors.append(f"G-301.status='{g301.get('status')}' expected='survivor'")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$FTEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: id-less finding skipped cleanly, G-301 is survivor"
else
  fail "synthesize.py: id-less finding skipped cleanly, G-301 is survivor" "$FTEST_CHECK"
fi

# ---- Test G: duplicate canonical verdict id warns accurately ----
# G-401 receives two verdicts with the exact same id "G-401". The first (confirm)
# must win, G-401 must be "survivor", and stderr must mention "duplicate verdict for finding id 'G-401'".
GTEST_GEMINI_FINDINGS="$TMP_DIR/g_gemini_findings.json"
GTEST_CLAUDE_VERDICTS="$TMP_DIR/g_claude_verdicts.json"
GTEST_CLAUDE_FINDINGS="$TMP_DIR/g_claude_findings.json"
GTEST_GEMINI_VERDICTS="$TMP_DIR/g_gemini_verdicts.json"
GTEST_OUT_JSON="$TMP_DIR/g_synthesis.json"

cat >"$GTEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-401","title":"X","path":"x.py","line":1,"severity":"minor","category":"bug","rationale":"x finding"}
  ]
}
JSON

cat >"$GTEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"G-401","claude_verdict":"confirm","reason":"a"},
    {"id":"G-401","claude_verdict":"refute","reason":"b"}
  ]
}
JSON

cat >"$GTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$GTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

GTEST_OUT=""
GTEST_EXIT=0
run_capture GTEST_OUT GTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$GTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$GTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$GTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$GTEST_CLAUDE_VERDICTS" \
  --json "$GTEST_OUT_JSON"

assert_exit_code "Test G: duplicate verdict id synthesize exits 0" 0 "$GTEST_EXIT"

assert_contains "synthesize.py: duplicate canonical verdict id warns accurately" \
  "duplicate verdict for finding id 'G-401'" "$GTEST_OUT"

GTEST_CHECK=""
GTEST_CHECK_EXIT=0
run_capture GTEST_CHECK GTEST_CHECK_EXIT python3 - "$GTEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g401 = findings.get("G-401", {})
errors = []
if g401.get("status") != "survivor":
    errors.append(f"G-401.status='{g401.get('status')}' expected='survivor' (first/confirm must win)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$GTEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: duplicate canonical verdict id warns accurately (first/confirm wins, G-401 is survivor)"
else
  fail "synthesize.py: duplicate canonical verdict id warns accurately (first/confirm wins, G-401 is survivor)" "$GTEST_CHECK"
fi

# ---- Test H: empty findings lists exit cleanly ----
HTEST_CLAUDE_FINDINGS="$TMP_DIR/h_claude_findings.json"
HTEST_GEMINI_FINDINGS="$TMP_DIR/h_gemini_findings.json"
HTEST_GEMINI_VERDICTS="$TMP_DIR/h_gemini_verdicts.json"
HTEST_CLAUDE_VERDICTS="$TMP_DIR/h_claude_verdicts.json"

cat >"$HTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON
cat >"$HTEST_GEMINI_FINDINGS" <<'JSON'
{"findings":[]}
JSON
cat >"$HTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON
cat >"$HTEST_CLAUDE_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

HTEST_OUT=""
HTEST_EXIT=0
run_capture HTEST_OUT HTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$HTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$HTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$HTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$HTEST_CLAUDE_VERDICTS"

assert_exit_code "synthesize.py: empty findings lists exit cleanly" 0 "$HTEST_EXIT"
assert_contains "synthesize.py: empty findings lists summary line correct" \
  "survivors=0 unconfirmed=0 rejected=0" "$HTEST_OUT"

# ====================================================================
# SECTION 12: synthesize.py — multi-location reason abstains (bug #30 regression)
# ====================================================================
section "synthesize.py — multi-location reason abstains (bug #30 regression)"

# Two gemini findings at distinct locations.
# A single claude-verdict with a gibberish id whose reason cites BOTH locations
# must NOT be applied to either finding — the loc_cands set has len>1, so
# reconcile_verdict_map must abstain (no recovery) and both findings stay
# "unconfirmed". If the guard were replaced by first-token-wins, G-501 would
# be incorrectly rejected.

ITEST_GEMINI_FINDINGS="$TMP_DIR/i_gemini_findings.json"
ITEST_CLAUDE_VERDICTS="$TMP_DIR/i_claude_verdicts.json"
ITEST_CLAUDE_FINDINGS="$TMP_DIR/i_claude_findings.json"
ITEST_GEMINI_VERDICTS="$TMP_DIR/i_gemini_verdicts.json"
ITEST_OUT_JSON="$TMP_DIR/i_synthesis.json"

cat >"$ITEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-501","title":"First","path":"a.py","line":10,"severity":"minor","category":"bug","rationale":"first finding"},
    {"id":"G-502","title":"Second","path":"b.py","line":20,"severity":"minor","category":"bug","rationale":"second finding"}
  ]
}
JSON

cat >"$ITEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {
      "id": "totally-unrelated-xyz",
      "claude_verdict": "refute",
      "reason": "compare a.py:10 against b.py:20 — both look suspicious"
    }
  ]
}
JSON

cat >"$ITEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$ITEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

ITEST_OUT=""
ITEST_EXIT=0
run_capture ITEST_OUT ITEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$ITEST_CLAUDE_FINDINGS" \
  --gemini-findings "$ITEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$ITEST_GEMINI_VERDICTS" \
  --claude-verdicts "$ITEST_CLAUDE_VERDICTS" \
  --json "$ITEST_OUT_JSON"

assert_exit_code "Test I: multi-location reason synthesize exits 0" 0 "$ITEST_EXIT"

ITEST_CHECK=""
ITEST_CHECK_EXIT=0
run_capture ITEST_CHECK ITEST_CHECK_EXIT python3 - "$ITEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g501 = findings.get("G-501", {})
g502 = findings.get("G-502", {})
errors = []
if g501.get("status") == "rejected":
    errors.append(f"G-501.status='rejected' but expected NOT rejected (multi-location must abstain)")
if g502.get("status") == "rejected":
    errors.append(f"G-502.status='rejected' but expected NOT rejected (multi-location must abstain)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$ITEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: multi-location reason abstains (no mis-match)"
else
  fail "synthesize.py: multi-location reason abstains (no mis-match)" "$ITEST_CHECK"
fi

assert_contains "Test I: multi-location reason stderr mentions could not be recovered" \
  "could not be recovered" "$ITEST_OUT"

# ====================================================================
# SECTION 13: synthesize.py — exact-id confirm not clobbered by reason-location refute (bug #30 regression)
# ====================================================================
section "synthesize.py — exact-id confirm not clobbered by reason-location refute (bug #30 regression)"

# ---- Test J: exact-id confirm not clobbered by reason-location refute ----
# G-601 has a confirmed exact-id verdict AND a second verdict whose gibberish id
# would otherwise recover via reason-location (its reason references "c.py:30",
# which is G-601's location). The guard `loc_index[tok] not in resolved` at
# synthesize.py:172 must prevent the location-recovered refute from clobbering
# the already-resolved exact-id confirm. G-601 must remain "survivor".
JTEST_GEMINI_FINDINGS="$TMP_DIR/j_gemini_findings.json"
JTEST_CLAUDE_VERDICTS="$TMP_DIR/j_claude_verdicts.json"
JTEST_CLAUDE_FINDINGS="$TMP_DIR/j_claude_findings.json"
JTEST_GEMINI_VERDICTS="$TMP_DIR/j_gemini_verdicts.json"
JTEST_OUT_JSON="$TMP_DIR/j_synthesis.json"

cat >"$JTEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-601","title":"Solo","path":"c.py","line":30,"severity":"minor","category":"bug","rationale":"solo finding"}
  ]
}
JSON

cat >"$JTEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"G-601","claude_verdict":"confirm","reason":"verified ok"},
    {"id":"unrelated-gibberish-id","claude_verdict":"refute","reason":"see c.py:30 for the problem"}
  ]
}
JSON

cat >"$JTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$JTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

JTEST_OUT=""
JTEST_EXIT=0
run_capture JTEST_OUT JTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$JTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$JTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$JTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$JTEST_CLAUDE_VERDICTS" \
  --json "$JTEST_OUT_JSON"

assert_exit_code "Test J: exact-id confirm not clobbered by reason-location refute exits 0" 0 "$JTEST_EXIT"

JTEST_CHECK=""
JTEST_CHECK_EXIT=0
run_capture JTEST_CHECK JTEST_CHECK_EXIT python3 - "$JTEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
g601 = findings.get("G-601", {})
errors = []
if g601.get("status") != "survivor":
    errors.append(f"G-601.status='{g601.get('status')}' expected='survivor' (exact-id confirm must not be clobbered by location-recovered refute)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$JTEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: exact-id confirm not clobbered by reason-location refute"
else
  fail "synthesize.py: exact-id confirm not clobbered by reason-location refute" "$JTEST_CHECK"
fi

assert_contains "Test J: location-recovered refute could not be recovered (exact-id claimed the slot)" \
  "could not be recovered" "$JTEST_OUT"

# ====================================================================
# SECTION 14: synthesize.py — conflicting slug vs reason-location signals abstain
# ====================================================================
section "synthesize.py — conflicting slug vs reason-location signals abstain (no mis-match)"

# ---- Test K: conflicting slug vs reason-location signals must abstain ----
# G-A (title "Alpha", path "a.py", line 1) and G-B (title "Beta", path "b.py", line 2).
# A single claude-verdict whose id slugifies to G-A's title ("alpha" -> "alpha" slug
# matches "Alpha") AND whose reason cites G-B's location ("b.py:2") must NOT be
# applied to either finding. Slug points to G-A; reason-location points to G-B —
# the signals conflict (candidates set has len>1). The code must abstain: both
# findings stay "unconfirmed" and stderr must mention "conflicting recovery signals".
KTEST_GEMINI_FINDINGS="$TMP_DIR/k_gemini_findings.json"
KTEST_CLAUDE_VERDICTS="$TMP_DIR/k_claude_verdicts.json"
KTEST_CLAUDE_FINDINGS="$TMP_DIR/k_claude_findings.json"
KTEST_GEMINI_VERDICTS="$TMP_DIR/k_gemini_verdicts.json"
KTEST_OUT_JSON="$TMP_DIR/k_synthesis.json"

cat >"$KTEST_GEMINI_FINDINGS" <<'JSON'
{
  "findings": [
    {"id":"G-A","title":"Alpha","path":"a.py","line":1,"severity":"minor","category":"bug","rationale":"alpha finding"},
    {"id":"G-B","title":"Beta","path":"b.py","line":2,"severity":"minor","category":"bug","rationale":"beta finding"}
  ]
}
JSON

cat >"$KTEST_CLAUDE_VERDICTS" <<'JSON'
{
  "verdicts": [
    {
      "id": "alpha",
      "claude_verdict": "refute",
      "reason": "the real problem is at b.py:2"
    }
  ]
}
JSON

cat >"$KTEST_CLAUDE_FINDINGS" <<'JSON'
{"findings":[]}
JSON

cat >"$KTEST_GEMINI_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

KTEST_OUT=""
KTEST_EXIT=0
run_capture KTEST_OUT KTEST_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$KTEST_CLAUDE_FINDINGS" \
  --gemini-findings "$KTEST_GEMINI_FINDINGS" \
  --gemini-verdicts "$KTEST_GEMINI_VERDICTS" \
  --claude-verdicts "$KTEST_CLAUDE_VERDICTS" \
  --json "$KTEST_OUT_JSON"

assert_exit_code "Test K: conflicting signals synthesize exits 0" 0 "$KTEST_EXIT"

KTEST_CHECK=""
KTEST_CHECK_EXIT=0
run_capture KTEST_CHECK KTEST_CHECK_EXIT python3 - "$KTEST_OUT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = {f["id"]: f for f in data["findings"]}
ga = findings.get("G-A", {})
gb = findings.get("G-B", {})
errors = []
if ga.get("status") == "rejected":
    errors.append(f"G-A.status='rejected' but expected NOT rejected (conflicting signals must abstain)")
if gb.get("status") == "rejected":
    errors.append(f"G-B.status='rejected' but expected NOT rejected (conflicting signals must abstain)")
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
PYEOF

if [[ "$KTEST_CHECK_EXIT" -eq 0 ]]; then
  pass "synthesize.py: conflicting slug vs reason-location signals abstain (no mis-match)"
else
  fail "synthesize.py: conflicting slug vs reason-location signals abstain (no mis-match)" "$KTEST_CHECK"
fi

assert_contains "Test K: conflicting signals warns on stderr" \
  "conflicting recovery signals" "$KTEST_OUT"

# ====================================================================
# SECTION 15: synthesize.py — confirm-rate guard (rubber-stamp / rubber-reject detection)
# ====================================================================
section "synthesize.py — confirm-rate guard"

# Shared: empty Gemini findings + empty Claude verdicts so the claude_on_gemini
# direction is always zero and doesn't interfere with gemini_on_claude assertions.
CR_EMPTY_GEMINI_FINDINGS="$TMP_DIR/cr_empty_gemini_findings.json"
CR_EMPTY_CLAUDE_VERDICTS="$TMP_DIR/cr_empty_claude_verdicts.json"
cat >"$CR_EMPTY_GEMINI_FINDINGS" <<'JSON'
{"findings":[]}
JSON
cat >"$CR_EMPTY_CLAUDE_VERDICTS" <<'JSON'
{"verdicts":[]}
JSON

# Fixtures in the fixtures/ dir
CR_CLAUDE_5="$FIXTURES_DIR/cr_claude_findings_5.json"
CR_CLAUDE_7="$FIXTURES_DIR/cr_claude_findings_7.json"
CR_CLAUDE_2="$FIXTURES_DIR/cr_claude_findings_2.json"
CR_GEM_ALL_CONFIRM="$FIXTURES_DIR/cr_gemini_verdicts_all_confirm.json"
CR_GEM_ALL_REFUTE="$FIXTURES_DIR/cr_gemini_verdicts_all_refute.json"
CR_GEM_MIXED="$FIXTURES_DIR/cr_gemini_verdicts_mixed_4c3r.json"

# ---- Test 1: guard fires (all-confirm rubber-stamp) ----
# 5 Claude findings, all confirmed by Gemini -> confirm_rate=1.000, judged=5 >= MIN -> low_signal=true
CR_T1_OUT=""
CR_T1_EXIT=0
run_capture CR_T1_OUT CR_T1_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_5" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_ALL_CONFIRM" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate T1: all-confirm (5) exits 0" 0 "$CR_T1_EXIT"
# Anchor assertion to the specific gemini_on_claude direction line
CR_T1_GEM_LINE="$(echo "$CR_T1_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate T1: gemini_on_claude low_signal=true (anchored)" \
  "gemini_on_claude: confirmed=5 refuted=0 judged=5 confirm_rate=1.000 low_signal=true" "$CR_T1_GEM_LINE"

# ---- Test 2: no false alarm (mixed 4 confirm / 3 refute) ----
# confirm_rate = 4/7 ≈ 0.571 — not near 1.0 or 0.0 -> low_signal=false
CR_T2_OUT=""
CR_T2_EXIT=0
run_capture CR_T2_OUT CR_T2_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_7" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_MIXED" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate T2: mixed exits 0" 0 "$CR_T2_EXIT"
CR_T2_GEM_LINE="$(echo "$CR_T2_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate T2: gemini_on_claude low_signal=false (no false alarm, anchored)" \
  "low_signal=false" "$CR_T2_GEM_LINE"

# ---- Test 3: below min sample (2 findings, both confirmed) ----
# confirm_rate=1.000 but judged=2 < RUBBER_STAMP_MIN_JUDGED=5 -> low_signal=false
CR_GEM_2_CONFIRM_FILE="$FIXTURES_DIR/cr_gemini_verdicts_2_confirm.json"

CR_T3_OUT=""
CR_T3_EXIT=0
run_capture CR_T3_OUT CR_T3_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_2" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_2_CONFIRM_FILE" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate T3: below-min-sample exits 0" 0 "$CR_T3_EXIT"
CR_T3_GEM_LINE="$(echo "$CR_T3_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate T3: gemini_on_claude low_signal=false (below min sample, anchored)" \
  "low_signal=false" "$CR_T3_GEM_LINE"

# ---- Test 4: all-refute extreme (rubber-reject) ----
# 5 Claude findings, all refuted by Gemini -> confirm_rate=0.000, judged=5 >= MIN -> low_signal=true
CR_T4_OUT=""
CR_T4_EXIT=0
run_capture CR_T4_OUT CR_T4_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_5" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_ALL_REFUTE" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate T4: all-refute (5) exits 0" 0 "$CR_T4_EXIT"
CR_T4_GEM_LINE="$(echo "$CR_T4_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate T4: gemini_on_claude low_signal=true fires (rubber-reject, anchored)" \
  "gemini_on_claude: confirmed=0 refuted=5 judged=5 confirm_rate=0.000 low_signal=true" "$CR_T4_GEM_LINE"

# ---- Test 5: ratio correctness — exact confirmed=, refuted=, confirm_rate= values (3 decimals) ----
# 7 Claude findings, 4 confirm / 3 refute -> confirmed=4 refuted=3 judged=7 confirm_rate=0.571
CR_T5_OUT=""
CR_T5_EXIT=0
run_capture CR_T5_OUT CR_T5_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_7" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_MIXED" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate T5: ratio correctness exits 0" 0 "$CR_T5_EXIT"
CR_T5_GEM_LINE="$(echo "$CR_T5_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate T5: confirmed=4 refuted=3" \
  "confirmed=4 refuted=3" "$CR_T5_GEM_LINE"
assert_contains  "confirm-rate T5: confirm_rate=0.571 (3 decimals)" \
  "confirm_rate=0.571" "$CR_T5_GEM_LINE"

# ---- Boundary-edge tests (Fix C) ----

CR_CLAUDE_20="$FIXTURES_DIR/cr_claude_findings_20.json"
CR_CLAUDE_4="$FIXTURES_DIR/cr_claude_findings_4.json"
CR_GEM_19C1R="$FIXTURES_DIR/cr_gemini_verdicts_19c1r.json"
CR_GEM_18C2R="$FIXTURES_DIR/cr_gemini_verdicts_18c2r.json"
CR_GEM_1C19R="$FIXTURES_DIR/cr_gemini_verdicts_1c19r.json"
CR_GEM_4C0R="$FIXTURES_DIR/cr_gemini_verdicts_4c0r.json"

# ---- Boundary T6: 0.95 high edge — 19 confirm / 1 refute (rate=0.950) -> low_signal=true ----
# Proves the >= boundary is inclusive (if > were used, 0.950 would not fire)
CR_B6_OUT=""
CR_B6_EXIT=0
run_capture CR_B6_OUT CR_B6_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_20" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_19C1R" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate boundary T6: 0.950 high edge exits 0" 0 "$CR_B6_EXIT"
CR_B6_GEM_LINE="$(echo "$CR_B6_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate boundary T6: rate=0.950 -> low_signal=true (proves >= inclusive)" \
  "confirmed=19 refuted=1 judged=20 confirm_rate=0.950 low_signal=true" "$CR_B6_GEM_LINE"

# ---- Boundary T7: 0.90 near-miss — 18 confirm / 2 refute (rate=0.900) -> low_signal=false ----
# Proves the guard does NOT fire below the 0.95 threshold
CR_B7_OUT=""
CR_B7_EXIT=0
run_capture CR_B7_OUT CR_B7_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_20" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_18C2R" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate boundary T7: 0.900 near-miss exits 0" 0 "$CR_B7_EXIT"
CR_B7_GEM_LINE="$(echo "$CR_B7_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate boundary T7: rate=0.900 -> low_signal=false (does not fire below 0.95)" \
  "confirmed=18 refuted=2 judged=20 confirm_rate=0.900 low_signal=false" "$CR_B7_GEM_LINE"

# ---- Boundary T8: 0.05 low edge — 1 confirm / 19 refute (rate=0.050) -> low_signal=true ----
# Proves the low-end <= boundary is inclusive
CR_B8_OUT=""
CR_B8_EXIT=0
run_capture CR_B8_OUT CR_B8_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_20" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_1C19R" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate boundary T8: 0.050 low edge exits 0" 0 "$CR_B8_EXIT"
CR_B8_GEM_LINE="$(echo "$CR_B8_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate boundary T8: rate=0.050 -> low_signal=true (proves <= inclusive)" \
  "confirmed=1 refuted=19 judged=20 confirm_rate=0.050 low_signal=true" "$CR_B8_GEM_LINE"

# ---- Boundary T9: 4-judged all-confirm — 4 confirm / 0 refute (rate=1.000, judged=4 < 5) -> low_signal=false ----
# Proves the MIN_JUDGED=5 boundary is exclusive at 4 (guard must NOT fire at 4)
CR_B9_OUT=""
CR_B9_EXIT=0
run_capture CR_B9_OUT CR_B9_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_CLAUDE_4" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_GEM_4C0R" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate boundary T9: 4-judged all-confirm exits 0" 0 "$CR_B9_EXIT"
CR_B9_GEM_LINE="$(echo "$CR_B9_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate boundary T9: judged=4 -> low_signal=false (proves MIN_JUDGED=5 exclusive at 4)" \
  "confirmed=4 refuted=0 judged=4 confirm_rate=1.000 low_signal=false" "$CR_B9_GEM_LINE"

# ---- Fix D: unrecognized verdict detection ----
# 5 confirm + 3 "reject" verdicts (unrecognized) -> unrecognized=3, judged=5, low_signal=true
# Use a fresh 8-finding fixture and inline verdicts
CR_D_CLAUDE_FINDINGS="$TMP_DIR/cr_d_claude_findings.json"
cat >"$CR_D_CLAUDE_FINDINGS" <<'JSON'
[
  {"id":"C-D1","path":"src/a.py","line":1,"severity":"minor","category":"bug","title":"F1","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D2","path":"src/a.py","line":2,"severity":"minor","category":"bug","title":"F2","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D3","path":"src/a.py","line":3,"severity":"minor","category":"bug","title":"F3","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D4","path":"src/a.py","line":4,"severity":"minor","category":"bug","title":"F4","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D5","path":"src/a.py","line":5,"severity":"minor","category":"bug","title":"F5","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D6","path":"src/a.py","line":6,"severity":"minor","category":"bug","title":"F6","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D7","path":"src/a.py","line":7,"severity":"minor","category":"bug","title":"F7","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null},
  {"id":"C-D8","path":"src/a.py","line":8,"severity":"minor","category":"bug","title":"F8","rationale":"R","origin":"claude","claude_verdict":null,"gemini_verdict":null,"status":null,"killed_by":null,"kill_reason":null}
]
JSON

CR_D_VERDICTS="$TMP_DIR/cr_d_verdicts.json"
cat >"$CR_D_VERDICTS" <<'JSON'
{
  "verdicts": [
    {"id":"C-D1","gemini_verdict":"confirm","reason":"ok","confidence":0.9},
    {"id":"C-D2","gemini_verdict":"confirm","reason":"ok","confidence":0.9},
    {"id":"C-D3","gemini_verdict":"confirm","reason":"ok","confidence":0.9},
    {"id":"C-D4","gemini_verdict":"confirm","reason":"ok","confidence":0.9},
    {"id":"C-D5","gemini_verdict":"confirm","reason":"ok","confidence":0.9},
    {"id":"C-D6","gemini_verdict":"reject","reason":"typo verdict","confidence":0.9},
    {"id":"C-D7","gemini_verdict":"reject","reason":"typo verdict","confidence":0.9},
    {"id":"C-D8","gemini_verdict":"reject","reason":"typo verdict","confidence":0.9}
  ]
}
JSON

CR_D_OUT=""
CR_D_EXIT=0
run_capture CR_D_OUT CR_D_EXIT python3 "$SYNTHESIZE" \
  --claude-findings "$CR_D_CLAUDE_FINDINGS" \
  --gemini-findings "$CR_EMPTY_GEMINI_FINDINGS" \
  --gemini-verdicts "$CR_D_VERDICTS" \
  --claude-verdicts "$CR_EMPTY_CLAUDE_VERDICTS"

assert_exit_code "confirm-rate Fix-D: unrecognized verdicts exits 0" 0 "$CR_D_EXIT"
CR_D_GEM_LINE="$(echo "$CR_D_OUT" | grep '^gemini_on_claude:')"
assert_contains  "confirm-rate Fix-D: confirmed=5 judged=5 low_signal=true" \
  "confirmed=5 refuted=0 judged=5 confirm_rate=1.000 low_signal=true" "$CR_D_GEM_LINE"
assert_contains  "confirm-rate Fix-D: unrecognized=3 in output line" \
  "unrecognized=3" "$CR_D_GEM_LINE"
assert_contains  "confirm-rate Fix-D: unrecognized warn on stderr" \
  "unrecognized verdict value" "$CR_D_OUT"

# ---- Fix E: low_signal _warn on stderr ----
# T1 (all-confirm) should already emit the warn; verify it appears in T1 output
assert_contains  "confirm-rate Fix-E: low_signal warn in T1 stderr" \
  "confirm-rate guard FIRED" "$CR_T1_OUT"

# ---- Presence P1: gemini-review.sh contains strict judge prompt phrase ----
# (gemini-review.sh must contain the hardened default-to-refute instruction)
GEMINI_REVIEW_CONTENT="$(cat "$GEMINI_REVIEW")"
assert_contains "presence P1: gemini-review.sh has default-to-refute phrase" \
  "Default to refute unless the finding is incontrovertibly grounded" \
  "$GEMINI_REVIEW_CONTENT"

# ---- Presence P2: gemini-review.sh contains forced-refute escalation phrase ----
assert_contains "presence P2: gemini-review.sh has quote-offending-line phrase" \
  "Quote the exact offending line from the diff verbatim" \
  "$GEMINI_REVIEW_CONTENT"

# ---- Presence P3: gemini-review.sh has --strict flag ----
# Note: avoid passing --strict as the grep pattern directly (ugrep interprets it
# as a flag). Test for the FORCE_STRICT variable name instead, which is set only
# when --strict is parsed, and for the usage line suffix that contains the flag.
assert_contains "presence P3: gemini-review.sh has FORCE_STRICT (--strict implementation)" \
  "FORCE_STRICT" \
  "$GEMINI_REVIEW_CONTENT"

# ---- Presence P4: adversarial-cross-examiner.md contains cannot-point phrase ----
# Path: scripts/ -> (skill)adversarial-review/ -> skills/ -> (plugin)adversarial-review/ -> agents/
CROSS_EXAMINER_FILE="$SCRIPT_DIR/../../../agents/adversarial-cross-examiner.md"
CROSS_EXAMINER_CONTENT="$(cat "$CROSS_EXAMINER_FILE")"
assert_contains "presence P4: cross-examiner.md has cannot-point-to-proving-line phrase" \
  "cannot point to the proving line" \
  "$CROSS_EXAMINER_CONTENT"

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
