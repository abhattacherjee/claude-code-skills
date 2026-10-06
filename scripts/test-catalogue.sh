#!/usr/bin/env bash
set -euo pipefail

# test-catalogue.sh — tests for catalogue.py (#190).
#
# catalogue.py writes the plugin catalogue (root README table, marketplace.json,
# plugin README meta lines) from each plugin.json, and --check is the drift
# guard. Each case builds its own repo under a temp dir; nothing here touches
# the live repo or the network.
#
# Usage: bash scripts/test-catalogue.sh   (CAT=<path> tests another copy)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAT="${CAT:-$REPO_ROOT/plugins/skill-kit/skills/publish/scripts/catalogue.py}"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

# fixture <dir>: a clean two-plugin repo that catalogue.py --check accepts once written.
fixture() {
  local r="$1"
  mkdir -p "$r/.claude-plugin" "$r/scripts"
  : > "$r/scripts/install-plugin.sh"
  for p in alpha beta; do
    mkdir -p "$r/plugins/$p/.claude-plugin" "$r/plugins/$p/skills/$p-one" "$r/plugins/$p/agents"
    printf '{"name":"%s","version":"1.0.0","description":"The %s plugin — does things."}\n' "$p" "$p" > "$r/plugins/$p/.claude-plugin/plugin.json"
    printf -- '---\nname: %s-one\n---\n' "$p" > "$r/plugins/$p/skills/$p-one/SKILL.md"
    printf '# %s\n\n<!-- plugin-meta:start -->\n<!-- plugin-meta:end -->\n\nSkill `%s-one`.\n' "$p" "$p" > "$r/plugins/$p/README.md"
  done
  printf '# agent\n' > "$r/plugins/beta/agents/beta-helper.md"
  printf '%s\n' '# beta' '' '<!-- plugin-meta:start -->' '<!-- plugin-meta:end -->' '' 'Skill `beta-one`, agent `beta-helper`.' > "$r/plugins/beta/README.md"
  printf '# Repo\n\nIntro kept.\n\n<!-- catalogue:start -->\n<!-- catalogue:end -->\n\n/plugin install PLUGIN_NAME@demo-market\n\nTail kept.\n' > "$r/README.md"
  printf '{\n  "name": "demo-market",\n  "owner": {"name": "Tester"},\n  "metadata": {"description": "d", "version": "2026.01.01"},\n  "plugins": []\n}\n' > "$r/.claude-plugin/marketplace.json"
}

# written <dir>: a fixture that catalogue.py has written once (so it is clean).
written() { fixture "$1"; python3 "$CAT" "$1" >/dev/null 2>&1 || true; }

run() { OUT="$(python3 "$CAT" "$@" 2>&1)" && RC=0 || RC=$?; }

# expect <label> <rc> <text...>: RC must equal rc and OUT must contain every text.
expect() {
  local label="$1" want="$2" t
  shift 2
  if [[ "$RC" != "$want" ]]; then
    bad "$label" "rc=$RC, want $want: $OUT"
    return 0
  fi
  for t in "$@"; do
    if [[ "$OUT" != *"$t"* ]]; then
      bad "$label" "output lacks [$t]: $OUT"
      return 0
    fi
  done
  ok "$label"
}

