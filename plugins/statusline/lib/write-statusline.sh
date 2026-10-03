# shellcheck shell=bash
# Shared write guard for the statusline plugin's installers. Source it; do not run it.
# Works on macOS bash 3.2 and bash 5.
#
#   write_statusline <source> <target> <force:0|1>
#     Writes <source> to <target> only if <target> is absent or carries the marker on
#     line 2, or force is 1. An existing <target> is backed up to
#     <target>.bak-<UTC stamp> first. Writes go to a temp file in the target's own
#     directory, then mv, so a failed write leaves the old file in place.
#     Returns 0 written, 1 backup or write failed (target unchanged), 2 bad input,
#     3 refused (target not written by this plugin; nothing changed).
#
#   check_settings <settings.json>
#     Returns 0 if the file is absent, blank, or holds exactly one JSON object;
#     2 otherwise (and says why); 1 if jq is missing or the file cannot be read.
#
#   update_settings <settings.json> <command>
#     Sets .statusLine = {"type":"command","command":<command>}. Same temp-file + mv
#     write and the same backup as above, the file's mode is kept, a symlinked file is
#     updated through its link, and an already-correct file is not touched.
#     Returns 0, 1 (write failed or jq missing; file unchanged) or 2 (not one JSON object;
#     file byte-identical).

STATUSLINE_MARKER='# managed-by: statusline-plugin'

_sl_err() { printf '%s\n' "$*" >&2; }

