#!/usr/bin/env bash
# Shared settings for the plan-week launchd scripts. Sourced, not run.
# Every external command and path can be overridden from the environment (tests do).
# Labels come from the github-board config (plan_week.launchd.label_prefix); a missing or
# invalid config exits here with config.py's code (4 or 2). A script that launchd runs sets
# GB_ALERT_ON_CONFIG_ERROR=1 before sourcing this, so that failure is also recorded in
# $STATE_DIR/last-error and raised as a notification (at most once per 6h) instead of
# vanishing into launchd's error log.
_WF_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SKILL_DIR="${SKILL_DIR:-$(cd "$_WF_SCRIPTS/.." && pwd)}"
export LAUNCHCTL="${LAUNCHCTL:-launchctl}"
export OSASCRIPT="${OSASCRIPT:-/usr/bin/osascript}"
export PYTHON="${PYTHON:-python3}"
export LA_DIR="${LA_DIR:-$HOME/Library/LaunchAgents}"
export STATE_DIR="${STATE_DIR:-$HOME/.local/state/weekly-focus}"
export LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/weekly-focus}"
export NOW="${NOW:-$(date +%s)}"
# install-launchd.sh copies the scripts it needs into $GITHUB_BOARD_HOME/<plugin version>/ and
# points the stable link $GITHUB_BOARD_HOME/current at that copy. The plists run through the
# link, so the jobs never depend on the plugin cache (which keeps only two versions).
export GITHUB_BOARD_HOME="${GITHUB_BOARD_HOME:-$HOME/.local/share/github-board}"
export GITHUB_BOARD_LINK="${GITHUB_BOARD_LINK:-$GITHUB_BOARD_HOME/current}"
# The plugin root this copy runs from, symlinks resolved, so the link never points at itself.
PLUGIN_ROOT="$(cd "$_WF_SCRIPTS/../../.." && pwd -P)"
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
# reinstall-failed alert for that label (one stamp per label, so a failing sync job cannot hide
# a failing watchdog). Returns the reinstall exit code.
reinstall_or_alert() {
  local label="$1" logf="$2" rc; shift 2
  reinstall "$label" "$@" >> "$logf" 2>&1
  rc=$?
  if [ "$rc" -ne 0 ]; then
    log "reinstall FAILED for $label (exit $rc)" >> "$logf"
    alert "reinstall-failed-$label" "reinstall failed" "reinstall FAILED for $label (exit $rc). See $logf"
  fi
  return "$rc"
}

. "$_WF_SCRIPTS/../../../lib/config.sh"
_gb_err="$(mktemp)"
_gb_rc=0
LABEL_PREFIX="$(gb_config_get plan_week.launchd.label_prefix 2>"$_gb_err")" || _gb_rc=$?
if [ "$_gb_rc" -ne 0 ]; then
  cat "$_gb_err" >&2
  if [ "${GB_ALERT_ON_CONFIG_ERROR:-0}" = 1 ]; then
    mkdir -p "$STATE_DIR"
    { echo "$(date -u +%FT%TZ) plan-week config unreadable (exit $_gb_rc)"; cat "$_gb_err"; } > "$STATE_DIR/last-error"
    alert config "config error" "plan-week cannot read its config (exit $_gb_rc): run plan-week init or fix the file. See $STATE_DIR/last-error"
  fi
  rm -f "$_gb_err"
  exit "$_gb_rc"
fi
rm -f "$_gb_err"
SYNC_LABEL="$LABEL_PREFIX-sync"
# launchd_enabled: plan_week.launchd.enabled is true. When it is false the jobs must not
# reinstall each other (that would fail with exit 2 and alert every 6h for nothing).
launchd_enabled() { [ "$(gb_config_get plan_week.launchd.enabled 2>/dev/null)" = true ]; }
WATCHDOG_LABEL="$LABEL_PREFIX-watchdog"
LABELS="$SYNC_LABEL $WATCHDOG_LABEL"
