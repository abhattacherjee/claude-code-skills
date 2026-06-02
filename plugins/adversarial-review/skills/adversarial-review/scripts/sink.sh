#!/usr/bin/env bash
# sink.sh — deliver synthesized review report (local file or PR comments)
# Usage: sink.sh --report-md <md> --report-json <json> --mode <pr|local>
#                [--pr <n>] [--branch <name>] [--help]
# Exit codes: 0=ok, 1=error, 2=usage

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
REPORT_MD=""
REPORT_JSON=""
MODE=""
PR_NUMBER=""
BRANCH=""

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --report-md <md> --report-json <json> --mode <pr|local>
         [--pr <n>] [--branch <name>] [--help]

Deliver the synthesized adversarial review report: post PR comments (pr mode)
or write a gitignored markdown file + print to terminal (local mode).

Options:
  --report-md <file>    Path to the markdown report (required)
  --report-json <file>  Path to the structured JSON report (required)
  --mode <pr|local>     Delivery mode (required)
  --pr <number>         PR number (required in pr mode)
  --branch <name>       Branch name (required in local mode for output filename)
  --help                Show this help and exit

pr mode behavior:
  Posts each SURVIVOR finding as a PR review comment via pr-review-cli.sh
  if that tool is available. If not found, falls back to local mode
  with a notice (never fails on missing optional integration).

local mode behavior:
  Prints the report to terminal AND writes <branch>.adversarial-review.md
  in the repo root. Ensures *.adversarial-review.md is gitignored.

Exit codes:
  0  Success
  1  Error
  2  Usage error
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

# ---- helpers ----
# Find the repo root (for gitignore + local output file)
get_repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || echo "."
}

# Ensure *.adversarial-review.md is in .gitignore at repo root
ensure_gitignored() {
  local repo_root="$1"
  local gitignore="$repo_root/.gitignore"
  local pattern="*.adversarial-review.md"

  if [[ -f "$gitignore" ]]; then
    if grep -qF "$pattern" "$gitignore"; then
      return 0
    fi
  fi
  echo "$pattern" >>"$gitignore"
  echo "Added '$pattern' to $gitignore"
}

# Write local markdown artifact
write_local_artifact() {
  local repo_root="$1"
  local branch="$2"
  local report_md="$3"

  # Sanitize branch name for filename (replace / with -)
  local safe_branch
  safe_branch="${branch//\//-}"
  local out_file="$repo_root/${safe_branch}.adversarial-review.md"

  ensure_gitignored "$repo_root"
  cp "$report_md" "$out_file"
  echo ""
  echo "Report written to: $out_file"
}

# Search for pr-review-cli.sh in known locations
find_pr_review_cli() {
  local candidates=(
    "pr-review-cli.sh"
    "$HOME/.claude/skills/pr-review-loop/scripts/pr-review-cli.sh"
  )

  # Check command in PATH
  if command -v pr-review-cli.sh >/dev/null 2>&1; then
    command -v pr-review-cli.sh
    return 0
  fi

  # Check fixed paths
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" && -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  # Check plugin cache glob
  local plugin_cache_paths
  plugin_cache_paths="$(find "$HOME/.claude/plugins/cache" -name "pr-review-cli.sh" -path "*/pr-review-loop/*/skills/*/scripts/*" 2>/dev/null || true)"
  if [[ -n "$plugin_cache_paths" ]]; then
    # Return first match
    echo "$plugin_cache_paths" | head -1
    return 0
  fi

  return 1
}

# ---- mode: local ----
deliver_local() {
  local repo_root
  repo_root="$(get_repo_root)"

  local output_branch="$BRANCH"
  if [[ -z "$output_branch" ]]; then
    output_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown-branch")"
  fi

  # Print to terminal
  echo ""
  echo "====== Adversarial PR Review Report ======"
  cat "$REPORT_MD"
  echo "=========================================="

  write_local_artifact "$repo_root" "$output_branch" "$REPORT_MD"
}

# ---- mode: pr ----
deliver_pr() {
  local pr_review_cli
  local cli_found=false

  if pr_review_cli="$(find_pr_review_cli 2>/dev/null)"; then
    cli_found=true
  fi

  if [[ "$cli_found" == "false" ]]; then
    echo ""
    echo "NOTICE: pr-review-cli.sh not found — PR comment posting is an optional integration."
    echo "        To enable: install the pr-review-loop plugin."
    echo "        Falling back to local markdown output."
    echo ""
    # Fallback to local
    local output_branch="$BRANCH"
    if [[ -z "$output_branch" ]]; then
      output_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "branch-$PR_NUMBER")"
    fi

    local repo_root
    repo_root="$(get_repo_root)"

    echo "====== Adversarial PR Review Report (PR #$PR_NUMBER) ======"
    cat "$REPORT_MD"
    echo "============================================================"

    write_local_artifact "$repo_root" "${output_branch:-pr-${PR_NUMBER}}" "$REPORT_MD"
    return 0
  fi

  echo "Using pr-review-cli.sh at: $pr_review_cli"

  # Extract survivors from report JSON and post each as a review comment
  local survivors_count
  survivors_count="$(python3 - "$REPORT_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
findings = data.get("findings", [])
survivors = [f for f in findings if f.get("status") == "survivor"]
print(len(survivors))
PYEOF
)"

  if [[ -z "$survivors_count" || ! "$survivors_count" =~ ^[0-9]+$ ]]; then
    echo "Error: could not determine survivors_count from report JSON" >&2
    return 1
  fi
  if [[ "$survivors_count" -eq 0 ]]; then
    echo "No survivor findings to post as PR comments."
    # Still print the report
    echo ""
    cat "$REPORT_MD"
    return 0
  fi

  echo "Posting $survivors_count survivor finding(s) as PR #$PR_NUMBER review comments..."

  # Extract and post each survivor
  python3 - "$REPORT_JSON" "$PR_NUMBER" "$pr_review_cli" <<'PYEOF'
import json, subprocess, sys, textwrap

report_json = sys.argv[1]
pr_number = sys.argv[2]
cli = sys.argv[3]

data = json.load(open(report_json))
findings = data.get("findings", [])
survivors = [f for f in findings if f.get("status") == "survivor"]

posted = 0
failed = 0

for f in survivors:
    path = f.get("path", "")
    line = f.get("line")
    severity = f.get("severity", "unknown").upper()
    category = f.get("category", "unknown")
    origin = f.get("origin", "unknown")
    title = f.get("title", "(no title)")
    rationale = f.get("rationale", "")

    comment_body = (
        f"**[{severity}] {title}** `{category}` *(adversarial-review — both models confirmed)*\n\n"
        f"{rationale}\n\n"
        f"*Origin: {origin} | Confirmed by both Claude and Gemini*"
    )

    cmd = [cli, "--pr", pr_number, "--body", comment_body]
    if path:
        cmd += ["--path", path]
    if line is not None:
        cmd += ["--line", str(line)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        posted += 1
        print(f"  Posted: [{severity}] {title}")
    else:
        failed += 1
        print(f"  Failed to post [{severity}] {title}: {result.stderr.strip()}", file=sys.stderr)

print(f"\nPosted {posted} comment(s), {failed} failed.")
PYEOF

  echo ""
  echo "PR review comments posted for PR #$PR_NUMBER."
}

# ---- dispatch ----
case "$MODE" in
  local) deliver_local ;;
  pr)    deliver_pr ;;
esac
