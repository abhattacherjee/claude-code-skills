#!/usr/bin/env bash
# Install (or check) the weekly-focus launchd agents.
#   install-launchd.sh                  render both plists into ~/Library/LaunchAgents and load them
#   install-launchd.sh --only <label>   just one label
#   install-launchd.sh --no-reload      only write the plist files; no bootout/bootstrap
#   install-launchd.sh --check          write nothing; exit 1 if an installed plist is missing,
#                                       differs from its rendered template, or is not loaded
# Overrides for tests: LAUNCHCTL, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR, BOOTSTRAP_RETRY_SLEEP.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

only="" check=0 reload=1
while [ $# -gt 0 ]; do
  case "$1" in
    --only) only="${2:-}"; shift 2 || { echo "--only needs a label" >&2; exit 2; } ;;
    --check) check=1; shift ;;
    --no-reload) reload=0; shift ;;
    -h|--help) sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
if [ -n "$only" ]; then
  case " $LABELS " in *" $only "*) targets="$only" ;; *) echo "unknown label: $only" >&2; exit 2 ;; esac
else
  targets="$LABELS"
fi

render() { # render <label> -> stdout, with __HOME__ replaced
  local tpl="$SKILL_DIR/launchd/$1.plist.template" body
  [ -f "$tpl" ] || { echo "missing template: $tpl" >&2; return 1; }
  body=$(<"$tpl")
  printf '%s\n' "${body//__HOME__/$HOME}"
}

if [ "$check" -eq 1 ]; then
  rc=0
  for label in $targets; do
    plist="$LA_DIR/$label.plist"
    if ! is_loaded "$label"; then echo "NOT LOADED $label"; rc=1; fi
    if [ ! -f "$plist" ]; then echo "MISSING $plist"; rc=1; continue; fi
    want=$(render "$label") || { rc=1; continue; }
    have=$(<"$plist")
    if [ "$want" != "$have" ]; then echo "DIFFERS $plist"; rc=1; else echo "ok $plist"; fi
  done
  exit "$rc"
fi

mkdir -p "$LA_DIR" "$LOG_DIR" "$STATE_DIR"
rc=0
for label in $targets; do
  plist="$LA_DIR/$label.plist"
  if ! render "$label" > "$plist.tmp"; then rm -f "$plist.tmp"; rc=1; continue; fi
  mv "$plist.tmp" "$plist"
  if [ "$reload" -eq 0 ]; then echo "wrote $label (not reloaded)"; continue; fi
  "$LAUNCHCTL" bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  # bootout then bootstrap can fail with error 5 while launchd is still tearing the job down.
  ok=0
  for attempt in 1 2 3; do
    if "$LAUNCHCTL" bootstrap "$DOMAIN" "$plist"; then ok=1; break; fi
    [ "$attempt" -lt 3 ] && sleep "${BOOTSTRAP_RETRY_SLEEP:-1}"
  done
  if [ "$ok" -eq 1 ]; then
    echo "installed $label"
  else
    echo "bootstrap failed: $label" >&2; rc=1
  fi
done
exit "$rc"