# setjson <file> <python statement over d>: edit a JSON file in place.
setjson() {
  python3 - "$1" "$2" <<'PY'
import json, sys
f, stmt = sys.argv[1], sys.argv[2]
d = json.load(open(f, encoding="utf-8"))
exec(stmt)
open(f, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
PY
}

n=0
fresh() { n=$((n + 1)); R="$TMP/r$n"; }

[[ -f "$CAT" ]] || { echo "FATAL: catalogue.py not found at $CAT" >&2; exit 1; }

echo "1. write, check and idempotence"
fresh; fixture "$R"
run --check "$R"; expect "a fresh fixture with an empty table is drift (rc 1)" 1 "README.md: row alpha: missing"
run "$R"; expect "a write exits 0 and names each file it wrote" 0 "WROTE README.md" "WROTE .claude-plugin/marketplace.json" "WROTE plugins/alpha/README.md" "WROTE plugins/beta/README.md"
run --check "$R"; expect "check after a write is clean (rc 0)" 0
[[ -z "$OUT" ]] && ok "check after a write prints nothing" || bad "check after a write prints nothing" "$OUT"
run "$R"; expect "a second write exits 0" 0
[[ -z "$OUT" ]] && ok "a second write changes nothing (no output)" || bad "a second write changes nothing (no output)" "$OUT"

echo "2. the README table, and the text around it"
fresh; fixture "$R"; cp "$R/README.md" "$TMP/before.md"; run "$R"
grep -qxF '| [alpha](./plugins/alpha/) | 1.0.0 | 1 | 0 | The alpha plugin — does things. |' "$R/README.md" \
  && ok "the alpha row is written exactly" || bad "the alpha row is written exactly" "$(cat "$R/README.md")"
cmp -s <(sed -n '1,5p' "$TMP/before.md") <(sed -n '1,5p' "$R/README.md") \
  && ok "the lines before the start marker are byte-identical" || bad "the lines before the start marker are byte-identical"
cmp -s <(sed -n '/catalogue:end/,$p' "$TMP/before.md") <(sed -n '/catalogue:end/,$p' "$R/README.md") \
  && ok "the lines from the end marker on are byte-identical" || bad "the lines from the end marker on are byte-identical"

echo "3. marketplace.json"
if python3 - "$R/.claude-plugin/marketplace.json" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8").read()
d = json.loads(raw)
want = [{"name": p, "source": f"./plugins/{p}", "description": f"The {p} plugin — does things.", "version": "1.0.0"}
        for p in ("alpha", "beta")]
assert d["plugins"] == want, d["plugins"]
assert [list(e) for e in d["plugins"]] == [["name", "source", "description", "version"]] * 2
assert d["owner"] == {"name": "Tester"} and d["metadata"] == {"description": "d", "version": "2026.01.01"}
assert list(d) == ["name", "owner", "metadata", "plugins"]
assert "—" in raw and "\\u2014" not in raw
assert raw.endswith("}\n")
PY
then ok "plugins[] rebuilt in key order, other keys kept, em dash kept literal"; else bad "plugins[] rebuilt in key order, other keys kept, em dash kept literal" "$(cat "$R/.claude-plugin/marketplace.json")"; fi

echo "4. plugin README meta line"
grep -qxF '**Version:** 1.0.0 · **1** skill · **1** agent · **0** commands' "$R/plugins/beta/README.md" \
  && ok "beta's meta line is written" || bad "beta's meta line is written" "$(cat "$R/plugins/beta/README.md")"

echo "5. seeded drift (check exits 1 and names it)"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.0.1"'
run --check "$R"; expect "version bump" 1 "README.md: row alpha: version 1.0.0 != plugin.json 1.0.1" "marketplace.json: alpha: version" "plugins/alpha/README.md: meta line"
fresh; written "$R"; mkdir -p "$R/plugins/alpha/skills/alpha-two"; printf -- '---\nname: alpha-two\n---\n' > "$R/plugins/alpha/skills/alpha-two/SKILL.md"
run --check "$R"; expect "a new skill" 1 "README.md: row alpha: skills 1 != 2" "plugins/alpha/README.md: does not name skill alpha-two"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]="Changed."'
run --check "$R"; expect "a changed description" 1 "README.md: row alpha: description" "marketplace.json: alpha: description"
fresh; written "$R"; grep -v '^| \[alpha\]' "$R/README.md" > "$TMP/x" && cat "$TMP/x" > "$R/README.md"
run --check "$R"; expect "a deleted row" 1 "README.md: row alpha: missing"
fresh; written "$R"; perl -pi -e 'print "| [ghost](./plugins/ghost/) | 1.0.0 | 0 | 0 | x |\n" if /catalogue:end/' "$R/README.md"
run --check "$R"; expect "an extra row" 1 "README.md: row ghost: no such plugin"
fresh; written "$R"; setjson "$R/.claude-plugin/marketplace.json" 'd["plugins"][0]["source"]="./x"'
run --check "$R"; expect "a marketplace source edit" 1 "marketplace.json: alpha: source"
fresh; written "$R"; setjson "$R/.claude-plugin/marketplace.json" 'd["plugins"].append({"name":"ghost","source":"./plugins/ghost","description":"x","version":"1"})'
run --check "$R"; expect "an extra marketplace entry" 1 "marketplace.json: ghost: no such plugin"
fresh; written "$R"; perl -pi -e 's/, agent `beta-helper`//' "$R/plugins/beta/README.md"
run --check "$R"; expect "an agent not named in its README" 1 "plugins/beta/README.md: does not name agent beta-helper"
fresh; written "$R"; perl -pi -e 's/\@demo-market/\@other-market/' "$R/README.md"
run --check "$R"; expect "an install line with the wrong marketplace" 1 "README.md: /plugin install PLUGIN_NAME@other-market: marketplace is demo-market"
fresh; written "$R"; printf '/plugin uninstall nosuch@demo-market\n' >> "$R/README.md"
run --check "$R"; expect "an uninstall line for a plugin that does not exist" 1 "README.md: /plugin uninstall nosuch@demo-market: no plugin nosuch"
fresh; written "$R"; rm "$R/scripts/install-plugin.sh"; printf '/tmp/x/scripts/install-plugin.sh /tmp/x/plugins/PLUGIN_NAME\n' >> "$R/README.md"
run --check "$R"; expect "an install script that does not exist" 1 "scripts/install-plugin.sh: does not exist"
fresh; written "$R"; perl -pi -e 's/^\*\*Version:\*\* 1\.0\.0 /**Version:** 9.9.9 /' "$R/plugins/alpha/README.md"
run --check "$R"; expect "a hand-edited meta line" 1 "plugins/alpha/README.md: meta line differs"
fresh; written "$R"; perl -pi -e 's/ \| 1\.0\.0 \| 1 \| 0 \| The alpha/ |  1.0.0 | 1 | 0 | The alpha/' "$R/README.md"
run --check "$R"; expect "a row that parses but is not formatted as written" 1 "README.md: catalogue table formatting differs"
fresh; written "$R"; perl -0pi -e 's/\n  \]/\n]/' "$R/.claude-plugin/marketplace.json"
run --check "$R"; expect "marketplace.json not formatted as written" 1 "marketplace.json: formatting differs"
fresh; written "$R"; rm "$R/plugins/alpha/README.md"
run --check "$R"; expect "a missing plugin README" 1 "plugins/alpha/README.md: missing"
run "$R"; expect "a write cannot fix a missing plugin README (rc 1)" 1 "plugins/alpha/README.md: missing"

