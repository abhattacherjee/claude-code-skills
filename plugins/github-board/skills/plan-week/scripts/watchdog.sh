#!/usr/bin/env bash
# Hourly watchdog for the plan-week sync (launchd StartInterval 3600 + RunAtLoad, no KeepAlive).
#  1. a plist is missing from $LA_DIR       -> reinstall it, alert "restored". The watchdog's own
#                                              plist is only rewritten (--no-reload): launchd has it
#                                              loaded, and a bootout would kill this very run.
#  2. the sync job is not loaded            -> reinstall it, alert "unloaded"
#  3. last-success missing or > 26h old     -> alert "stale" (with the first line of last-error);
#                                              no alert while the sync plist is under 26h old
#  A failed reinstall alerts "reinstall FAILED" instead of claiming a restore.
# With plan_week.launchd.enabled false it logs that and exits 0 without touching anything.
# Each alert kind (and each label's reinstall failure) is rate-limited to once per 6h (stamp
# files in $STATE_DIR). Always exits 0,
# except when the github-board config cannot be read: then it alerts "config error" and exits
# with config.py's code (4 or 2), since it cannot know its own labels.
# Overrides for tests: LAUNCHCTL, OSASCRIPT, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR, NOW.
set -uo pipefail
GB_ALERT_ON_CONFIG_ERROR=1
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

STALE_HOURS=26
mkdir -p "$STATE_DIR" "$LOG_DIR"
WLOG="$LOG_DIR/watchdog.log"

if ! launchd_enabled; then
  log "watchdog: plan_week.launchd.enabled is false; nothing to watch"
  exit 0
fi

summary=""

for label in $LABELS; do
  if [ ! -f "$LA_DIR/$label.plist" ]; then
    flags=()
    [ "$label" = "$WATCHDOG_LABEL" ] && flags=(--no-reload)
    if reinstall_or_alert "$label" "$WLOG" ${flags[@]+"${flags[@]}"}; then
      alert restored "restored" "$label.plist was missing and was reinstalled."
      summary="$summary restored=$label"
    else
      summary="$summary reinstall-failed=$label"
    fi
  fi
done

if ! is_loaded "$SYNC_LABEL"; then
  if reinstall_or_alert "$SYNC_LABEL" "$WLOG"; then
    alert unloaded "sync not loaded" "The weekly-focus sync job was not loaded and was reinstalled."
    summary="$summary unloaded=$SYNC_LABEL"
  else
    summary="$summary reinstall-failed=$SYNC_LABEL"
  fi
fi

hb="$STATE_DIR/last-success"
detail=""
[ -f "$STATE_DIR/last-error" ] && detail=" Last error: $(head -n 1 "$STATE_DIR/last-error")"
sync_plist="$LA_DIR/$SYNC_LABEL.plist"
if [ ! -f "$hb" ]; then
  # Grace: a freshly installed sync has had no chance to run yet.
  if [ -f "$sync_plist" ] && [ $(( (NOW - $(mtime "$sync_plist")) / 3600 )) -lt "$STALE_HOURS" ]; then
    summary="$summary stale=pending"
  else
    alert stale "sync stale" "No successful sync recorded yet.$detail"
    summary="$summary stale=never"
  fi
else
  age_h=$(( (NOW - $(mtime "$hb")) / 3600 ))
  if [ "$age_h" -ge "$STALE_HOURS" ]; then
    alert stale "sync stale" "No successful sync in ${age_h}h (limit ${STALE_HOURS}h).$detail"
    summary="$summary stale=${age_h}h"
  else
    summary="$summary ok=${age_h}h"
  fi
fi

log "watchdog:$summary"
exit 0
