#!/usr/bin/env bash
# gemini-review.sh — Gemini adversarial review (find mode or judge mode)
# Usage: gemini-review.sh --diff <file> [--findings <r1.json>] [--mode find|judge]
#                         [--model <m>] [--out <file>] [--help]
# Exit codes: 0=ok, 1=error, 2=usage, 3=adversary-unavailable

set -eu

SCRIPT_NAME="$(basename "$0")"
DIFF_FILE=""
FINDINGS_FILE=""
MODE="judge"
MODEL="${GEMINI_MODEL:-gemini-2.5-pro}"
OUT_FILE=""
FORCE_STRICT=false

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --diff <file> [--findings <r1.json>] [--mode find|judge]
                    [--model <m>] [--out <file>] [--strict] [--help]

Run Gemini in one of two modes:

  find (independent review):
    Gemini independently reviews the diff and reports its own findings.
    Requires --diff only; --findings is ignored if provided.
    Output: {"findings":[...]}

  judge (default — verdict on peer findings):
    Gemini verdicts each provided finding as confirm or refute.
    Requires --diff AND --findings.
    Output: {"verdicts":[...]}

Options:
  --diff <file>       Path to the shared diff artifact (required)
  --findings <file>   Path to peer findings JSON list (required for judge mode)
  --mode <mode>       find or judge (default: judge)
  --model <model>     Gemini model to use (default: gemini-2.5-pro,
                      or \$GEMINI_MODEL env var)
  --out <file>        Write output JSON to this file (default: stdout)
  --strict            Force the hardened/strict prompt variant on the first call
                      instead of the standard prompt, regardless of --mode.
                      Use for low-signal escalation re-runs.
  --help              Show this help and exit

Output JSON schema:
  find mode:
    {
      "findings": [
        {
          "id": "<unique-id>",
          "path": "<file>",
          "line": <n|null>,
          "severity": "critical|important|minor",
          "category": "bug|security|perf|convention|maintainability",
          "title": "<short title>",
          "rationale": "<explanation>",
          "origin": "gemini",
          "claude_verdict": null,
          "gemini_verdict": null,
          "status": null,
          "killed_by": null,
          "kill_reason": null
        }
      ]
    }

  judge mode:
    {
      "verdicts": [
        {"id": "...", "gemini_verdict": "confirm|refute", "reason": "...", "confidence": 0.0}
      ]
    }

Exit codes:
  0  Success
  1  Error (file not found, etc.)
  2  Usage error
  3  Adversary unavailable (gemini not installed, auth error, parse failure)
EOF
}

