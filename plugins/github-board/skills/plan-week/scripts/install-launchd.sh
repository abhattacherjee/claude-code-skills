#!/usr/bin/env bash
# Install (or check) the plan-week launchd agents.
#   install-launchd.sh                  point the stable link at this plugin, render both plists
#                                       into ~/Library/LaunchAgents and load them
#   install-launchd.sh --only <label>   just one label
#   install-launchd.sh --no-reload      write the link and plist files; no bootout/bootstrap
#   install-launchd.sh --takeover       replace plists that another copy (an older bare skill) owns
#   install-launchd.sh --check          write nothing; exit 1 if the link or a plist is missing or
#                                       wrong, differs from its template, or is not loaded
# Labels: <plan_week.launchd.label_prefix>-sync and -watchdog. Sync times: plan_week.launchd.times.
# The plists run the scripts through $GITHUB_BOARD_LINK (~/.local/share/github-board/current).
# Re-run this after every plugin update so the link points at the new version.
# Exit codes: 0 ok; 1 a launchctl step or a check failed; 2 bad arguments, or launchd is disabled
# in the config; 3 refused: another copy owns a plist (pass --takeover) or the link path is not a
# symlink; 4 no config (run plan-week init).
# Overrides for tests: LAUNCHCTL, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR, GITHUB_BOARD_LINK, GB_PYTHON,
# XDG_CONFIG_HOME, XDG_CACHE_HOME, BOOTSTRAP_RETRY_SLEEP.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

only="" check=0 reload=1 takeover=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) only="${2:-}"; shift 2 || { echo "--only needs a label" >&2; exit 2; } ;;
    --check) check=1; shift ;;
    --no-reload) reload=0; shift ;;
    --takeover) takeover=1; shift ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done
if [ -n "$only" ]; then
  case " $LABELS " in *" $only "*) targets="$only" ;; *) echo "unknown label: $only" >&2; exit 2 ;; esac
else
  targets="$LABELS"
fi

enabled="$(gb_config_get plan_week.launchd.enabled)" || exit $?
if [ "$enabled" != true ]; then
  echo "plan_week.launchd.enabled is false in the config; nothing to install" >&2
  exit 2
fi

calendar_xml() { # one <dict> per plan_week.launchd.times entry
  local t h m times
  times="$(gb_config_get plan_week.launchd.times --lines)" || return 1
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    h=$((10#${t%%:*})); m=$((10#${t##*:}))
    printf '\t\t<dict>\n\t\t\t<key>Hour</key>\n\t\t\t<integer>%d</integer>\n\t\t\t<key>Minute</key>\n\t\t\t<integer>%d</integer>\n\t\t</dict>\n' "$h" "$m"
  done <<< "$times"
}

render() { # render <label> -> stdout
  local kind tpl body cal
  case "$1" in
    "$SYNC_LABEL") kind=sync ;;
    "$WATCHDOG_LABEL") kind=watchdog ;;
    *) echo "unknown label: $1" >&2; return 1 ;;
  esac
  tpl="$SKILL_DIR/launchd/$kind.plist.template"
  [ -f "$tpl" ] || { echo "missing template: $tpl" >&2; return 1; }
  body=$(<"$tpl")
  # None of these values contains '&', so bash 5.2's patsub_replacement cannot bite.
  body="${body//__LABEL__/$1}"
  body="${body//__SCRIPTS__/$GITHUB_BOARD_LINK/skills/plan-week/scripts}"
  body="${body//__XDG_CONFIG_HOME__/${XDG_CONFIG_HOME:-$HOME/.config}}"
  body="${body//__XDG_CACHE_HOME__/${XDG_CACHE_HOME:-$HOME/.cache}}"
  body="${body//__HOME__/$HOME}"
  if [ "$kind" = sync ]; then
    cal="$(calendar_xml)" || return 1
    body="${body//__CALENDAR__/$cal}"
  fi
  printf '%s\n' "$body"
}

plist_program() { # plist_program <plist> -> the script launchd runs; non-zero if unreadable
  "$GB_PYTHON" - "$1" <<'PY'
import plistlib, sys
try:
    with open(sys.argv[1], "rb") as f:
        print(plistlib.load(f)["ProgramArguments"][-1])
except Exception:
    sys.exit(1)
PY
}

guard_owner() { # guard_owner <label>: 0 when we may write its plist, 3 when another copy owns it
  local plist="$LA_DIR/$1.plist" prog
  [ -e "$plist" ] || return 0
  if ! prog="$(plist_program "$plist")"; then
    echo "refusing: cannot read $plist, so its owner is unknown. Inspect it, then re-run with --takeover." >&2
    return 3
  fi
  case "$prog" in "$GITHUB_BOARD_LINK"/*) return 0 ;; esac
  echo "refusing: $plist runs $prog, which belongs to another copy. Re-run with --takeover to hand the job to this plugin." >&2
  return 3
}

check_link() {
  if [ ! -L "$GITHUB_BOARD_LINK" ]; then
    if [ -e "$GITHUB_BOARD_LINK" ]; then echo "NOT A LINK $GITHUB_BOARD_LINK"; else echo "MISSING LINK $GITHUB_BOARD_LINK"; fi
    return 1
  fi
  if [ ! -e "$GITHUB_BOARD_LINK" ]; then echo "DANGLING LINK $GITHUB_BOARD_LINK"; return 1; fi
  if [ ! -f "$GITHUB_BOARD_LINK/skills/plan-week/scripts/run-sync.sh" ]; then
    echo "BAD LINK $GITHUB_BOARD_LINK (no skills/plan-week/scripts/run-sync.sh)"; return 1
  fi
  echo "ok $GITHUB_BOARD_LINK -> $(readlink "$GITHUB_BOARD_LINK")"
}

if [ "$check" -eq 1 ]; then
  rc=0
  check_link || rc=1
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

# Refuse before writing anything.
if [ -e "$GITHUB_BOARD_LINK" ] && [ ! -L "$GITHUB_BOARD_LINK" ]; then
  echo "refusing: $GITHUB_BOARD_LINK exists and is not a symlink. Move it away, then re-run." >&2
  exit 3
fi
if [ "$takeover" -eq 0 ]; then
  refused=0
  for label in $targets; do guard_owner "$label" || refused=3; done
  [ "$refused" -eq 0 ] || exit 3
fi

mkdir -p "$(dirname "$GITHUB_BOARD_LINK")" || exit 1
ln -sfn "$PLUGIN_ROOT" "$GITHUB_BOARD_LINK" || { echo "could not write $GITHUB_BOARD_LINK" >&2; exit 1; }

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
