#!/usr/bin/env bash
# launchd entry point: run `weekly-focus.py sync`, record success or failure, then make sure
# the watchdog is still loaded (nothing else watches the watchdog), unless
# plan_week.launchd.enabled is false.
# State: $STATE_DIR/last-success (touched on success), $STATE_DIR/last-error (on failure).
# Exit 3 from sync means "skipped: GraphQL budget low". That is logged only: last-success and
# last-error stay as they are and nothing is notified. If skips keep happening, the watchdog's
# 26h staleness alert fires. Any other non-zero exit is a failure.
# A missing or invalid github-board config exits 4 or 2 before sync runs; common.sh records it
# in last-error and notifies (at most once per 6h).
# Overrides for tests: PYTHON, LAUNCHCTL, OSASCRIPT, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR.
set -uo pipefail
GB_ALERT_ON_CONFIG_ERROR=1
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mkdir -p "$STATE_DIR" "$LOG_DIR"
errtmp=$(mktemp)
trap 'rm -f "$errtmp"' EXIT

log "sync start" >> "$LOG_DIR/sync.log"
"$PYTHON" "$SKILL_DIR/scripts/weekly-focus.py" sync >> "$LOG_DIR/sync.log" 2> "$errtmp"
rc=$?
cat "$errtmp" >> "$LOG_DIR/sync.err.log"

if [ "$rc" -eq 0 ]; then
  touch "$STATE_DIR/last-success"
  rm -f "$STATE_DIR/last-error"
  log "sync ok" >> "$LOG_DIR/sync.log"
elif [ "$rc" -eq 3 ]; then
  log "sync skipped (GraphQL budget low): $(tail -n 1 "$errtmp")" >> "$LOG_DIR/sync.log"
  rc=0
else
  { echo "$(date -u +%FT%TZ) sync failed (exit $rc)"; tail -n 20 "$errtmp"; } > "$STATE_DIR/last-error"
  log "sync FAILED (exit $rc)" >> "$LOG_DIR/sync.log"
  notify "sync failed" "Weekly Focus sync failed (exit $rc). See $STATE_DIR/last-error"
fi

if launchd_enabled && ! is_loaded "$WATCHDOG_LABEL"; then
  log "watchdog not loaded, reinstalling" >> "$LOG_DIR/sync.log"
  if reinstall_or_alert "$WATCHDOG_LABEL" "$LOG_DIR/sync.log"; then
    notify "watchdog restored" "The weekly-focus watchdog was not loaded and was reinstalled."
  fi
fi
exit "$rc"
