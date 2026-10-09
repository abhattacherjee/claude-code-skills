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
fresh; lines 10 > "$S/references/orphan.md"; printf 'See references/orphan.md.bak instead.\n' >> "$S/SKILL.md"; run
expect "references/orphan.md.bak does not name references/orphan.md" 1 "references/orphan.md: S2"
fresh; lines 10 > "$S/references/orphan.md"; printf 'See other/./references/orphan.md.\n' >> "$S/SKILL.md"; run
expect "other/./references/orphan.md does not name references/orphan.md" 1 "references/orphan.md: S2"
fresh; lines 10 > "$S/references/orphan.md"; printf 'cat "$DIR/orphan.md.bak"\n' > "$S/scripts/run.sh"; run
expect "a script reading orphan.md.bak does not read orphan.md" 1 "references/orphan.md: S2"
fresh; printf '# r\n' > "$S/references/README.md"; printf '# c\n' > "$S/references/CHANGELOG.md"; run
clean "README.md and CHANGELOG.md are never orphans"
fresh; printf '# c\n' > "$S/CONTRIBUTING.md"; mkdir -p "$S/.github"; lines 150 > "$S/.github/PULL_REQUEST_TEMPLATE.md"; run
clean "CONTRIBUTING.md and files under a dot-directory are not checked (skill repos carry them)"

echo "4. S3 contents lists"
fresh; lines 150 > "$S/references/short.md"; run
expect "a 150-line reference with no Contents fails" 1 "plugins/kit/skills/pub/references/short.md: S3: 150 lines with no '## Contents' heading"
fresh; lines 100 > "$S/references/short.md"; run
clean "a 100-line reference needs no Contents"
fresh; { lines 30; printf '## Contents\n'; lines 100; } > "$S/references/short.md"; run
expect "a Contents heading after line 30 fails" 1 "references/short.md: S3"
fresh; { printf '# T\n## Table of contents\n'; lines 120; } > "$S/references/short.md"; run
clean "## Table of contents is accepted"
fresh; { printf '# T\n```markdown\n## Contents\n```\n'; lines 120; } > "$S/references/short.md"; run
expect "a ## Contents heading inside a code fence does not count" 1 "references/short.md: S3"
fresh; { printf '# T\n~~~\n## Contents\n~~~\n## Contents\n'; lines 120; } > "$S/references/short.md"; run
clean "a real ## Contents heading after a fenced one counts"
fresh; { printf '# T\n```inline``` is not a fence\n## Contents\n'; lines 120; } > "$S/references/short.md"; run
clean "a line like \`\`\`inline\`\`\` (backtick in the info string) is not a fence"
fresh; { printf '# T\n### Contents\n'; lines 120; } > "$S/references/short.md"; run
expect "a ### Contents heading is not a level-2 heading and fails" 1 "references/short.md: S3"
fresh; lines 150 | tr '\n' '\r' > "$S/references/short.md"; run
clean "a lone CR does not end a line (a line ends in \\n, as validate-skill.sh counts it)"
fresh; lines 99 > "$S/references/short.md"; printf 'a\x0bb\x0cc\xe2\x80\xa8d\n' >> "$S/references/short.md"; run
clean "nor do VT, FF or U+2028 (100 lines)"

echo "5. several violations, cannot run"
fresh; lines 10 > "$S/references/orphan.md"; lines 150 > "$S/references/short.md"; lines 499 >> "$S/SKILL.md"; run
expect "every violation is reported" 1 "S1: body"
[[ "$OUT" == *"orphan.md: S2"* && "$OUT" == *"short.md: S3"* ]] && ok "…S2 and S3 too" || bad "…S2 and S3 too" "$OUT"
[[ "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" == 3 ]] && ok "…one line each" || bad "…one line each" "$OUT"
n=$((n + 1)); R="$TMP/r$n"; mkdir -p "$R"; run
expect "a repo with no plugins/ exits 2" 2 "cannot run"
n=$((n + 1)); R="$TMP/r$n"; mkdir -p "$R/plugins/kit"; run
expect "a repo with no skills exits 2" 2 "no plugins/*/skills/*/SKILL.md"