echo "5b. write mode fixes what it can and reports the rest"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="2.0.0"'
run "$R"; expect "a version bump is written (rc 0)" 0 "WROTE README.md" "WROTE .claude-plugin/marketplace.json" "WROTE plugins/alpha/README.md"
[[ "$OUT" != *"!="* && "$OUT" != *"differs"* ]] && ok "a write does not print the drift it fixed" || bad "a write does not print the drift it fixed" "$OUT"
run --check "$R"; expect "check after that write is clean" 0
fresh; written "$R"; mkdir -p "$R/plugins/alpha/skills/alpha-two"; printf -- '---\nname: alpha-two\n---\n' > "$R/plugins/alpha/skills/alpha-two/SKILL.md"
run "$R"; expect "a write with an unnamed skill writes the counts but exits 1" 1 "WROTE README.md" "plugins/alpha/README.md: does not name skill alpha-two"
[[ "$OUT" != *"skills 1 != 2"* ]] && ok "the count drift it fixed is not reported" || bad "the count drift it fixed is not reported" "$OUT"
fresh; written "$R"; perl -pi -e 's/\@demo-market/\@other-market/' "$R/README.md"
run "$R"; expect "a write with a bad install line exits 1" 1 "marketplace is demo-market"

echo "6. fail closed (exit 2)"
fresh; written "$R"; perl -ni -e 'print unless /catalogue:end/' "$R/README.md"
run --check "$R"; expect "no end marker" 2 "README.md: needs exactly one <!-- catalogue:end -->"
fresh; written "$R"; perl -pi -e 'print "<!-- catalogue:start -->\n" if /catalogue:start/' "$R/README.md"
run --check "$R"; expect "a repeated start marker" 2 "needs exactly one <!-- catalogue:start -->"
fresh; written "$R"; perl -0pi -e 's/(<!-- catalogue:start -->)(.*)(<!-- catalogue:end -->)/$3$2$1/s' "$R/README.md"
run --check "$R"; expect "markers in the wrong order" 2 "comes before"
fresh; written "$R"; printf '{' > "$R/plugins/alpha/.claude-plugin/plugin.json"
run --check "$R"; expect "invalid plugin.json" 2 "plugins/alpha/.claude-plugin/plugin.json:" "Expecting"
fresh; written "$R"; printf '[]' > "$R/plugins/alpha/.claude-plugin/plugin.json"
run --check "$R"; expect "plugin.json that is not an object" 2 "not a JSON object"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'del d["version"]'
run --check "$R"; expect "plugin.json without a version" 2 "'version' missing or empty"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["name"]="alpha2"'
run --check "$R"; expect "a name that is not the directory name" 2 "name alpha2 does not match directory alpha"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]="a | b"'
run --check "$R"; expect "a description with a pipe" 2 "description contains '|' or a newline"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]="a\nb"'
run --check "$R"; expect "a description with a newline" 2 "description contains '|' or a newline"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]=" a "'
run --check "$R"; expect "a description with spaces around it" 2 "spaces before or after"
fresh; written "$R"; mkdir "$R/plugins/stray"
run --check "$R"; expect "a stray plugins/ directory" 2 "plugins/stray/.claude-plugin/plugin.json: missing"
run "$R"; expect "a stray plugins/ directory also stops a write" 2 "plugins/stray/.claude-plugin/plugin.json: missing"
fresh; written "$R"; rm -rf "$R/plugins"
run --check "$R"; expect "no plugins/ directory" 2 "no plugins/ directory"
fresh; written "$R"; printf '\xff\xfe' >> "$R/plugins/alpha/README.md"
run --check "$R"; expect "a plugin README that is not UTF-8" 2 "plugins/alpha/README.md"
fresh; written "$R"; chmod 000 "$R/plugins"
run --check "$R"; chmod 755 "$R/plugins"; expect "an unreadable plugins/ directory (an unexpected error) is exit 2, not drift" 2 "PermissionError"
fresh; written "$R"; printf '{' > "$R/.claude-plugin/marketplace.json"
run --check "$R"; expect "invalid marketplace.json" 2 "marketplace.json"
fresh; written "$R"; perl -ni -e 'print unless /plugin-meta:end/' "$R/plugins/alpha/README.md"
run --check "$R"; expect "a plugin README with a start marker and no end marker" 2 "plugins/alpha/README.md: needs exactly one <!-- plugin-meta:end -->"
fresh; written "$R"; cp -R "$R" "$TMP/snap"; printf '{' > "$R/plugins/beta/.claude-plugin/plugin.json"; cp "$R/plugins/beta/.claude-plugin/plugin.json" "$TMP/snap/plugins/beta/.claude-plugin/plugin.json"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="3.0.0"'; cp "$R/plugins/alpha/.claude-plugin/plugin.json" "$TMP/snap/plugins/alpha/.claude-plugin/plugin.json"
run "$R"; expect "a write with one bad plugin.json exits 2" 2 "plugins/beta/.claude-plugin/plugin.json"
diff -r "$TMP/snap" "$R" >/dev/null && ok "and writes nothing at all" || bad "and writes nothing at all" "$(diff -r "$TMP/snap" "$R")"
rm -rf "$TMP/snap"

