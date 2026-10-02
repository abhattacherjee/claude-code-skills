#!/usr/bin/env bash
# Write (or show) the create_board section of the github-board config.
#   init-config.sh --show            print the current config (exit 4 when there is none)
#   init-config.sh [--force] < payload.json
#     payload: {"create_board": {"template_owner": "<login>", "template_number": <n>}}
#     plus "owner": "<login>" when there is no config yet.
# Exit codes: 0 written or shown; 2 invalid payload or arguments (names the key); 3 a different
# create_board (or owner) is already there and --force was not passed; 4 no config (--show only).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../../lib/config.sh"

show=0
force=()
for arg in "$@"; do
  case "$arg" in
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
    --show) show=1 ;;
    --force) force=(--force) ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done
if [ "$show" -eq 1 ]; then
  [ "$#" -eq 1 ] || { echo "--show takes no other arguments" >&2; exit 2; }
  exec "$GB_PYTHON" "$GB_LIB_DIR/config.py" show
fi
exec "$GB_PYTHON" "$GB_LIB_DIR/config.py" init --require create_board ${force[@]+"${force[@]}"}
