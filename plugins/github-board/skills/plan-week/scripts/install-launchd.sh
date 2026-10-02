#!/usr/bin/env bash
# Install (or check) the plan-week launchd agents.
#   install-launchd.sh                  copy the plan-week scripts and lib into
#                                       $GITHUB_BOARD_HOME/<plugin version>/, point the stable link
#                                       $GITHUB_BOARD_HOME/current at that copy, render both plists
#                                       into ~/Library/LaunchAgents and load them
#   install-launchd.sh --only <label>   just one label
#   install-launchd.sh --no-reload      write the copy, link and plist files; no bootout/bootstrap
#   install-launchd.sh --takeover       replace plists that another copy (an older bare skill) owns
#   install-launchd.sh --check          write nothing; exit 1 if the link, the copy or a plist is
#                                       missing or wrong, the copy is older than this plugin, a
#                                       plist differs from its template, or a label is not loaded
# Labels: <plan_week.launchd.label_prefix>-sync and -watchdog. Sync times: plan_week.launchd.times.
# GITHUB_BOARD_HOME defaults to ~/.local/share/github-board. The jobs run only from the copy, so
# removing or upgrading the plugin never breaks them; re-run this after a plugin update to move
# them to the new code. A re-install replaces the copy for this version and deletes older
# version copies, except the one the link pointed at before (it may still be running).
# Exit codes: 0 ok; 1 a copy, launchctl step or check failed; 2 bad arguments, or launchd is
# disabled in the config; 3 refused: another copy owns a plist (pass --takeover) or the link path
# is not a symlink; 4 no config (run plan-week init).
# Overrides for tests: LAUNCHCTL, LA_DIR, STATE_DIR, LOG_DIR, SKILL_DIR, GITHUB_BOARD_HOME,
# GITHUB_BOARD_LINK, GB_PYTHON, XDG_CONFIG_HOME, XDG_CACHE_HOME, BOOTSTRAP_RETRY_SLEEP.
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

plugin_version() { # the version in this plugin's plugin.json; non-zero if unreadable or odd
  "$GB_PYTHON" - "$PLUGIN_ROOT/.claude-plugin/plugin.json" <<'PY'
import json, re, sys
try:
    v = json.load(open(sys.argv[1]))["version"]
except Exception:
    sys.exit(1)
if not isinstance(v, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", v):
    sys.exit(1)
print(v)
PY
}

# The parts of the plugin the jobs need, relative to the plugin root. The copy keeps the same
# layout, so the scripts' own relative paths (../../../lib) work unchanged.
COPY_PARTS="skills/plan-week/scripts skills/plan-week/launchd lib .claude-plugin/plugin.json"

copy_differs() { # copy_differs <copy dir>: 0 when any part differs from this plugin
  local part
  for part in $COPY_PARTS; do
    diff -rq -x __pycache__ "$PLUGIN_ROOT/$part" "$1/$part" >/dev/null 2>&1 || return 0
  done
  return 1
}

install_copy() { # install_copy <copy dir>: (re)create it from this plugin; non-zero on failure
  local dest="$1" new="$1.new.$$" old="$1.old.$$" part
  # Running from the copy itself (through the link): it is already in place.
  if [ -d "$dest" ] && [ "$(cd "$dest" && pwd -P)" = "$PLUGIN_ROOT" ]; then return 0; fi
  rm -rf "$new"
  for part in $COPY_PARTS; do
    mkdir -p "$new/$(dirname "$part")" && cp -R "$PLUGIN_ROOT/$part" "$new/$part" \
      || { echo "could not copy $PLUGIN_ROOT/$part to $new" >&2; rm -rf "$new"; return 1; }
  done
  find "$new" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  if [ -e "$dest" ]; then mv "$dest" "$old" || { rm -rf "$new"; return 1; }; fi
  mv "$new" "$dest" || { echo "could not move $new to $dest" >&2; return 1; }
  rm -rf "$old"
}

prune_copies() { # prune_copies <keep> <keep>: delete other version copies under GITHUB_BOARD_HOME
  local d name
  for d in "$GITHUB_BOARD_HOME"/*; do
    [ -d "$d" ] && [ ! -L "$d" ] || continue
    name="${d##*/}"
    case "$name" in [0-9]*.[0-9]*) ;; *) continue ;; esac
    case "$name" in *.new.*|*.old.*) continue ;; esac
    [ "$name" = "$1" ] || [ "$name" = "$2" ] && continue
    [ -d "$d/skills/plan-week" ] || continue          # only ever delete our own copies
    rm -rf "$d"
  done
}

check_link() {
  local target home
  if [ ! -L "$GITHUB_BOARD_LINK" ]; then
    if [ -e "$GITHUB_BOARD_LINK" ]; then echo "NOT A LINK $GITHUB_BOARD_LINK"; else echo "MISSING LINK $GITHUB_BOARD_LINK"; fi
    return 1
  fi
  if [ ! -e "$GITHUB_BOARD_LINK" ]; then echo "DANGLING LINK $GITHUB_BOARD_LINK"; return 1; fi
  if [ ! -f "$GITHUB_BOARD_LINK/skills/plan-week/scripts/run-sync.sh" ]; then
    echo "BAD LINK $GITHUB_BOARD_LINK (no skills/plan-week/scripts/run-sync.sh)"; return 1
  fi
  target="$(cd "$GITHUB_BOARD_LINK" && pwd -P)"
  home="$(cd "$GITHUB_BOARD_HOME" 2>/dev/null && pwd -P)"
  if [ -z "$home" ] || [ "$(dirname "$target")" != "$home" ]; then
    echo "NOT A COPY $GITHUB_BOARD_LINK -> $target (not under $GITHUB_BOARD_HOME; re-run install-launchd.sh)"
    return 1
  fi
  if [ "$target" != "$PLUGIN_ROOT" ] && copy_differs "$target"; then
    echo "STALE COPY $target differs from $PLUGIN_ROOT (re-run install-launchd.sh)"
    return 1
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

version="$(plugin_version)" || { echo "cannot read the version in $PLUGIN_ROOT/.claude-plugin/plugin.json" >&2; exit 1; }
copy="$GITHUB_BOARD_HOME/$version"
previous=""
[ -L "$GITHUB_BOARD_LINK" ] && previous="$(basename "$(readlink "$GITHUB_BOARD_LINK")")"
mkdir -p "$GITHUB_BOARD_HOME" "$(dirname "$GITHUB_BOARD_LINK")" || exit 1
install_copy "$copy" || exit 1
ln -sfn "$copy" "$GITHUB_BOARD_LINK" || { echo "could not write $GITHUB_BOARD_LINK" >&2; exit 1; }
prune_copies "$version" "$previous"

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