echo "6a. symlinks and bad versions (exit 2, nothing written)"
OUTSIDE="$TMP/outside"; mkdir -p "$OUTSIDE"
# refused <label> <text>: rc 2 naming <text>, and the outside file is byte-identical.
refused() {
  [[ $RC -eq 2 && "$OUT" == *"$2"* ]] || { bad "$1" "rc=$RC: $OUT"; return 0; }
  cmp -s "$OUTSIDE/target.md" "$OUTSIDE/target.orig" || { bad "$1" "the outside file changed: $(cat "$OUTSIDE/target.md")"; return 0; }
  ok "$1"
}
fresh; written "$R"; mv "$R/README.md" "$OUTSIDE/target.md"; cp "$OUTSIDE/target.md" "$OUTSIDE/target.orig"; ln -s "$OUTSIDE/target.md" "$R/README.md"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="4.0.0"'
run "$R"; refused "a symlinked root README is refused and its target is untouched" "README.md: is a symlink"
fresh; written "$R"; mv "$R/plugins/alpha/README.md" "$OUTSIDE/target.md"; cp "$OUTSIDE/target.md" "$OUTSIDE/target.orig"; ln -s "$OUTSIDE/target.md" "$R/plugins/alpha/README.md"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="4.0.0"'
run "$R"; refused "a plugin README symlinked outside the repo is refused and its target is untouched" "plugins/alpha/README.md: is a symlink"
[[ "$(grep -c '4.0.0' "$R/README.md" || true)" == 0 ]] && ok "and the root README was not written either" || bad "and the root README was not written either"
fresh; written "$R"; mv "$R/plugins/alpha" "$OUTSIDE/alpha"; ln -s "$OUTSIDE/alpha" "$R/plugins/alpha"
cp "$OUTSIDE/alpha/README.md" "$OUTSIDE/target.md"; cp "$OUTSIDE/alpha/README.md" "$OUTSIDE/target.orig"
setjson "$OUTSIDE/alpha/.claude-plugin/plugin.json" 'd["version"]="4.0.0"'; cp "$OUTSIDE/alpha/README.md" "$TMP/alpha.orig"
run "$R"; refused "a symlinked plugin directory is refused" "plugins/alpha: is a symlink"
cmp -s "$OUTSIDE/alpha/README.md" "$TMP/alpha.orig" && ok "and the README behind the link is untouched" || bad "and the README behind the link is untouched"
fresh; written "$R"; mv "$R/.claude-plugin/marketplace.json" "$OUTSIDE/target.md"; cp "$OUTSIDE/target.md" "$OUTSIDE/target.orig"; ln -s "$OUTSIDE/target.md" "$R/.claude-plugin/marketplace.json"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="4.0.0"'
run "$R"; refused "a symlinked marketplace.json is refused and its target is untouched" ".claude-plugin/marketplace.json: is a symlink"
fresh; written "$R"; mv "$R/.claude-plugin" "$OUTSIDE/cp"; ln -s "$OUTSIDE/cp" "$R/.claude-plugin"; cp "$OUTSIDE/cp/marketplace.json" "$OUTSIDE/target.md"; cp "$OUTSIDE/target.md" "$OUTSIDE/target.orig"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="4.0.0"'
run "$R"; refused "a marketplace.json reached through a symlinked .claude-plugin/ is refused" "is outside the repo"
cmp -s "$OUTSIDE/cp/marketplace.json" "$OUTSIDE/target.orig" && ok "and the marketplace.json behind the link is untouched" || bad "and the marketplace.json behind the link is untouched"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.0|x"'
run "$R"; expect "a version that is not X.Y.Z is refused, naming the plugin" 2 "plugins/alpha/.claude-plugin/plugin.json: version '1.0|x' is not"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.0"'
run --check "$R"; expect "a two-part version is refused" 2 "version '1.0' is not"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.2.3-rc.1+b5"'
run "$R"; expect "a pre-release version with build metadata is accepted" 0 "WROTE README.md"

