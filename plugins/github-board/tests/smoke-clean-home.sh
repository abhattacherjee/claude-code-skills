#!/usr/bin/env bash
# Clean-HOME smoke test for the github-board plugin (#146). HOME is an empty temp dir and the
# environment is cleared, so no command can fall back to an installed copy under ~/.claude.
# Two kinds of check, neither touching the network:
#   - start-up only: --help / task manifests exit before loading anything, so they prove only
#     that the script runs from the plugin;
#   - config readers: they load lib/config.py from inside the plugin and look for the config
#     under the clean HOME, so they must fail with "no config" (exit 4) and name the init to
#     run, and `config.py path` must print a path under that HOME.
# Usage: smoke-clean-home.sh [--help]. Exit 0 when every check passes, else 1.
set -uo pipefail
case "${1:-}" in
  -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac
PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME"' EXIT
fail=0

run() { # run <label> <expected exit> <expected text or ""> <command...>
  local label="$1" want="$2" text="$3" out rc
  shift 3
  out="$(env -i PATH="$PATH" HOME="$TMP_HOME" "$@" 2>&1)"
  rc=$?
  if [ "$rc" -eq "$want" ] && { [ -z "$text" ] || printf '%s' "$out" | grep -qF -- "$text"; }; then
    echo "ok   $label"
  else
    echo "FAIL $label (exit $rc, wanted $want${text:+ and \"$text\"})"
    printf '%s\n' "$out" | head -5
    fail=1
  fi
}

# start-up only
run "plan-milestones milestone-report.sh --help" 0 "" bash "$PLUGIN/skills/plan-milestones/scripts/milestone-report.sh" --help
run "plan-week weekly-focus.py --help" 0 "" python3 "$PLUGIN/skills/plan-week/scripts/weekly-focus.py" --help
run "create-board task-manifest.sh" 0 "" bash "$PLUGIN/skills/create-board/scripts/task-manifest.sh"
# config readers: lib from the plugin, config from the clean HOME only
run "lib config.py path" 0 "$TMP_HOME/.config/github-board/config.json" python3 "$PLUGIN/lib/config.py" path
run "plan-week weekly-focus.py config (no config)" 4 "plan-week init" python3 "$PLUGIN/skills/plan-week/scripts/weekly-focus.py" config
run "create-board init-config.sh --show (no config)" 4 "init" bash "$PLUGIN/skills/create-board/scripts/init-config.sh" --show
run "plan-week install-launchd.sh --check (no config)" 4 "plan-week init" bash "$PLUGIN/skills/plan-week/scripts/install-launchd.sh" --check
exit "$fail"
