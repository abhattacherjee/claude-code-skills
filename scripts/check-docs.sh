#!/usr/bin/env bash
# check-docs.sh — the docs drift guard (#190).
#
# Runs three checks on this repo's working tree:
#   1. catalogue.py --check: the README plugin table, marketplace.json and each
#      plugin README's meta line match every plugin.json;
#   2. check-doc-refs.py: every link, repo path and plugin:skill name in the
#      current docs exists;
#   3. check-skill-structure.py: every plugin SKILL.md body is under 500 lines,
#      every reference file is linked from its SKILL.md, and every reference
#      over 100 lines has a Contents list (#210).
# All always run, so one run shows every problem. Exit 0 clean, 1 drift or a
# broken rule, 2 a check could not run (the worst of the three).
# commit-preflight.sh and the docs-drift CI job run this.
#
# Fix catalogue drift with:
#   python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .
set -uo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAT="$ROOT/plugins/skill-kit/skills/publish/scripts/catalogue.py"
REFS="$ROOT/scripts/check-doc-refs.py"
STRUCT="$ROOT/scripts/check-skill-structure.py"
for f in "$CAT" "$REFS" "$STRUCT"; do
  [[ -f "$f" ]] || { echo "check-docs.sh: $f is missing" >&2; exit 2; }
done

# run_check <name> <command...>: runs one checker, passes its output through,
# and returns its exit code. All checkers exit 0, 1 or 2 and write to stderr
# only with exit 2, so any other exit, or exit 1 with something on stderr (a
# Python crash: a syntax or import error also exits 1), means "could not run"
# (2), never drift (#190).
run_check() {
  local name="$1" err r=0
  shift
  err="$(mktemp)"
  "$@" 2>"$err" || r=$?
  cat "$err" >&2
  if (( r > 2 )); then
    echo "check-docs.sh: $name exited $r; treated as: could not run" >&2
    r=2
  elif (( r == 1 )) && [[ -s "$err" ]]; then
    echo "check-docs.sh: $name exited 1 with output on stderr (a crash); treated as: could not run" >&2
    r=2
  fi
  rm -f "$err"
  return "$r"
}

rc=0
r=0; run_check catalogue.py python3 "$CAT" --check "$ROOT" || r=$?
(( r > rc )) && rc=$r
r=0; run_check check-doc-refs.py python3 "$REFS" "$ROOT" || r=$?
(( r > rc )) && rc=$r
r=0; run_check check-skill-structure.py python3 "$STRUCT" "$ROOT" || r=$?
(( r > rc )) && rc=$r
if (( rc == 0 )); then
  echo "check-docs.sh: catalogue, doc references and skill structure are clean"
fi
exit "$rc"