mkdir -p "$TMP/lonecat"; cp "$CAT" "$TMP/lonecat/catalogue.py"
fresh; written "$R"; OUT="$(python3 "$TMP/lonecat/catalogue.py" --check "$R" 2>&1)" && RC=0 || RC=$?
expect "no standalone-plugins.txt next to catalogue.py is exit 2, not an empty skip list" 2 "standalone-plugins.txt"

echo "6b. a plugin README with no meta markers"
fresh; written "$R"; perl -ni -e 'print unless /plugin-meta:/ || /^\*\*Version:\*\*/' "$R/plugins/alpha/README.md"
run --check "$R"; expect "check reports a missing meta line (rc 1)" 1 "plugins/alpha/README.md: no meta line"
run "$R"; expect "a write inserts the meta block (rc 0)" 0 "WROTE plugins/alpha/README.md"
[[ "$(sed -n '1,5p' "$R/plugins/alpha/README.md")" == "$(printf '# alpha\n\n<!-- plugin-meta:start -->\n**Version:** 1.0.0 · **1** skill · **0** agents · **0** commands\n<!-- plugin-meta:end -->')" ]] \
  && ok "the block sits right after the first # heading" || bad "the block sits right after the first # heading" "$(cat "$R/plugins/alpha/README.md")"
