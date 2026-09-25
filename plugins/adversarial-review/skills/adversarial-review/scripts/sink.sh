#!/usr/bin/env bash
# sink.sh — deliver the synthesized review report, and save the model exchange
# on the PR (pr mode) or in the local report file (local mode).
# Usage: sink.sh --report-md <md> --report-json <json> --mode <pr|local>
#                [--pr <n>] [--branch <name>] [--record <round.json>] [--no-post] [--help]
# Exit codes: 0=ok, 1=error, 2=usage, 4=report delivered but the audit trail
#             is incomplete, went to the local file, or was not saved

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_MD=""
REPORT_JSON=""
MODE=""
PR_NUMBER=""
BRANCH=""
RECORD=""
NO_POST="false"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --report-md <md> --report-json <json> --mode <pr|local>
         [--pr <n>] [--branch <name>] [--record <round.json>] [--no-post] [--help]

Deliver the synthesized adversarial review report. In pr mode, also save every
model exchange on the PR through pr-audit.py: one inline thread per finding,
verdicts as replies, and one summary review.

Options:
  --report-md <file>    Path to the markdown report (required)
  --report-json <file>  Path to the structured JSON report (required)
  --mode <pr|local>     Delivery mode (required)
  --pr <number>         PR number (required in pr mode)
  --branch <name>       Branch name, used for the local output filename
  --record <file>       Round record (audit-round/v1). Required in pr mode unless --no-post.
  --no-post             Do not post to the PR; deliver as in local mode
  --help                Show this help and exit

pr mode behavior:
  Prints the report, then runs pr-audit.py post. If gh is missing, not logged
  in, or cannot read the PR, pr-audit.py writes the exchange to
  <branch>.adversarial-review.md instead (exit 4).

local mode behavior:
  Prints the report AND writes <branch>.adversarial-review.md in the repo root,
  then appends the exchange from --record if given. Ensures
  *.adversarial-review.md is gitignored.

Exit codes:
  0  Success
  1  Error
  2  Usage error
  4  Report delivered, but the audit trail is incomplete: some posts failed,
     it went to the local file, the record was rejected, or pr-audit.py
     crashed (see the pr-audit lines on stderr)
EOF
}

