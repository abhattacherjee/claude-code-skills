#!/usr/bin/env bash
# Clean-HOME smoke test for the github-board plugin (#146). HOME is an empty temp dir and the
# environment is cleared, so no command can fall back to an installed copy under ~/.claude.
# Usage: smoke-clean-home.sh [--help]. Exit 0 when every command exits 0, else 1.
set -uo pipefail
case "${1:-}" in
  -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac
PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME"' EXIT
fail=0

run() { # run <label> <command...>
  local label="$1" out rc
  shift
  out="$(env -i PATH="$PATH" HOME="$TMP_HOME" "$@" 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "ok   $label"
  else
    echo "FAIL $label (exit $rc)"
    printf '%s\n' "$out" | head -5
    fail=1
  fi
}

run "plan-milestones milestone-report.sh --help" bash "$PLUGIN/skills/plan-milestones/scripts/milestone-report.sh" --help
run "plan-week weekly-focus.py --help" python3 "$PLUGIN/skills/plan-week/scripts/weekly-focus.py" --help
run "create-board task-manifest.sh" bash "$PLUGIN/skills/create-board/scripts/task-manifest.sh"
exit "$fail"