run --check "$R"; expect "check after the insert is clean" 0

echo "7. standalone plugins are skipped"
fresh; written "$R"; mkdir -p "$R/plugins/git-flow/skills/x"
run --check "$R"; expect "plugins/git-flow with no plugin.json is not reported" 0
printf '/plugin install git-flow@git-flow-repo\n' >> "$R/README.md"
run --check "$R"; expect "a standalone install line from its own marketplace is accepted" 0

echo "8. CRLF line endings are kept"
fresh; written "$R"; perl -pi -e 's/\n/\r\n/' "$R/README.md"
before_cr="$(grep -c $'\r$' "$R/README.md" || true)"; before_all="$(wc -l < "$R/README.md" | tr -d ' ')"
sed -n '1,/catalogue:start/p' "$R/README.md" > "$TMP/head.crlf"; sed -n '/catalogue:end/,$p' "$R/README.md" > "$TMP/tail.crlf"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.2.3"'
run "$R"; expect "a write on a CRLF README exits 0" 0 "WROTE README.md"
after_cr="$(grep -c $'\r$' "$R/README.md" || true)"
[[ "$before_cr" == "$before_all" && "$after_cr" == "$before_cr" ]] && ok "every line still ends in CRLF ($after_cr of $before_all)" || bad "every line still ends in CRLF" "before=$before_cr/$before_all after=$after_cr"
cmp -s "$TMP/head.crlf" <(sed -n '1,/catalogue:start/p' "$R/README.md") && cmp -s "$TMP/tail.crlf" <(sed -n '/catalogue:end/,$p' "$R/README.md") \
  && ok "the text outside the markers is byte-identical" || bad "the text outside the markers is byte-identical"
grep -qF '| 1.2.3 |' "$R/README.md" && ok "the new version is in the CRLF table" || bad "the new version is in the CRLF table"
run --check "$R"; expect "check on the written CRLF README is clean" 0

echo "9. marketplace.json missing"
fresh; written "$R"; rm "$R/.claude-plugin/marketplace.json"
run "$R"; expect "a write without --marketplace-name/--owner exits 2" 2 "marketplace.json is missing; pass --marketplace-name and --owner"
[[ ! -e "$R/.claude-plugin/marketplace.json" ]] && ok "and creates nothing" || bad "and creates nothing"
run --marketplace-name demo-market --owner o "$R"; expect "a write with both creates it (rc 0)" 0 "WROTE .claude-plugin/marketplace.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["name"]=="demo-market" and d["owner"]=={"name":"o"} and len(d["plugins"])==2' "$R/.claude-plugin/marketplace.json" \
  && ok "the new marketplace.json has the name, owner and both plugins" || bad "the new marketplace.json has the name, owner and both plugins" "$(cat "$R/.claude-plugin/marketplace.json")"

echo "10. --json"
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="1.0.1"'
run --check --json "$R"
[[ $RC -eq 1 ]] && printf '%s' "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["drift"] and d["errors"]==[] and d["written"]==[]' \
  && ok "--check --json on drift: rc 1, drift listed, no errors" || bad "--check --json on drift: rc 1, drift listed, no errors" "rc=$RC $OUT"
rm -rf "$R/plugins"; run --check --json "$R"
[[ $RC -eq 2 ]] && printf '%s' "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["errors"] and d["drift"]==[]' \
  && ok "--check --json when it cannot run: rc 2, error listed" || bad "--check --json when it cannot run: rc 2, error listed" "rc=$RC $OUT"

echo "11. quotes and backslashes give valid JSON"
fresh; fixture "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]="Say \"hi\" to C:\\path."'
run "$R"; expect "a description with quote and backslash is written" 0
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["plugins"][0]["description"]=="Say \"hi\" to C:\\path."' "$R/.claude-plugin/marketplace.json" \
  && ok "marketplace.json round-trips it" || bad "marketplace.json round-trips it" "$(cat "$R/.claude-plugin/marketplace.json")"
