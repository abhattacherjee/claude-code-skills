#!/usr/bin/env bash
# github-board shared helpers for bash scripts. Sourced, not run:
#   . "<plugin>/lib/config.sh"
# Every helper runs lib/config.py with $GB_PYTHON (default python3). GB_PYTHON is separate from
# the launchd scripts' $PYTHON, which tests replace with a stub.
#   gb_config_get KEY [--lines]   print a config value; exit 4 when there is no config, 2 when invalid
# A cache key is a tuple of separate arguments, never one joined string:
#   gb_cache_get PART...          print a fresh cache entry; non-zero on a miss
#   gb_cache_put PART...          store stdin JSON; never fails
#   gb_cache_drop PART...         forget one entry
#   gb_cache_key PART...          print the file name the tuple maps to
#   gb_cache_drop_containing TEXT forget every entry whose JSON contains TEXT (a stale id)
#   gb_error_kind TEXT            print rate, scope or other (a refetch never fixes rate or scope)
#   gb_next_release --repo O/R [--cache FILE]
#                                 print "<number>\t<title>" of the next-release milestone, or
#                                 nothing (a warning on stderr); exit 2 when the list is unreadable
#   gb_milestone_for_tag --repo O/R --tag TAG [--cache FILE]
#                                 print "<number>\t<title>" of TAG's release milestone, or
#                                 "skip\t<reason>"; exit 2 when the list is unreadable
# GB_NO_CACHE=1 (--no-cache): never read or write the cache.
# GB_CACHE_REFRESH=1: skip reads but write fresh entries (the one refetch after a stale id).
GB_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_PYTHON="${GB_PYTHON:-python3}"

gb_config_get() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" get "$@"; }

gb_cache_get() {
  if [ "${GB_NO_CACHE:-0}" = 1 ] || [ "${GB_CACHE_REFRESH:-0}" = 1 ]; then return 1; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache get -- "$@"
}

gb_cache_put() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then cat >/dev/null; return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache put -- "$@" || true
}

gb_cache_drop() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop -- "$@" || true
}

gb_cache_key() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache key -- "$@"; }

gb_cache_drop_containing() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop-containing "$1" >/dev/null || true
}

gb_error_kind() { printf '%s' "$1" | "$GB_PYTHON" "$GB_LIB_DIR/config.py" classify-error; }

gb_next_release() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" next-release-milestone "$@"; }

gb_milestone_for_tag() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" milestone-for-tag "$@"; }