echo "6. parity with validate-skill.sh (#214)"
# Both scripts run on one fixture set. For each skill, the S1/S2/S3 failures each
# reports (with the line counts) must be the same; any other FAIL from the validator
# shows up as a difference too, so a fixture that breaks another rule cannot hide.
# Not covered: a SKILL.md saved with CRLF. validate-skill.sh fails its frontmatter
# check (fail-closed); the Python checker has no frontmatter rule.
VALIDATOR="${VALIDATOR:-$REPO_ROOT/scripts/validate-skill.sh}"
[[ -f "$VALIDATOR" ]] || { echo "FATAL: validate-skill.sh not found at $VALIDATOR" >&2; exit 1; }
P="$TMP/parity"
# pskill <id> <body-lines>: a skill that passes every other validate-skill.sh rule;
# SKILL.md names references/short.md. Sets PS to its directory.
pskill() {
  PS="$P/plugins/kit/skills/$1"; mkdir -p "$PS/references" "$PS/scripts"
  { printf -- '---\nname: %s\ndescription: "Fixture. Use when: (1) testing."\nmetadata:\n  version: 1.0.0\n---\n' "$1"
    printf 'Read references/short.md.\n'; lines $(($2 - 1)) 'body'; } > "$PS/SKILL.md"
  printf '# Short\n' > "$PS/references/short.md"
}
# names_it <text>: SKILL.md also says this line. scripted <text>: scripts/run.sh says it.
names_it() { printf '%s\n' "$1" >> "$PS/SKILL.md"; }
scripted() { printf '#!/usr/bin/env bash\n# --help\n%s\n' "$1" > "$PS/scripts/run.sh"; chmod +x "$PS/scripts/run.sh"; }
orphan() { printf '# o\n' > "$PS/references/orphan.md"; }
ref() { cat > "$PS/references/short.md"; }   # ref < content: replace references/short.md
nonl() { local t; t="$(cat "$1")"; printf '%s' "$t" > "$1"; }   # drop the final newline
crlf() { local t; t="$(sed 's/$/\r/' "$1")"; printf '%s\n' "$t" > "$1"; }

pskill clean 10
pskill s1-499 499
pskill s1-500 500
pskill s1-500-no-final-newline 500; nonl "$PS/SKILL.md"
pskill s1-499-form-feed 498; printf 'a\fb\n' >> "$PS/SKILL.md"   # a line is \n-terminated; \f does not split it
pskill s2-orphan 10; orphan
pskill s2-deep 10; mkdir -p "$PS/resources/deep"; printf '# x\n' > "$PS/resources/deep/x.md"
pskill s2-dot-slash 10; orphan; names_it 'See ./references/orphan.md'
pskill s2-skill-dir 10; orphan; names_it 'cat "${CLAUDE_SKILL_DIR}/references/orphan.md"'
pskill s2-link 10; orphan; names_it 'See [o](references/orphan.md).'
pskill s2-period 10; orphan; names_it 'See references/orphan.md.'
pskill s2-bak 10; orphan; names_it 'See references/orphan.md.bak'
pskill s2-other-dot 10; orphan; names_it 'See other/./references/orphan.md'
pskill s2-other-path 10; orphan; names_it 'See other/references/orphan.md'
pskill s2-dash 10; orphan; names_it 'See references/orphan.md-old'
pskill s2-dot-dot 10; orphan; names_it 'See ../references/orphan.md'
pskill s2-script 10; orphan; scripted 'cat "$DIR/orphan.md"'
pskill s2-script-bak 10; orphan; scripted 'cat "$DIR/orphan.md.bak"'
pskill s2-script-longer 10; orphan; scripted 'cat "$DIR/my-orphan.md"'
pskill s2-script-dotted 10; orphan; scripted 'cat "$DIR/a.orphan.md"'
pskill s2-not-checked 10; mkdir -p "$PS/.github"; for f in references/README.md references/CHANGELOG.md CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md; do printf '# x\n' > "$PS/$f"; done
pskill s3-150 10; lines 150 | ref
pskill s3-100 10; lines 100 | ref
pskill s3-101-no-final-newline 10; lines 101 | ref; nonl "$PS/references/short.md"
pskill s3-150-crlf 10; { printf '# T\n## Contents\n```\n'; lines 147; } | ref; crlf "$PS/references/short.md"
pskill s3-lone-cr 10; lines 150 | tr '\n' '\r' | ref
pskill s3-after-30 10; { lines 30; printf '## Contents\n'; lines 119; } | ref
pskill s3-table 10; { printf '# T\n## Table of contents\n'; lines 148; } | ref
pskill s3-case 10; { printf '# T\n##  CONTENTS  \n'; lines 148; } | ref
pskill s3-fenced 10; { printf '# T\n```markdown\n## Contents\n```\n'; lines 146; } | ref
pskill s3-after-fence 10; { printf '# T\n   ~~~\n## Contents\n~~~~\n## Contents\n'; lines 145; } | ref
pskill s3-short-close 10; { printf '# T\n````\n```\n## Contents\n````\n'; lines 145; } | ref
pskill s3-close-with-text 10; { printf '# T\n```\n``` text\n## Contents\n'; lines 146; } | ref
pskill s3-other-char 10; { printf '# T\n```\n~~~\n## Contents\n'; lines 146; } | ref
pskill s3-inline 10; { printf '# T\n```inline``` text\n## Contents\n'; lines 147; } | ref
pskill s3-indent-4 10; { printf '# T\n    ```\n## Contents\n'; lines 147; } | ref
pskill s3-h3 10; { printf '# T\n### Contents\n'; lines 148; } | ref