# Follow a chain of symlinks to the path that holds the bytes.
_sl_resolve() {
  local p=$1 n=0 l
  while [ -L "$p" ]; do
    n=$((n + 1))
    [ "$n" -gt 40 ] && return 1
    l=$(readlink "$p") || return 1
    case $l in
      /*) p=$l ;;
      *) p=$(dirname "$p")/$l ;;
    esac
  done
  printf '%s\n' "$p"
}

# Copy <file> to a fresh <file>.bak-<UTC stamp>[-N]; print its path. The copy is
# compared byte for byte, so a short copy (disk full) counts as a failure.
_sl_backup() {
  local file=$1 base b i=1
  base="$file.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  b=$base
  while [ -e "$b" ] || [ -L "$b" ]; do
    b="$base-$i"
    i=$((i + 1))
  done
  if ! cp -p "$file" "$b" 2>/dev/null || ! cmp -s "$file" "$b"; then
    rm -f "$b"
    return 1
  fi
  printf '%s\n' "$b"
}

# Write <source> into a temp file next to <target>, check it, then mv it over <target>.
# <mode> is an octal mode, or "keep" to keep <target>'s current mode.
_sl_atomic_write() {
  local src=$1 target=$2 mode=$3 tmp
  tmp=$(mktemp "$(dirname "$target")/.$(basename "$target").XXXXXX" 2>/dev/null) || return 1
  if [ "$mode" = keep ] && [ -e "$target" ]; then
    # cp -p carries the mode over; the contents are replaced next.
    cp -p "$target" "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
    cat "$src" > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  else
    cp "$src" "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
    [ "$mode" = keep ] || chmod "$mode" "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  fi
  cmp -s "$src" "$tmp" || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$target" 2>/dev/null || { rm -f "$tmp"; return 1; }
}

write_statusline() {
  if [ $# -ne 3 ]; then
    _sl_err "usage: write_statusline <source> <target> <force:0|1>"
    return 2
  fi
  local src=$1 target=$2 force=$3 real b
  case $force in 0|1) ;; *) _sl_err "write_statusline: force must be 0 or 1 (got: $force)"; return 2 ;; esac
  if [ ! -f "$src" ] || [ ! -r "$src" ]; then
    _sl_err "write_statusline: source not readable: $src"
    return 2
  fi
  if [ "$(sed -n 2p "$src")" != "$STATUSLINE_MARKER" ]; then
    _sl_err "write_statusline: $src lacks '$STATUSLINE_MARKER' on line 2"
    return 2
  fi
  real=$(_sl_resolve "$target") || { _sl_err "Cannot resolve the symlink $target."; return 1; }
  if [ -d "$real" ]; then
    _sl_err "$target is a directory. Nothing written."
    return 1
  fi

  if [ -e "$real" ] || [ -L "$target" ]; then
    if [ "$force" != 1 ] && { [ ! -e "$real" ] || [ "$(sed -n 2p "$real" 2>/dev/null)" != "$STATUSLINE_MARKER" ]; }; then
      if [ -e "$real" ]; then
        _sl_err "$target already exists ($(wc -c < "$real" | tr -d ' ') bytes) and was not written by the statusline plugin (line 2 is not '$STATUSLINE_MARKER')."
      else
        _sl_err "$target is a symlink to $real, which does not exist."
      fi
      _sl_err "Left it untouched. To replace it, re-run with --force; the current file is backed up to $target.bak-<UTC time> first."
      return 3
    fi
  fi

  if [ -e "$real" ]; then
    b=$(_sl_backup "$real") || { _sl_err "Could not back up $real. Nothing written."; return 1; }
    echo "Backed up $real to $b"
  fi
  mkdir -p "$(dirname "$real")" 2>/dev/null || { _sl_err "Cannot create $(dirname "$real"). Nothing written."; return 1; }
  if ! _sl_atomic_write "$src" "$real" 755; then
    _sl_err "Could not write $target (disk full or no permission?). The old file, if any, is unchanged."
    return 1
  fi
  echo "Wrote $target"
}

_sl_need_jq() {
  command -v jq >/dev/null 2>&1 && return 0
  _sl_err "jq is required to update settings.json (and by the statusline itself). Install jq and re-run."
  return 1
}

# 0 = file holds no JSON text (absent, empty, or whitespace only).
_sl_blank() {
  [ ! -e "$1" ] || [ -z "$(tr -d ' \t\r\n' < "$1")" ]
}

check_settings() {
  local file=$1 real
  _sl_need_jq || return 1
  real=$(_sl_resolve "$file") || { _sl_err "Cannot resolve the symlink $file."; return 1; }
  if [ -d "$real" ]; then
    _sl_err "$file is a directory."
    return 2
  fi
  if [ -e "$real" ] && [ ! -r "$real" ]; then
    _sl_err "Cannot read $file. Nothing was written."
    return 1
  fi
  _sl_blank "$real" && return 0
  if ! jq -e -s 'length == 1 and (.[0] | type) == "object"' "$real" >/dev/null 2>&1; then
    _sl_err "$file is not a single JSON object. Fix it by hand; it was not changed."
    return 2
  fi
}

update_settings() {
  local file=$1 cmd=$2 real tmp b rc
  check_settings "$file" || return $?
  real=$(_sl_resolve "$file") || return 1
  if ! _sl_blank "$real" &&
     jq -e --arg cmd "$cmd" '.statusLine == {"type": "command", "command": $cmd}' "$real" >/dev/null 2>&1; then
    echo "$file already points statusLine at: $cmd"
    return 0
  fi
  mkdir -p "$(dirname "$real")" 2>/dev/null || { _sl_err "Cannot create $(dirname "$real")."; return 1; }
  tmp=$(mktemp "${TMPDIR:-/tmp}/statusline-settings.XXXXXX") || return 1
  if _sl_blank "$real"; then
    jq -n --arg cmd "$cmd" '{"statusLine": {"type": "command", "command": $cmd}}' > "$tmp"
  else
    jq --arg cmd "$cmd" '.statusLine = {"type": "command", "command": $cmd}' "$real" > "$tmp"
  fi
  rc=$?
  if [ $rc -ne 0 ] || ! jq -e --arg cmd "$cmd" '.statusLine.command == $cmd' "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    _sl_err "Could not build the new $file. It was not changed."
    return 1
  fi
  if [ -e "$real" ]; then
    b=$(_sl_backup "$real") || { rm -f "$tmp"; _sl_err "Could not back up $real. It was not changed."; return 1; }
    echo "Backed up $real to $b"
  fi
  if ! _sl_atomic_write "$tmp" "$real" keep; then
    rm -f "$tmp"
    _sl_err "Could not write $file. It is unchanged."
    return 1
  fi
  rm -f "$tmp"
  echo "Set statusLine in $file to: $cmd"
}