# ---- argument parsing ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --diff)
      [[ $# -lt 2 ]] && { echo "Error: --diff requires an argument" >&2; exit 2; }
      DIFF_FILE="$2"; shift 2 ;;
    --findings)
      [[ $# -lt 2 ]] && { echo "Error: --findings requires an argument" >&2; exit 2; }
      FINDINGS_FILE="$2"; shift 2 ;;
    --mode)
      [[ $# -lt 2 ]] && { echo "Error: --mode requires an argument" >&2; exit 2; }
      MODE="$2"; shift 2 ;;
    --model)
      [[ $# -lt 2 ]] && { echo "Error: --model requires an argument" >&2; exit 2; }
      MODEL="$2"; shift 2 ;;
    --out)
      [[ $# -lt 2 ]] && { echo "Error: --out requires an argument" >&2; exit 2; }
      OUT_FILE="$2"; shift 2 ;;
    --strict)
      FORCE_STRICT=true; shift ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ---- validate mode ----
if [[ "$MODE" != "find" && "$MODE" != "judge" ]]; then
  echo "Error: --mode must be 'find' or 'judge', got: $MODE" >&2
  usage >&2
  exit 2
fi

# ---- input validation ----
if [[ -z "$DIFF_FILE" ]]; then
  echo "Error: --diff is required" >&2
  usage >&2
  exit 2
fi
[[ -f "$DIFF_FILE" ]] || { echo "Error: diff file not found: $DIFF_FILE" >&2; exit 1; }

if [[ "$MODE" == "judge" ]]; then
  if [[ -z "$FINDINGS_FILE" ]]; then
    echo "Error: --findings is required for judge mode" >&2
    usage >&2
    exit 2
  fi
  [[ -f "$FINDINGS_FILE" ]] || { echo "Error: findings file not found: $FINDINGS_FILE" >&2; exit 1; }
fi

# ---- check gemini is available ----
if ! command -v gemini >/dev/null 2>&1; then
  echo "ADVERSARY_UNAVAILABLE: gemini CLI not found in PATH" >&2
  exit 3
fi

# ---- helper: extract model answer JSON from gemini CLI raw output ----
#
# Handles three shapes of gemini CLI output:
#
#  Shape A (old / plain)  — stdout IS the model's JSON (possibly wrapped in prose
#                           or markdown fences):
#    {"verdicts":[...]}        (judge mode)
#    {"findings":[...]}        (find mode)
#
#  Shape B (v0.44.x envelope) — stdout has optional prose prefix lines, then an
#                              outer JSON envelope whose "response" field is a
#                              string containing the model's actual answer:
#    Ripgrep is not available. Falling back to GrepTool.
#    Skill conflict detected: ...
#    {"session_id":"...","response":"{\"verdicts\":[...]}","stats":{...}}
#
# In both shapes the model's answer may itself be:
#   - bare JSON
#   - JSON wrapped in ```json ... ``` fences
#   - JSON surrounded by prose
#
# On success: prints the extracted JSON object and exits 0.
# On failure: exits 1.
extract_model_answer() {
  python3 - "$1" "$2" <<'PYEOF'
import sys, json, re

MODE = sys.argv[2]  # "find" or "judge"

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
    """Return the first balanced {...} block that parses as a JSON dict, or None."""
    for obj in iter_json_objects(text):
        return obj
    return None

def find_first_json_with_keys(text, *keys):
    """Return the first JSON dict containing any of the given keys, or None."""
    for obj in iter_json_objects(text):
        if any(k in obj for k in keys):
            return obj
    return None

def has_payload_key(obj):
    """Check if the dict has the expected top-level key for the current mode."""
    if MODE == "find":
        return "findings" in obj
    else:
        return "verdicts" in obj

def extract_payload(text):
    """
    Extract the mode-appropriate JSON dict from raw text.
    Returns the dict or None.
    """
    # --- Step 1: look for an object with the "response" key first (v0.44.x envelope) ---
    envelope = find_first_json_with_keys(text, "response")
    if envelope is not None and isinstance(envelope.get("response"), str):
        model_text = envelope["response"]
    else:
        # --- Step 2: look for an object with the payload key directly ---
        payload_key = "findings" if MODE == "find" else "verdicts"
        direct = find_first_json_with_keys(text, payload_key)
        if direct is not None and has_payload_key(direct):
            return direct
        # No payload object found at top level; fall through to search raw text
        model_text = text

    # --- Step 3: extract payload from model_text ---
    # (a) a bare JSON object — try direct parse first
    try:
        obj = json.loads(model_text.strip())
        if isinstance(obj, dict) and has_payload_key(obj):
            return obj
    except Exception:
        pass

    # (b) JSON inside ```json ... ``` fences
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', model_text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if isinstance(obj, dict) and has_payload_key(obj):
                return obj
        except Exception:
            pass

    # (c) JSON object embedded in prose — find first balanced {...} with payload key
    payload_key = "findings" if MODE == "find" else "verdicts"
    inner = find_first_json_with_keys(model_text, payload_key)
    if inner is not None and has_payload_key(inner):
        return inner

    return None

text = open(sys.argv[1]).read()
result = extract_payload(text)

if result is None:
    sys.exit(1)

print(json.dumps(result))
sys.exit(0)
PYEOF
}

# Keep the old name as an alias so any internal callers still work
extract_json_object() {
  extract_model_answer "$1" "$MODE"
}

# ---- build prompt ----
build_prompt() {
  local strict="$1"

  if [[ "$MODE" == "find" ]]; then
    if [[ "$strict" == "true" ]]; then
      cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff.

Your task is to independently review the diff and report findings (bugs, security issues,
performance problems, conventions, or maintainability concerns) introduced by the diff,
grounded in the diff only.

Output ONLY valid JSON, no prose, no markdown, no explanation. The JSON must have
exactly this structure:
{
  "findings": [
    {
      "id": "<unique-id>",
      "path": "<file path>",
      "line": <line number or null>,
      "severity": "critical|important|minor",
      "category": "bug|security|perf|convention|maintainability",
      "title": "<short title>",
      "rationale": "<explanation of why this is a finding>",
      "origin": "gemini",
      "claude_verdict": null,
      "gemini_verdict": null,
      "status": null,
      "killed_by": null,
      "kill_reason": null
    }
  ]
}
PROMPT
    else
      cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff.

Your task is to independently review the diff and report findings (bugs, security issues,
performance problems, conventions, or maintainability concerns) introduced by the diff.

Respond with a JSON object with a "findings" key: an array of finding objects.
Each finding must have: id (unique string), path, line (number or null), severity
(critical|important|minor), category (bug|security|perf|convention|maintainability),
title, rationale, origin ("gemini"), and null values for claude_verdict, gemini_verdict,
status, killed_by, kill_reason.
PROMPT
    fi
  else
    # judge mode
    local findings_content
    findings_content="$(cat "$FINDINGS_FILE")"

    if [[ "$strict" == "true" ]]; then
      cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff followed by a list of code
review findings made by another model.

Your task is to verdict each finding (identified by "id"): output "confirm" if the
finding is valid and grounded in the diff, or "refute" if it is incorrect or not
supported by the diff.

Default to refute unless the finding is incontrovertibly grounded in the diff shown
below. The cost of a wrongly-confirmed finding (it inflates the survivors list and
erodes trust) is higher than a wrongly-refuted one (it is retained as UNCONFIRMED,
not lost).

Refute findings that rest on taste, convention preference, speculation about runtime
behavior not shown, or severity-inflation.

For every confirm, your reason MUST cite the specific diff line(s) or code that prove
the finding. A confirm without grounded evidence is not allowed — refute instead.

Quote the exact offending line from the diff verbatim in your reason for every
confirm; if you cannot quote a line that proves it, refute.

Output ONLY valid JSON, no prose, no markdown, no explanation. The JSON must have
exactly this structure:
{
  "verdicts": [
    {"id": "<finding-id>", "gemini_verdict": "confirm|refute", "reason": "<brief reason>", "confidence": 0.0}
  ]
}

Findings to verdict:
${findings_content}
PROMPT
    else
      cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff followed by a list of code
review findings made by another model.

Your task is to verdict each finding (identified by "id"): "confirm" if valid and
grounded in the diff, or "refute" if incorrect or not supported.

Default to refute unless the finding is incontrovertibly grounded in the diff shown
below. The cost of a wrongly-confirmed finding (it inflates the survivors list and
erodes trust) is higher than a wrongly-refuted one (it is retained as UNCONFIRMED,
not lost).

Refute findings that rest on taste, convention preference, speculation about runtime
behavior not shown, or severity-inflation.

For every confirm, your reason MUST cite the specific diff line(s) or code that prove
the finding. A confirm without grounded evidence is not allowed — refute instead.

Respond with a JSON object with a "verdicts" key: an array of verdict objects.
Each verdict must have: id (the finding id), gemini_verdict ("confirm" or "refute"),
reason (brief explanation), confidence (0.0–1.0).

Findings to verdict:
${findings_content}
PROMPT
    fi
  fi
}

# ---- call gemini with retry ----
COMBINED_INPUT_FILE="$(mktemp /tmp/adversarial-gemini-input.XXXXXX)"
RAW_OUTPUT_FILE="$(mktemp /tmp/adversarial-gemini-raw.XXXXXX)"
EXTRACTED_JSON_FILE="$(mktemp /tmp/adversarial-gemini-json.XXXXXX)"
GEMINI_STDERR_FILE="$(mktemp /tmp/adversarial-gemini-stderr.XXXXXX)"
VALIDATE_ERR_FILE="$(mktemp /tmp/adversarial-validate-err.XXXXXX)"

trap 'rm -f "$COMBINED_INPUT_FILE" "$RAW_OUTPUT_FILE" "$EXTRACTED_JSON_FILE" "$GEMINI_STDERR_FILE" "$VALIDATE_ERR_FILE"' EXIT

# Build combined input (diff + prompt context)
cat "$DIFF_FILE" >"$COMBINED_INPUT_FILE"

call_gemini() {
  local strict="$1"
  local prompt
  prompt="$(build_prompt "$strict")"

  # Call gemini: -p for prompt, -o json for output format, -m for model
  # stdin receives the diff content
  if ! gemini -p "$prompt" -o json -m "$MODEL" <"$COMBINED_INPUT_FILE" >"$RAW_OUTPUT_FILE" 2>"$GEMINI_STDERR_FILE"; then
    local stderr_content
    stderr_content="$(cat "$GEMINI_STDERR_FILE" 2>/dev/null || true)"
    # Check for auth-related errors
    if echo "$stderr_content" | grep -qiE 'auth|credentials|api.key|unauthorized|permission|403|401'; then
      echo "ADVERSARY_UNAVAILABLE: Gemini authentication error: $stderr_content" >&2
      exit 3
    fi
    # Other errors
    echo "ADVERSARY_UNAVAILABLE: Gemini CLI returned non-zero exit: $stderr_content" >&2
    exit 3
  fi

  # Try to extract JSON from the output
  if extract_model_answer "$RAW_OUTPUT_FILE" "$MODE" >"$EXTRACTED_JSON_FILE" 2>/dev/null; then
    return 0
  fi
  return 1
}

# First attempt: use FORCE_STRICT if --strict was passed, otherwise non-strict
if ! call_gemini "$FORCE_STRICT"; then
  # Retry with strict prompt (always true on retry)
  echo "Warning: Failed to parse Gemini output, retrying with stricter prompt..." >&2
  if ! call_gemini "true"; then
    echo "ADVERSARY_UNAVAILABLE: Could not extract valid JSON from Gemini output after retry" >&2
    exit 3
  fi
fi

# Validate the extracted JSON and drop any id-less entries
if [[ "$MODE" == "judge" ]]; then
  if ! python3 -c "
import json, sys
data = json.load(open('$EXTRACTED_JSON_FILE'))
assert 'verdicts' in data, 'missing verdicts key'
assert isinstance(data['verdicts'], list), 'verdicts must be a list'
# Drop entries without a string id so downstream never sees id-less entries
data['verdicts'] = [v for v in data['verdicts'] if isinstance(v.get('id'), str) and v['id']]
with open('$EXTRACTED_JSON_FILE', 'w') as fh:
    json.dump(data, fh)
" 2>"$VALIDATE_ERR_FILE"; then
    err="$(cat "$VALIDATE_ERR_FILE" 2>/dev/null || echo 'unknown')"
    echo "ADVERSARY_UNAVAILABLE: Gemini output missing required fields: $err" >&2
    exit 3
  fi
else
  # find mode
  if ! python3 -c "
import json, sys
data = json.load(open('$EXTRACTED_JSON_FILE'))
assert 'findings' in data, 'missing findings key'
assert isinstance(data['findings'], list), 'findings must be a list'
# Drop entries without a string id so downstream never sees id-less entries
data['findings'] = [f for f in data['findings'] if isinstance(f.get('id'), str) and f['id']]
with open('$EXTRACTED_JSON_FILE', 'w') as fh:
    json.dump(data, fh)
" 2>"$VALIDATE_ERR_FILE"; then
    err="$(cat "$VALIDATE_ERR_FILE" 2>/dev/null || echo 'unknown')"
    echo "ADVERSARY_UNAVAILABLE: Gemini output missing required fields: $err" >&2
    exit 3
  fi
fi

# ---- emit output ----
if [[ -n "$OUT_FILE" ]]; then
  cp "$EXTRACTED_JSON_FILE" "$OUT_FILE"
else
  cat "$EXTRACTED_JSON_FILE"
fi