# Normalise both reports to "<skill> <file> <rule> [<count>]" lines.
PY_OUT="$(python3 "$CHECKER" "$P" 2>&1)" || true
PY_SET="$(printf '%s\n' "$PY_OUT" | sed -n -E \
  -e 's#^plugins/kit/skills/([^/]+)/SKILL\.md: S1: body is ([0-9]+) lines.*#\1 SKILL.md S1 \2#p' \
  -e 's#^plugins/kit/skills/([^/]+)/(.*): S2: .*#\1 \2 S2#p' \
  -e 's#^plugins/kit/skills/([^/]+)/(.*): S3: ([0-9]+) lines.*#\1 \2 S3 \3#p' | LC_ALL=C sort)"
PY_OTHER="$(printf '%s\n' "$PY_OUT" | grep -vE '^plugins/kit/skills/[^/]+/.*: S[123]: ' || true)"
SH_SET="$(for d in "$P"/plugins/kit/skills/*/; do
  id="$(basename "$d")"
  bash "$VALIDATOR" "$d" 2>&1 | sed -n -E \
    -e "s#^  FAIL  body: ([0-9]+) lines .*#$id SKILL.md S1 \\1#p" \
    -e "s#^  FAIL  (.*): not named in SKILL\\.md.*#$id \\1 S2#p" \
    -e "s#^  FAIL  (.*): ([0-9]+) lines with no '\#\# Contents'.*#$id \\1 S3 \\2#p" \
    -e "/^  FAIL  body: /d; /: not named in SKILL\\.md/d; /lines with no '\#\# Contents'/d" \
    -e "s#^  FAIL  (.*)#$id OTHER \\1#p"
done | LC_ALL=C sort)"
if [[ -n "$PY_SET" && "$PY_SET" == "$SH_SET" && -z "$PY_OTHER" ]]; then
  ok "check-skill-structure.py and validate-skill.sh fail the same $(printf '%s\n' "$PY_SET" | wc -l | tr -d ' ') rule(s) on $(ls "$P/plugins/kit/skills" | wc -l | tr -d ' ') fixtures"
else
  bad "check-skill-structure.py and validate-skill.sh fail the same rules" "$(diff <(printf '%s\n' "$PY_SET") <(printf '%s\n' "$SH_SET"); printf '%s' "$PY_OTHER")"
fi
# The fixture set must exercise both verdicts of every rule, or the parity above is vacuous.
for want in 's1-500 SKILL.md S1 500' 's2-orphan references/orphan.md S2' 's3-150 references/short.md S3 150'; do
  [[ "$PY_SET" == *"$want"* ]] && ok "…the fixtures make $want fail" || bad "…the fixtures make $want fail" "$PY_SET"
done
for id in clean s1-499 s2-script s3-table; do
  [[ "$PY_SET" != *"$id "* ]] && ok "…and $id pass" || bad "…and $id pass" "$PY_SET"
done

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