# ---- argument parsing ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --report-md)
      [[ $# -lt 2 ]] && { echo "Error: --report-md requires an argument" >&2; exit 2; }
      REPORT_MD="$2"; shift 2 ;;
    --report-json)
      [[ $# -lt 2 ]] && { echo "Error: --report-json requires an argument" >&2; exit 2; }
      REPORT_JSON="$2"; shift 2 ;;
    --mode)
      [[ $# -lt 2 ]] && { echo "Error: --mode requires an argument" >&2; exit 2; }
      MODE="$2"; shift 2 ;;
    --pr)
      [[ $# -lt 2 ]] && { echo "Error: --pr requires an argument" >&2; exit 2; }
      PR_NUMBER="$2"; shift 2 ;;
    --branch)
      [[ $# -lt 2 ]] && { echo "Error: --branch requires an argument" >&2; exit 2; }
      BRANCH="$2"; shift 2 ;;
    --record)
      [[ $# -lt 2 ]] && { echo "Error: --record requires an argument" >&2; exit 2; }
      RECORD="$2"; shift 2 ;;
    --no-post) NO_POST="true"; shift ;;
    --help) usage; exit 0 ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ---- input validation ----
[[ -z "$REPORT_MD" ]] && { echo "Error: --report-md is required" >&2; usage >&2; exit 2; }
[[ -z "$REPORT_JSON" ]] && { echo "Error: --report-json is required" >&2; usage >&2; exit 2; }
[[ -z "$MODE" ]] && { echo "Error: --mode is required" >&2; usage >&2; exit 2; }

[[ -f "$REPORT_MD" ]] || { echo "Error: report-md not found: $REPORT_MD" >&2; exit 1; }
[[ -f "$REPORT_JSON" ]] || { echo "Error: report-json not found: $REPORT_JSON" >&2; exit 1; }

case "$MODE" in
  pr|local) ;;
  *) echo "Error: --mode must be 'pr' or 'local'" >&2; usage >&2; exit 2 ;;
esac

if [[ "$MODE" == "pr" && -z "$PR_NUMBER" ]]; then
  echo "Error: --pr <number> is required in pr mode" >&2
  usage >&2
  exit 2
fi

if [[ "$MODE" == "pr" && "$NO_POST" == "false" && -z "$RECORD" ]]; then
  echo "Error: --record <round.json> is required in pr mode (or pass --no-post)" >&2
  usage >&2
  exit 2
fi
if [[ -n "$RECORD" && ! -f "$RECORD" ]]; then
  if [[ "$NO_POST" == "true" ]]; then
    echo "Note: record not found ($RECORD); continuing without it because --no-post was given."
    RECORD=""
  else
    echo "Error: record not found: $RECORD" >&2
    exit 1
  fi
fi

# ---- helpers ----
# Find the repo root (for gitignore + local output file)
get_repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || echo "."
}

# Ensure *.adversarial-review.md is in .gitignore at repo root. A CRLF line
# ("pattern\r") counts as present. When the file does not end in a newline,
# one is added first so the pattern does not merge with the last line. A write
# failure is a warning, not an abort: the report is still delivered.
ensure_gitignored() {
  local repo_root="$1"
  local gitignore="$repo_root/.gitignore"
  local pattern="*.adversarial-review.md"

  if [[ -f "$gitignore" ]] && grep -qxF -e "$pattern" -e "$pattern"$'\r' "$gitignore"; then
    return 0
  fi
  local text="$pattern"$'\n'
  if [[ -f "$gitignore" && -s "$gitignore" && -n "$(tail -c 1 "$gitignore")" ]]; then
    text=$'\n'"$text"
  fi
  # One simple command: bash 3.2 does not report a failed redirect on a { } group.
  if ! printf '%s' "$text" 2>/dev/null >>"$gitignore"; then
    echo "WARNING: could not add '$pattern' to $gitignore; add it by hand so the local report is not committed." >&2
    return 0
  fi
  echo "Added '$pattern' to $gitignore"
}

# Write local markdown artifact
write_local_artifact() {
  local repo_root="$1"
  local branch="$2"
  local report_md="$3"
  local out_file
  out_file="$(local_out_file "$branch")"

  ensure_gitignored "$repo_root"
  cp "$report_md" "$out_file"
  echo ""
  echo "Report written to: $out_file"
}

# Local output file for a branch: <repo_root>/<branch with / as ->.adversarial-review.md
local_out_file() {
  local branch="$1"
  echo "$(get_repo_root)/${branch//\//-}.adversarial-review.md"
}

# Map a non-zero pr-audit.py exit code to a message. The report is already
# delivered by then, so every failure here is exit 4.
audit_failed() {
  local code="$1" where=""
  [[ -n "$PR_NUMBER" && "$NO_POST" == "false" ]] && where=" for PR #$PR_NUMBER"
  case "$code" in
    1) echo "WARNING: the audit trail$where is incomplete — see the pr-audit lines above." >&2 ;;
    2) echo "WARNING: the round record was rejected, no audit trail was saved." >&2 ;;
    3) echo "WARNING: pr-audit.py crashed; the audit trail may be partial — see the pr-audit line above." >&2 ;;
    *) echo "WARNING: pr-audit.py failed (exit $code), the audit trail may be incomplete." >&2 ;;
  esac
  return 4
}

# ---- mode: local ----
deliver_local() {
  local repo_root output_branch code=0
  repo_root="$(get_repo_root)"
  output_branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown-branch")}"

  echo ""
  echo "====== Adversarial PR Review Report ======"
  cat "$REPORT_MD"
  echo "=========================================="

  write_local_artifact "$repo_root" "$output_branch" "$REPORT_MD"
  if [[ -n "$RECORD" ]]; then
    python3 "$SCRIPT_DIR/pr-audit.py" local --record "$RECORD" \
      --out "$(local_out_file "$output_branch")" || code=$?
    [[ "$code" == "0" ]] || { audit_failed "$code"; return; }
  fi
}

# ---- mode: pr ----
deliver_pr() {
  local repo_root output_branch code=0
  repo_root="$(get_repo_root)"
  output_branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "pr-$PR_NUMBER")}"

  echo ""
  echo "====== Adversarial PR Review Report (PR #$PR_NUMBER) ======"
  cat "$REPORT_MD"
  echo "============================================================"

  # pr-audit.py falls back to this file when gh is unavailable or the PR cannot
  # be read, so keep it ignored.
  ensure_gitignored "$repo_root"
  python3 "$SCRIPT_DIR/pr-audit.py" post --pr "$PR_NUMBER" --record "$RECORD" \
    --fallback-out "$(local_out_file "$output_branch")" || code=$?
  [[ "$code" == "0" ]] || audit_failed "$code"
}

# ---- dispatch ----
case "$MODE" in
  local) deliver_local ;;
  pr)
    if [[ "$NO_POST" == "true" ]]; then
      deliver_local
    else
      deliver_pr
    fi
    ;;
esac