run --check "$R"; expect "and check is clean" 0

echo "12. commands are counted (T2)"
fresh; fixture "$R"; mkdir -p "$R/plugins/beta/commands"; printf '# go\n' > "$R/plugins/beta/commands/go.md"
run "$R"; expect "a write with a command exits 0" 0
grep -qxF '| [beta](./plugins/beta/) | 1.0.0 | 1 | 1 | The beta plugin — does things. |' "$R/README.md" \
  && ok "the row counts the command" || bad "the row counts the command" "$(grep beta "$R/README.md")"
grep -qF '**1** command' "$R/plugins/beta/README.md" && ok "the meta line says **1** command" || bad "the meta line says **1** command" "$(cat "$R/plugins/beta/README.md")"

echo "13. install lines (T7)"
fresh; written "$R"; printf '/plugin install git-flow@wrong-market\n' >> "$R/README.md"
run --check "$R"; expect "a standalone plugin installed from the wrong marketplace is drift" 1 "README.md: /plugin install git-flow@wrong-market"

echo "14. writes are all or nothing (F4)"
fresh; written "$R"; cp "$R/README.md" "$TMP/readme.before"; cp "$R/.claude-plugin/marketplace.json" "$TMP/market.before"
setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["version"]="5.0.0"'
chmod 444 "$R/plugins/beta/README.md"; chmod 555 "$R/plugins/beta"
setjson "$R/plugins/beta/.claude-plugin/plugin.json" 'd["version"]="5.0.0"' 2>/dev/null || true
run "$R"; chmod 755 "$R/plugins/beta"; chmod 644 "$R/plugins/beta/README.md"
expect "a write that cannot write one file exits 2" 2 "nothing was written"
cmp -s "$TMP/readme.before" "$R/README.md" && cmp -s "$TMP/market.before" "$R/.claude-plugin/marketplace.json" \
  && ok "and leaves every other file as it was" || bad "and leaves every other file as it was" "$(diff "$TMP/readme.before" "$R/README.md")"
[[ -z "$(find "$R" -name '.catalogue-*')" ]] && ok "and leaves no temp file behind" || bad "and leaves no temp file behind" "$(find "$R" -name '.catalogue-*')"

echo "15. unreadable skills/, agents/, commands/ (F5)"
for sub in skills agents; do
  fresh; written "$R"; chmod 000 "$R/plugins/beta/$sub"
  run --check "$R"; chmod 755 "$R/plugins/beta/$sub"
  expect "an unreadable $sub/ directory is exit 2, not a count of 0" 2 "plugins/beta/$sub"
done
fresh; written "$R"; mkdir -p "$R/plugins/beta/commands"; chmod 000 "$R/plugins/beta/commands"
run --check "$R"; chmod 755 "$R/plugins/beta/commands"
expect "an unreadable commands/ directory is exit 2" 2 "plugins/beta/commands"
fresh; written "$R"; chmod 000 "$R/plugins/beta/skills/beta-one"
run --check "$R"; chmod 755 "$R/plugins/beta/skills/beta-one"
expect "an unreadable skill directory is exit 2" 2 "plugins/beta/skills/beta-one"

echo "16. names and descriptions that would break the markers (F7)"
for bad_desc in 'has <!-- in it' 'has --> in it' 'x <!-- catalogue:end --> y' 'x <!-- plugin-meta:start --> y'; do
  fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" "d['description']='$bad_desc'"
  run "$R"; expect "a description [$bad_desc] is refused" 2 "plugins/alpha/.claude-plugin/plugin.json: description contains an HTML comment marker"
done
fresh; written "$R"; mv "$R/plugins/alpha" "$R/plugins/Alpha"; setjson "$R/plugins/Alpha/.claude-plugin/plugin.json" 'd["name"]="Alpha"'
run --check "$R"; expect "a plugin name with a capital letter is refused" 2 "name 'Alpha' is not lower-case letters, digits and hyphens"
fresh; written "$R"; mv "$R/plugins/alpha" "$R/plugins/al_pha"; setjson "$R/plugins/al_pha/.claude-plugin/plugin.json" 'd["name"]="al_pha"'
run --check "$R"; expect "a plugin name with an underscore is refused" 2 "name 'al_pha' is not"

