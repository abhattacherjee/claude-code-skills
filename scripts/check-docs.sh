#!/usr/bin/env bash
# check-docs.sh — the docs drift guard (#190).
#
# Runs two checks on this repo's working tree:
#   1. catalogue.py --check: the README plugin table, marketplace.json and each
#      plugin README's meta line match every plugin.json;
#   2. check-doc-refs.py: every link, repo path and plugin:skill name in the
#      current docs exists.
# Both always run, so one run shows every problem. Exit 0 clean, 1 drift or a
# broken reference, 2 a check could not run (the worst of the two).
# commit-preflight.sh and the docs-drift CI job run this.
#
# Fix catalogue drift with:
#   python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .
set -uo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAT="$ROOT/plugins/skill-kit/skills/publish/scripts/catalogue.py"
REFS="$ROOT/scripts/check-doc-refs.py"
for f in "$CAT" "$REFS"; do
  [[ -f "$f" ]] || { echo "check-docs.sh: $f is missing" >&2; exit 2; }
done

rc=0
r=0; python3 "$CAT" --check "$ROOT" || r=$?
(( r > rc )) && rc=$r
r=0; python3 "$REFS" "$ROOT" || r=$?
(( r > rc )) && rc=$r
# An exit above 2 (a crash, a signal, python3 missing) still means "could not run".
(( rc > 2 )) && rc=2
if (( rc == 0 )); then
  echo "check-docs.sh: catalogue and doc references are clean"
fi
exit "$rc"
