#!/usr/bin/env bash
# github-board shared helpers for bash scripts. Sourced, not run:
#   . "<plugin>/lib/config.sh"
# Every helper runs lib/config.py with $GB_PYTHON (default python3). GB_PYTHON is separate from
# the launchd scripts' $PYTHON, which tests replace with a stub.
#   gb_config_get KEY [--lines]   print a config value; exit 4 when there is no config, 2 when invalid
GB_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_PYTHON="${GB_PYTHON:-python3}"

gb_config_get() { "$GB_PYTHON" "$GB_LIB_DIR/config.py" get "$@"; }
