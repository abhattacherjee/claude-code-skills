#!/usr/bin/env bash
# github-board shared helpers for bash scripts. Sourced, not run:
#   . "<plugin>/lib/config.sh"
# Every helper runs lib/config.py with $GB_PYTHON (default python3). GB_PYTHON is separate from
# the launchd scripts' $PYTHON, which tests replace with a stub.
#   gb_config_get KEY [--lines]   print a config value; exit 4 when there is no config, 2 when invalid
#   gb_cache_get KEY              print a fresh cache entry; non-zero on a miss
#   gb_cache_put KEY              store stdin JSON; never fails
#   gb_cache_drop KEY             forget one entry
#   gb_cache_drop_containing TEXT forget every entry whose JSON contains TEXT (a stale id)
# GB_NO_CACHE=1 (--no-cache): never read or write the cache.
# GB_CACHE_REFRESH=1: skip reads but write fresh entries (the one refetch after a stale id).
GB_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_PYTHON="${GB_PYTHON:-python3}"

gb_config_get() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" get "$@"; }

gb_cache_get() {
  if [ "${GB_NO_CACHE:-0}" = 1 ] || [ "${GB_CACHE_REFRESH:-0}" = 1 ]; then return 1; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache get "$1"
}

gb_cache_put() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then cat >/dev/null; return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache put "$1" || true
}

gb_cache_drop() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop "$1" || true
}

gb_cache_drop_containing() {
  if [ "${GB_NO_CACHE:-0}" = 1 ]; then return 0; fi
  "$GB_PYTHON" "$GB_LIB_DIR/config.py" cache drop-containing "$1" >/dev/null || true
}
