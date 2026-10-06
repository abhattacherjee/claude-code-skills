#!/usr/bin/env bash
set -euo pipefail

# test-check-docs.sh — tests for scripts/check-docs.sh, the docs drift guard (#190).
#
# Each case copies check-docs.sh and its two checkers into a small fixture repo
# under a temp dir, so nothing here touches the live repo or the network.
#
# Usage: bash scripts/test-check-docs.sh   (CHECK_DOCS=<path> tests another copy)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_DOCS="${CHECK_DOCS:-$REPO_ROOT/scripts/check-docs.sh}"
CAT_SRC="$REPO_ROOT/plugins/skill-kit/skills/publish/scripts"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

[[ -f "$CHECK_DOCS" ]] || { echo "FATAL: check-docs.sh not found at $CHECK_DOCS" >&2; exit 1; }

# fixture <dir>: a clean repo with one plugin (skill-kit, which holds catalogue.py).
fixture() {
  local r="$1" p="$1/plugins/skill-kit"
  mkdir -p "$r/scripts" "$r/.claude-plugin" "$p/.claude-plugin" "$p/skills/publish/scripts"
  cp "$CHECK_DOCS" "$r/scripts/check-docs.sh"
  cp "$REPO_ROOT/scripts/check-doc-refs.py" "$r/scripts/check-doc-refs.py"
  cp "$CAT_SRC/catalogue.py" "$CAT_SRC/standalone-plugins.txt" "$p/skills/publish/scripts/"
  printf '{"name":"skill-kit","version":"1.0.0","description":"Fixture."}\n' > "$p/.claude-plugin/plugin.json"
  printf -- '---\nname: publish\n---\n' > "$p/skills/publish/SKILL.md"
  printf '# skill-kit\n\nSkill `publish`.\n' > "$p/README.md"
  printf '# Repo\n\n<!-- catalogue:start -->\n<!-- catalogue:end -->\n' > "$r/README.md"
  printf '{"name": "m", "owner": {"name": "o"}, "plugins": []}\n' > "$r/.claude-plugin/marketplace.json"
  for d in CONTRIBUTING.md LOCAL-TESTING.md AGENTS.md CLAUDE.md; do printf '# %s\n' "$d" > "$r/$d"; done
  python3 "$p/skills/publish/scripts/catalogue.py" "$r" >/dev/null
}
n=0
fresh() { n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; }
run() { OUT="$(bash "$R/scripts/check-docs.sh" 2>&1)" && RC=0 || RC=$?; }
expect() { if [[ "$RC" == "$2" && "$OUT" == *"$3"* ]]; then ok "$1"; else bad "$1" "rc=$RC (want $2): $OUT"; fi; }

fresh; run; expect "a clean fixture exits 0" 0 "catalogue and doc references are clean"
fresh; sed -i.bak 's/"1.0.0"/"1.0.1"/' "$R/plugins/skill-kit/.claude-plugin/plugin.json"; run
expect "seeded catalogue drift exits 1" 1 "README.md: row skill-kit: version 1.0.0 != plugin.json 1.0.1"
fresh; printf '\nSee `scripts/gone.sh`.\n' >> "$R/AGENTS.md"; run
expect "a broken doc reference exits 1" 1 "AGENTS.md:3: scripts/gone.sh: no such path"
fresh; sed -i.bak 's/"1.0.0"/"1.0.1"/' "$R/plugins/skill-kit/.claude-plugin/plugin.json"; printf '\nSee `scripts/gone.sh`.\n' >> "$R/AGENTS.md"; run
expect "with both, both checks run and both are reported" 1 "scripts/gone.sh: no such path"
[[ "$OUT" == *"row skill-kit"* ]] && ok "…the catalogue line too" || bad "…the catalogue line too" "$OUT"
fresh; rm "$R/plugins/skill-kit/skills/publish/scripts/catalogue.py"; run
expect "catalogue.py removed exits 2" 2 "catalogue.py is missing"
fresh; rm "$R/scripts/check-doc-refs.py"; run
expect "check-doc-refs.py removed exits 2" 2 "check-doc-refs.py is missing"
fresh; printf 'import no_such_module_for_190\n' > "$R/scripts/check-doc-refs.py"; run
expect "a checker that crashes (exit 1 with a traceback) exits 2, not 1" 2 "treated as: could not run"
fresh; printf 'def (\n' > "$R/plugins/skill-kit/skills/publish/scripts/catalogue.py"; run
expect "a catalogue.py with a syntax error exits 2" 2 "treated as: could not run"
fresh; printf 'import sys\nsys.exit(5)\n' > "$R/scripts/check-doc-refs.py"; run
expect "a checker that exits 5 exits 2" 2 "exited 5"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
