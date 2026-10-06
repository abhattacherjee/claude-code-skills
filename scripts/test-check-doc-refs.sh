#!/usr/bin/env bash
set -euo pipefail

# test-check-doc-refs.sh — tests for scripts/check-doc-refs.py (#190).
#
# Each case builds a small repo under a temp dir; nothing here touches the live
# repo or the network.
#
# Usage: bash scripts/test-check-doc-refs.sh   (CHECKER=<path> tests another copy)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKER="${CHECKER:-$REPO_ROOT/scripts/check-doc-refs.py}"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

# fixture <dir>: a clean repo; each root doc holds one valid reference of each kind.
fixture() {
  local r="$1" d
  mkdir -p "$r/plugins/kit/.claude-plugin" "$r/plugins/kit/skills/publish/scripts" "$r/plugins/kit/agents" "$r/plugins/kit/commands" "$r/scripts" "$r/docs"
  printf '{"name":"kit","version":"1.0.0","description":"k"}\n' > "$r/plugins/kit/.claude-plugin/plugin.json"
  printf -- '---\nname: publish\n---\n' > "$r/plugins/kit/skills/publish/SKILL.md"
  : > "$r/plugins/kit/skills/publish/scripts/run.sh"
  printf '# helper\n' > "$r/plugins/kit/agents/helper.md"
  printf '# go\n' > "$r/plugins/kit/commands/go.md"
  printf '# kit\n\nRun `kit:publish`.\n' > "$r/plugins/kit/README.md"
  : > "$r/scripts/real.sh"
  printf '# x\n' > "$r/docs/x.md"
  for d in README.md CONTRIBUTING.md LOCAL-TESTING.md AGENTS.md CLAUDE.md; do
    printf '# %s\n\nSee [x](./docs/x.md), `scripts/real.sh`, `kit:publish`, `/kit:helper` and `kit:go`.\n' "$d" > "$r/$d"
  done
}

run() { OUT="$(python3 "$CHECKER" "$@" 2>&1)" && RC=0 || RC=$?; }

# with <label> <file> <line>: a fresh fixture with <line> appended to <file>, then run.
n=0
with() {
  n=$((n + 1)); R="$TMP/r$n"; fixture "$R"
  printf '%s\n' "$3" >> "$R/$2"
  run "$R"
}
# reported <label> <text...>: RC 1 and OUT holds every text.
reported() {
  local label="$1" t; shift
  [[ $RC -eq 1 ]] || { bad "$label" "rc=$RC, want 1: $OUT"; return 0; }
  for t in "$@"; do [[ "$OUT" == *"$t"* ]] || { bad "$label" "output lacks [$t]: $OUT"; return 0; }; done
  ok "$label"
}
clean() { [[ $RC -eq 0 && -z "$OUT" ]] && ok "$1" || bad "$1" "rc=$RC: $OUT"; }

[[ -f "$CHECKER" ]] || { echo "FATAL: check-doc-refs.py not found at $CHECKER" >&2; exit 1; }

echo "1. clean fixture"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; run "$R"
clean "a clean fixture exits 0 with no output"

echo "2. R1 links"
with x README.md 'A [gone](./docs/gone.md) link.'; reported "a broken relative link" "README.md:4: ./docs/gone.md: link target does not exist"
with x README.md '[ok](https://example.com) [a](#anchor) [m](mailto:a@b) [h](http://x.y)'; clean "web, anchor and mailto links are skipped"
with x README.md '[ok](./docs/x.md#part)'; clean "a link with an anchor checks only the file part"
with x plugins/kit/README.md '[up](../../docs/x.md) [also](../kit/README.md)'; clean "a link is resolved relative to its own file"
with x plugins/kit/README.md '[gone](./docs/x.md)'; reported "a link that only exists relative to the root is broken in a plugin README" "plugins/kit/README.md:4: ./docs/x.md"
with x README.md '[sp](./docs/my%20file.md)'; reported "a percent-encoded link is decoded" "./docs/my%20file.md"
printf '# m\n' > "$R/docs/my file.md"; run "$R"; clean "the decoded file exists, so it passes"
with x README.md 'Code `[not](./gone.md)` is not a link.'; clean "a link inside inline code is not checked"
with x README.md '[root](/docs/x.md)'; clean "a link starting with / resolves from the repo root"