echo "17. check reports every change a write would make (F8)"
fresh; written "$R"; perl -pi -e 's/^(\*\*Version:\*\*.*)$/$1  /' "$R/plugins/alpha/README.md"
run --check "$R"; expect "trailing spaces on the meta line are drift" 1 "plugins/alpha/README.md: meta line differs"
fresh; written "$R"; perl -0pi -e 's/(<!-- plugin-meta:start -->)\n/$1\n\n/' "$R/plugins/alpha/README.md"
run --check "$R"; expect "a blank line inside the meta block is drift" 1 "plugins/alpha/README.md"
run "$R"; run --check "$R"; expect "and a write makes it clean" 0
fresh; written "$R"; printf '%s\n' '```bash' '# not a heading' '```' '' '# alpha' '' 'Skill `alpha-one`.' > "$R/plugins/alpha/README.md"
run "$R"; expect "a write inserts the meta block into a README that opens with a fence" 0
[[ "$(sed -n '5,8p' "$R/plugins/alpha/README.md")" == "$(printf '# alpha\n\n<!-- plugin-meta:start -->\n**Version:** 1.0.0 · **1** skill · **0** agents · **0** commands')" ]] \
  && ok "the block goes after the real heading, not a # line in a fence" || bad "the block goes after the real heading, not a # line in a fence" "$(cat "$R/plugins/alpha/README.md")"

echo "18. a README names a skill or agent only as code, plugin:name or /name (F9)"
# name_ok <label> <README line> <0|1>: beta's README has only that naming line.
name_case() {
  fresh; written "$R"
  printf '%s\n' '# beta' '' '<!-- plugin-meta:start -->' '**Version:** 1.0.0 · **1** skill · **1** agent · **0** commands' '<!-- plugin-meta:end -->' '' 'Skill `beta-one`.' "$2" > "$R/plugins/beta/README.md"
  run --check "$R"
  if [[ "$3" == 0 ]]; then expect "$1" 0; else expect "$1" 1 "plugins/beta/README.md: does not name agent beta-helper"; fi
}
name_case "inline code names it" 'Agent `beta-helper`.' 0
name_case "plugin:name names it" 'Agent beta:beta-helper.' 0
name_case "/name names it" 'Run /beta-helper.' 0
name_case "a plain word does not" 'Agent beta-helper does things.' 1
name_case "a longer name does not (beta-helpers)" 'Agent `beta-helpers`.' 1
name_case "a prefixed name does not (xbeta-helper)" 'Agent `xbeta-helper`.' 1
name_case "a path segment does not" 'See agents/beta-helper.md.' 1
fresh; written "$R"; mkdir -p "$R/plugins/beta/skills/install"; printf -- '---\nname: install\n---\n' > "$R/plugins/beta/skills/install/SKILL.md"
printf '\nRun /plugin install beta@demo-market.\n' >> "$R/plugins/beta/README.md"
run --check "$R"; expect "'/plugin install' does not name a skill called install" 1 "plugins/beta/README.md: does not name skill install"

echo "19. --validate-plugins (F3)"
fresh; written "$R"; perl -ni -e 'print unless /catalogue:/' "$R/README.md"
run --validate-plugins "$R"; expect "--validate-plugins passes without README markers" 0
fresh; written "$R"; setjson "$R/plugins/alpha/.claude-plugin/plugin.json" 'd["description"]="a | b"'
cp -R "$R" "$TMP/vp-snap"
run --validate-plugins "$R"; expect "--validate-plugins refuses a bad plugin.json" 2 "description contains '|'"
diff -r "$TMP/vp-snap" "$R" >/dev/null && ok "and writes nothing" || bad "and writes nothing"
fresh; written "$R"; mv "$R/plugins/alpha/README.md" "$TMP/alpha-readme.md"; ln -s "$TMP/alpha-readme.md" "$R/plugins/alpha/README.md"
run --validate-plugins "$R"; expect "--validate-plugins refuses a symlinked plugin README" 2 "is a symlink"
fresh; written "$R"
run --check --validate-plugins "$R"; expect "--check and --validate-plugins together is a usage error" 2 "not allowed with"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
