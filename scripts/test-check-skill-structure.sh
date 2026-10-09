#!/usr/bin/env bash
set -euo pipefail

# test-check-skill-structure.sh — tests for scripts/check-skill-structure.py (#210).
#
# Each case builds a small repo under a temp dir with one clean skill, plants one
# violation and runs the checker; nothing here touches the live repo.
#
# Usage: bash scripts/test-check-skill-structure.sh   (CHECKER=<path> tests another copy)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKER="${CHECKER:-$REPO_ROOT/scripts/check-skill-structure.py}"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

[[ -f "$CHECKER" ]] || { echo "FATAL: check-skill-structure.py not found at $CHECKER" >&2; exit 1; }

# lines <n> [first-line]: n lines of text, the first one given.
lines() { printf '%s\n' "${2:-# Doc}"; local i; for ((i = 2; i <= $1; i++)); do printf 'line %d\n' "$i"; done; }

# fixture <dir>: one clean skill with a short and a long reference, both linked.
fixture() {
  local s="$1/plugins/kit/skills/pub"
  mkdir -p "$s/references" "$s/scripts"
  { printf -- '---\nname: pub\ndescription: d\n---\n'
    printf 'Read [references/short.md](references/short.md) and `${CLAUDE_SKILL_DIR}/references/long.md`.\n'
    lines 100 'body'; } > "$s/SKILL.md"
  lines 20 > "$s/references/short.md"
  { printf '# Long\n\n## Contents\n- One\n'; lines 150 '## One'; } > "$s/references/long.md"
  printf '# readme\n' > "$s/README.md"
  printf '# changelog\n' > "$s/CHANGELOG.md"
}
n=0
fresh() { n=$((n + 1)); R="$TMP/r$n"; S="$R/plugins/kit/skills/pub"; fixture "$R"; }
run() { OUT="$(python3 "$CHECKER" "$R" 2>&1)" && RC=0 || RC=$?; }
expect() { if [[ "$RC" == "$2" && "$OUT" == *"$3"* ]]; then ok "$1"; else bad "$1" "rc=$RC (want $2): $OUT"; fi; }
clean() { if [[ "$RC" == 0 && -z "$OUT" ]]; then ok "$1"; else bad "$1" "rc=$RC: $OUT"; fi; }

echo "1. clean fixture"
fresh; run; clean "a clean fixture exits 0 with no output"

echo "2. S1 body size"
fresh; lines 395 'more' >> "$S/SKILL.md"; run   # 1 + 100 + 395 = 496 body lines
clean "a 496-line body passes"
fresh; lines 399 'more' >> "$S/SKILL.md"; run   # 500 body lines
expect "a 500-line body fails" 1 "plugins/kit/skills/pub/SKILL.md: S1: body is 500 lines (must be under 500)"
fresh; printf 'no frontmatter\n' > "$S/SKILL.md"; lines 500 >> "$S/SKILL.md"; run
expect "a SKILL.md with no frontmatter counts every line" 1 "S1: body is 501 lines"

echo "3. S2 orphans"
fresh; lines 10 > "$S/references/orphan.md"; run
expect "an unlinked reference fails" 1 "plugins/kit/skills/pub/references/orphan.md: S2: not named in SKILL.md"
fresh; mkdir -p "$S/resources/deep"; lines 10 > "$S/resources/deep/x.md"; run
expect "an unlinked file in any subdirectory fails" 1 "resources/deep/x.md: S2"
fresh; lines 10 > "$S/references/orphan.md"; printf 'See ./references/orphan.md.\n' >> "$S/SKILL.md"; run
clean "a ./references/ path counts as a link"
fresh; lines 10 > "$S/references/orphan.md"; printf 'cat "$DIR/orphan.md"\n' > "$S/scripts/run.sh"; run
clean "a file a script reads counts as linked"
fresh; lines 10 > "$S/references/orphan.md"; printf 'See other/references/orphan.md.\n' >> "$S/SKILL.md"; run
expect "a longer path that only ends in the name does not count" 1 "references/orphan.md: S2"
fresh; lines 10 > "$S/references/readme-template.md"; printf 'cat "$DIR/monorepo-readme-template.md"\n' > "$S/scripts/run.sh"; run
expect "a script naming a longer file name does not count" 1 "references/readme-template.md: S2"
fresh; lines 10 > "$S/references/orphan.md"; printf 'See references/orphan.md.\n' >> "$S/SKILL.md"; run
clean "a name followed by punctuation still counts (references/orphan.md.)"
fresh; printf '# r\n' > "$S/references/README.md"; printf '# c\n' > "$S/references/CHANGELOG.md"; run
clean "README.md and CHANGELOG.md are never orphans"

echo "4. S3 contents lists"
fresh; lines 150 > "$S/references/short.md"; run
expect "a 150-line reference with no Contents fails" 1 "plugins/kit/skills/pub/references/short.md: S3: 150 lines with no '## Contents' heading"
fresh; lines 100 > "$S/references/short.md"; run
clean "a 100-line reference needs no Contents"
fresh; { lines 30; printf '## Contents\n'; lines 100; } > "$S/references/short.md"; run
expect "a Contents heading after line 30 fails" 1 "references/short.md: S3"
fresh; { printf '# T\n## Table of contents\n'; lines 120; } > "$S/references/short.md"; run
clean "## Table of contents is accepted"
fresh; { printf '# T\n### Contents\n'; lines 120; } > "$S/references/short.md"; run
expect "a ### Contents heading is not a level-2 heading and fails" 1 "references/short.md: S3"

echo "5. several violations, cannot run"
fresh; lines 10 > "$S/references/orphan.md"; lines 150 > "$S/references/short.md"; lines 499 >> "$S/SKILL.md"; run
expect "every violation is reported" 1 "S1: body"
[[ "$OUT" == *"orphan.md: S2"* && "$OUT" == *"short.md: S3"* ]] && ok "…S2 and S3 too" || bad "…S2 and S3 too" "$OUT"
[[ "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" == 3 ]] && ok "…one line each" || bad "…one line each" "$OUT"
n=$((n + 1)); R="$TMP/r$n"; mkdir -p "$R"; run
expect "a repo with no plugins/ exits 2" 2 "cannot run"
n=$((n + 1)); R="$TMP/r$n"; mkdir -p "$R/plugins/kit"; run
expect "a repo with no skills exits 2" 2 "no plugins/*/skills/*/SKILL.md"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
