#!/usr/bin/env bash
set -euo pipefail

# test-validate-plugin.sh — tests for scripts/validate-plugin.sh (#167).
#
# validate-plugin.sh runs validate-skill.sh on each skill. It used to take the
# exit code of the `sed` at the end of a pipe, so a skill that failed
# validation was reported as PASS. These cases pin the exit code and the text.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VALIDATOR="${VALIDATOR:-$REPO_ROOT/scripts/validate-plugin.sh}"
# validate-plugin.sh finds validate-skill.sh next to itself.
[[ -x "$(dirname "$VALIDATOR")/validate-skill.sh" ]] || { echo "FATAL: no validate-skill.sh next to $VALIDATOR" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

# new_plugin <name>: a plugin with a manifest and an empty skills/ directory.
new_plugin() {
  local d="$TMP/$1"
  mkdir -p "$d/.claude-plugin" "$d/skills"
  printf '{"name":"%s","version":"1.0.0","description":"fixture plugin"}\n' "$1" > "$d/.claude-plugin/plugin.json"
  printf '%s\n' "$d"
}

# add_skill <plugin-dir> <name> <good|bad>
add_skill() {
  local s="$1/skills/$2"
  mkdir -p "$s"
  if [[ "$3" == good ]]; then
    printf -- '---\nname: %s\ndescription: Does a thing. Use when: you need the thing.\nmetadata:\n  version: 1.0.0\n---\n\n# S\n' "$2" > "$s/SKILL.md"
  else
    # No "Use when:" and a non-standard top-level `version`: validate-skill.sh exits 1.
    printf -- '---\nname: %s\ndescription: Does a thing.\nversion: 1.0.0\n---\n\n# S\n' "$2" > "$s/SKILL.md"
  fi
}

run() { OUT="$("$VALIDATOR" "$1" 2>&1)" && RC=0 || RC=$?; }

echo "validate-plugin.sh skill handling"

P="$(new_plugin good)"; add_skill "$P" s good
run "$P"
[[ $RC -eq 0 ]] && ok "a plugin with a valid skill passes (rc 0)" || bad "a plugin with a valid skill passes (rc 0)" "rc=$RC: $OUT"

P="$(new_plugin bad)"; add_skill "$P" s bad
"$(dirname "$VALIDATOR")/validate-skill.sh" "$P/skills/s" >/dev/null 2>&1 && SRC=0 || SRC=$?
[[ $SRC -eq 1 ]] && ok "control: validate-skill.sh itself rejects the bad skill (rc 1)" || bad "control: validate-skill.sh itself rejects the bad skill (rc 1)" "rc=$SRC"
run "$P"
[[ $RC -eq 1 ]] && ok "a plugin whose skill fails validation exits 1" || bad "a plugin whose skill fails validation exits 1" "rc=$RC"
[[ "$OUT" == *"FAIL  skill s: fails validation"* ]] && ok "the FAIL line for the skill is printed" || bad "the FAIL line for the skill is printed" "$OUT"
[[ "$OUT" != *"PASS  skill s"* ]] && ok "no PASS line for the failing skill" || bad "no PASS line for the failing skill" "$OUT"

P="$(new_plugin mixed)"; add_skill "$P" a good; add_skill "$P" b bad
run "$P"
[[ $RC -eq 1 ]] && ok "one bad skill among good ones fails the plugin" || bad "one bad skill among good ones fails the plugin" "rc=$RC"

P="$(new_plugin empty)"
run "$P"
[[ $RC -eq 1 ]] && ok "a plugin whose skills/ holds no skill directory exits 1" || bad "a plugin whose skills/ holds no skill directory exits 1" "rc=$RC: $OUT"
[[ "$OUT" == *"FAIL  skills/ directory exists but contains no skill subdirectories"* ]] && ok "the zero-skill FAIL line is printed" || bad "the zero-skill FAIL line is printed" "$OUT"

P="$(new_plugin commandsonly)"; rmdir "$P/skills"; mkdir "$P/commands"
printf -- '---\ndescription: Does a thing\n---\n\nBody\n' > "$P/commands/c.md"
run "$P"
[[ $RC -eq 0 ]] && ok "a commands-only plugin (no skills/ directory) still passes" || bad "a commands-only plugin (no skills/ directory) still passes" "rc=$RC: $OUT"

echo ""
echo "copies of validate-plugin.sh"
for c in plugins/skill-kit/skills/publish/scripts/validate-plugin.sh plugins/skill-publishing/skills/skill-publishing/scripts/validate-plugin.sh; do
  cmp -s "$REPO_ROOT/scripts/validate-plugin.sh" "$REPO_ROOT/$c" && ok "$c is byte-identical to scripts/validate-plugin.sh" || bad "$c is byte-identical to scripts/validate-plugin.sh" "they differ"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
