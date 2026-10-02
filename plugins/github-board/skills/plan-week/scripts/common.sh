#!/usr/bin/env bash
# Shared settings for the weekly-focus launchd scripts. Sourced, not run.
# Every external command and path can be overridden from the environment (tests do).
_WF_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SKILL_DIR="${SKILL_DIR:-$(cd "$_WF_SCRIPTS/.." && pwd)}"
export LAUNCHCTL="${LAUNCHCTL:-launchctl}"
export OSASCRIPT="${OSASCRIPT:-/usr/bin/osascript}"
export PYTHON="${PYTHON:-python3}"
export LA_DIR="${LA_DIR:-$HOME/Library/LaunchAgents}"
export STATE_DIR="${STATE_DIR:-$HOME/.local/state/weekly-focus}"
export LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/weekly-focus}"
export NOW="${NOW:-$(date +%s)}"

SYNC_LABEL="com.abhattacherjee.weekly-focus-sync"
WATCHDOG_LABEL="com.abhattacherjee.weekly-focus-watchdog"
LABELS="$SYNC_LABEL $WATCHDOG_LABEL"
DOMAIN="gui/$(id -u)"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# notify <title suffix> <message>. A failed notification is ignored.
notify() {
  local msg="${2//\"/\'}"
  "$OSASCRIPT" -e "display notification \"${msg//\\/}\" with title \"Weekly Focus $1\"" >/dev/null 2>&1 || true
}

# Loaded in launchd's gui domain?
is_loaded() { "$LAUNCHCTL" print "$DOMAIN/$1" >/dev/null 2>&1; }

# reinstall <label> [install-launchd.sh flags]. Returns install-launchd.sh's exit code.
reinstall() { local label="$1"; shift; bash "$_WF_SCRIPTS/install-launchd.sh" --only "$label" "$@"; }

ALERT_GAP=$((6 * 3600))

# alert <kind> <title suffix> <message>: notify unless the same kind fired in the last 6h.
# The stamp holds the NOW value it fired at (not a file mtime), so NOW overrides work.
alert() {
  local stamp="$STATE_DIR/alert-$1" last=0
  [ -f "$stamp" ] && last=$(cat "$stamp" 2>/dev/null)
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  if [ $((NOW - last)) -ge "$ALERT_GAP" ]; then
    echo "$NOW" > "$stamp"
    notify "$2" "$3"
    return 0
  fi
  return 1
}

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }  # GNU, then BSD

# reinstall_or_alert <label> <log file> [install flags]: reinstall, and if that fails raise a
# reinstall-failed alert. Returns the reinstall exit code.
reinstall_or_alert() {
  local label="$1" logf="$2" rc; shift 2
  reinstall "$label" "$@" >> "$logf" 2>&1
  rc=$?
  if [ "$rc" -ne 0 ]; then
    log "reinstall FAILED for $label (exit $rc)" >> "$logf"
    alert reinstall-failed "reinstall failed" "reinstall FAILED for $label (exit $rc). See $logf"
  fi
  return "$rc"
}