echo "3. R2 repo paths"
with x README.md 'See `plugins/kit/skills/nope/`.'; reported "a missing repo path" "README.md:4: plugins/kit/skills/nope/: no such path"
with x README.md 'See `plugins/<group>/skills/<name>/`.'; clean "a <placeholder> path that matches one path passes"
with x README.md 'See `plugins/<group>/skills/zzz/`.'; reported "a <placeholder> path that matches nothing" "plugins/<group>/skills/zzz/: no such path"
with x README.md 'See `plugins/*/README.md`.'; clean "a * path that matches passes"
with x README.md 'See `./scripts/real.sh`.'; clean "a ./ path that exists passes"
with x README.md 'Run `scripts/real.sh --flag`.'; clean "a token with a space is skipped"
with x README.md 'See `scripts/real.sh:12`.'; clean "a :line suffix is not part of the path"
with x README.md 'See `docs/gone.md`, `.github/x.yml` and `.claude-plugin/m.json`.'; reported "each prefix is checked" "docs/gone.md: no such path" ".github/x.yml: no such path" ".claude-plugin/m.json: no such path"
with x README.md 'See `record.sh` and `src/app.py`.'; clean "bare names and other prefixes are not checked (stated blind spot)"

echo "4. R2 in a plugin README"
with x plugins/kit/README.md 'Runs `scripts/run.sh`.'; clean "a path that resolves in one of the plugin's skill dirs passes"
with x README.md 'Runs `scripts/run.sh`.'; reported "the same token in the root README is reported" "README.md:4: scripts/run.sh: no such path"
with x plugins/kit/README.md 'See `skills/publish/SKILL.md`.'; clean "a plugin-relative path that is not a checked prefix is skipped"

echo "5. R3 plugin:name"
with x README.md 'Use `kit:nothing`.'; reported "an unknown name in our plugin" "kit:nothing: kit has no skill, agent or command named nothing"
with x README.md 'Use `/kit:nothing`.'; reported "a /-prefixed unknown name" "/kit:nothing: kit has no skill"
with x README.md 'Use `git-flow:feature` and `pr-review-toolkit:code-reviewer`.'; clean "other plugins' prefixes are skipped"

echo "6. fenced blocks"
with x README.md "$(printf '```bash\n`scripts/gone.sh` [x](./gone.md) `kit:nope`\n```')"; clean "references inside a fenced block are skipped"
with x README.md "$(printf '```\nx\n```\n`scripts/gone.sh` [x](./gone.md)')"; reported "the same references after the fence closes are reported" "README.md:7: scripts/gone.sh: no such path" "README.md:7: ./gone.md: link target does not exist"
with x README.md "$(printf '~~~\n```\n`scripts/gone.sh`\n~~~\n`scripts/gone2.sh`')"; reported "a fence closes only on its own marker" "scripts/gone2.sh"
[[ "$OUT" != *"gone.sh:"* ]] && ok "and the text inside the ~~~ fence is not reported" || bad "and the text inside the ~~~ fence is not reported" "$OUT"
with x README.md "$(printf '````markdown\n```\n`scripts/gone.sh`\n```\n````\n`scripts/gone3.sh`')"; reported "a longer fence holds shorter ones" "scripts/gone3.sh"
[[ "$OUT" != *"gone.sh:"* ]] && ok "and the nested fence's text is not reported" || bad "and the nested fence's text is not reported" "$OUT"

echo "7. cannot run (exit 2)"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; rm "$R/LOCAL-TESTING.md"; run "$R"
[[ $RC -eq 2 && "$OUT" == *"LOCAL-TESTING.md: missing"* ]] && ok "a missing root doc" || bad "a missing root doc" "rc=$RC: $OUT"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; rm -rf "$R/plugins"; run "$R"
[[ $RC -eq 2 && "$OUT" == *"no plugins/ directory"* ]] && ok "no plugins/ directory" || bad "no plugins/ directory" "rc=$RC: $OUT"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; printf '\xff\xfe\n' >> "$R/plugins/kit/README.md"; run "$R"
[[ $RC -eq 2 && "$OUT" == *"plugins/kit/README.md"* ]] && ok "a doc that is not UTF-8" || bad "a doc that is not UTF-8" "rc=$RC: $OUT"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; chmod 000 "$R/plugins/kit"; run "$R"; chmod 755 "$R/plugins/kit"
[[ $RC -eq 2 ]] && ok "an unreadable plugin directory is exit 2, not 0 or 1" || bad "an unreadable plugin directory is exit 2, not 0 or 1" "rc=$RC: $OUT"
n=$((n + 1)); R="$TMP/r$n"; fixture "$R"; run "$R/nope"
[[ $RC -eq 2 ]] && ok "a repo path that does not exist" || bad "a repo path that does not exist" "rc=$RC: $OUT"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
