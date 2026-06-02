#!/usr/bin/env bash
# gemini-review.sh — Gemini R2 adversarial review (refute+augment Claude findings)
# Usage: gemini-review.sh --diff <file> --findings <r1.json> [--model <m>] [--out <r2.json>] [--help]
# Exit codes: 0=ok, 1=error, 2=usage, 3=adversary-unavailable

set -eu

SCRIPT_NAME="$(basename "$0")"
DIFF_FILE=""
FINDINGS_FILE=""
MODEL="${GEMINI_MODEL:-gemini-2.5-pro}"
OUT_FILE=""

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --diff <file> --findings <r1.json> [--model <m>] [--out <r2.json>] [--help]

Send Claude's R1 findings + the shared diff to Gemini for adversarial
review (Round 2). Gemini verdicts each Claude finding and adds new ones.

Options:
  --diff <file>       Path to the shared diff artifact (required)
  --findings <file>   Path to R1 Claude findings JSON list (required)
  --model <model>     Gemini model to use (default: gemini-2.5-pro,
                      or \$GEMINI_MODEL env var)
  --out <file>        Write output JSON to this file (default: stdout)
  --help              Show this help and exit

Output JSON schema:
  {
    "verdicts": [
      {"id": "...", "gemini_verdict": "confirm|refute", "reason": "...", "confidence": 0.0-1.0}
    ],
    "new_findings": [
      { <full finding schema with origin=gemini> }
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
    --model)
      [[ $# -lt 2 ]] && { echo "Error: --model requires an argument" >&2; exit 2; }
      MODEL="$2"; shift 2 ;;
    --out)
      [[ $# -lt 2 ]] && { echo "Error: --out requires an argument" >&2; exit 2; }
      OUT_FILE="$2"; shift 2 ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ---- input validation ----
if [[ -z "$DIFF_FILE" ]]; then
  echo "Error: --diff is required" >&2
  usage >&2
  exit 2
fi
if [[ -z "$FINDINGS_FILE" ]]; then
  echo "Error: --findings is required" >&2
  usage >&2
  exit 2
fi
[[ -f "$DIFF_FILE" ]] || { echo "Error: diff file not found: $DIFF_FILE" >&2; exit 1; }
[[ -f "$FINDINGS_FILE" ]] || { echo "Error: findings file not found: $FINDINGS_FILE" >&2; exit 1; }

# ---- check gemini is available ----
if ! command -v gemini >/dev/null 2>&1; then
  echo "ADVERSARY_UNAVAILABLE: gemini CLI not found in PATH" >&2
  exit 3
fi

# ---- helper: extract JSON object from potentially wrapped output ----
# Tries to find a {...} JSON object (possibly multi-line) in the input
extract_json_object() {
  python3 - "$1" <<'PYEOF'
import sys, re, json

text = open(sys.argv[1]).read()

# Try direct parse first
try:
    obj = json.loads(text.strip())
    if isinstance(obj, dict):
        print(json.dumps(obj))
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
                    print(json.dumps(obj))
                    sys.exit(0)
            except Exception:
                # Reset and keep searching
                start = None
                depth = 0

sys.exit(1)
PYEOF
}

# ---- build prompt ----
build_prompt() {
  local strict="$1"
  local findings_content
  findings_content="$(cat "$FINDINGS_FILE")"

  if [[ "$strict" == "true" ]]; then
    cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff followed by a list of code review findings made by Claude (Round 1).

Your task is to:
1. For each Claude finding (identified by "id"), output your verdict: "confirm" if valid, "refute" if invalid/wrong.
2. Add any NEW findings you identify that Claude missed (use origin="gemini").

Output ONLY valid JSON, no prose, no markdown, no explanation. The JSON must have exactly this structure:
{
  "verdicts": [
    {"id": "<finding-id>", "gemini_verdict": "confirm|refute", "reason": "<brief reason>", "confidence": 0.0}
  ],
  "new_findings": [
    {
      "id": "<unique-id>",
      "path": "<file path>",
      "line": <line number or null>,
      "severity": "critical|important|minor",
      "category": "bug|security|convention|perf|maintainability",
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

Claude's findings:
${findings_content}
PROMPT
  else
    cat <<PROMPT
You are an adversarial code reviewer. Below is a git diff followed by a list of code review findings made by Claude (Round 1).

Your task is to:
1. For each Claude finding (identified by "id"), output your verdict: "confirm" if valid, "refute" if invalid/wrong.
2. Add any NEW findings you identify that Claude missed (use origin="gemini").

Respond with a JSON object with two keys: "verdicts" (array of verdict objects with id, gemini_verdict, reason, confidence) and "new_findings" (array of new finding objects following the full finding schema with origin="gemini" and null for verdict/status/killed_by/kill_reason fields).

Claude's findings:
${findings_content}
PROMPT
  fi
}

# ---- call gemini with retry ----
COMBINED_INPUT_FILE="$(mktemp /tmp/adversarial-gemini-input.XXXXXX)"
RAW_OUTPUT_FILE="$(mktemp /tmp/adversarial-gemini-raw.XXXXXX)"
EXTRACTED_JSON_FILE="$(mktemp /tmp/adversarial-gemini-json.XXXXXX)"

trap 'rm -f "$COMBINED_INPUT_FILE" "$RAW_OUTPUT_FILE" "$EXTRACTED_JSON_FILE"' EXIT

# Build combined input (diff + prompt context)
cat "$DIFF_FILE" >"$COMBINED_INPUT_FILE"

call_gemini() {
  local strict="$1"
  local prompt
  prompt="$(build_prompt "$strict")"

  # Call gemini: -p for prompt, -o json for output format, -m for model
  # stdin receives the diff content
  if ! gemini -p "$prompt" -o json -m "$MODEL" <"$COMBINED_INPUT_FILE" >"$RAW_OUTPUT_FILE" 2>/tmp/adversarial-gemini-stderr.txt; then
    local stderr_content
    stderr_content="$(cat /tmp/adversarial-gemini-stderr.txt 2>/dev/null || true)"
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
  if extract_json_object "$RAW_OUTPUT_FILE" >"$EXTRACTED_JSON_FILE" 2>/dev/null; then
    return 0
  fi
  return 1
}

# First attempt (non-strict prompt)
if ! call_gemini "false"; then
  # Retry with strict prompt
  echo "Warning: Failed to parse Gemini output, retrying with stricter prompt..." >&2
  if ! call_gemini "true"; then
    echo "ADVERSARY_UNAVAILABLE: Could not extract valid JSON from Gemini output after retry" >&2
    exit 3
  fi
fi

# Validate the extracted JSON has required keys
if ! python3 -c "
import json, sys
data = json.load(open('$EXTRACTED_JSON_FILE'))
assert 'verdicts' in data, 'missing verdicts key'
assert 'new_findings' in data, 'missing new_findings key'
assert isinstance(data['verdicts'], list), 'verdicts must be a list'
assert isinstance(data['new_findings'], list), 'new_findings must be a list'
" 2>/tmp/adversarial-validate-err.txt; then
  err="$(cat /tmp/adversarial-validate-err.txt 2>/dev/null || echo 'unknown')"
  echo "ADVERSARY_UNAVAILABLE: Gemini output missing required fields: $err" >&2
  exit 3
fi

# ---- emit output ----
if [[ -n "$OUT_FILE" ]]; then
  cp "$EXTRACTED_JSON_FILE" "$OUT_FILE"
else
  cat "$EXTRACTED_JSON_FILE"
fi
