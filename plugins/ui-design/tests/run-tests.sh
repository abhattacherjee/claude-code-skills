#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts of the ui-design plugin.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a temp
# project directory (never the skill directory), in a clean environment (`env -i`,
# so nothing leaks in from the caller's shell). HOME points at a temp dir, and the
# environment is clean. The plugin is copied to a path with a
# space first, so a script that finds its files relative to its own location, or does
# not quote a path, fails here. Needs bash 3.2+, jq and python3 (standard library). Nothing
# here touches the network or anything outside the temp dir.
#
# Usage: bash plugins/ui-design/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy" "$TMP/home" "$TMP/proj" "$TMP/work"
cp -R "$PLUGIN/skills" "$TMP/plugin copy/skills"
cp -R "$PLUGIN/agents" "$TMP/plugin copy/agents"
# UIDESIGN_SKILLS and UIDESIGN_AGENTS may each be set by the caller to test another copy.
SKILLS="${UIDESIGN_SKILLS:-$TMP/plugin copy/skills}"
AGENTS="${UIDESIGN_AGENTS:-$TMP/plugin copy/agents}"
echo "skills under test: $SKILLS"
echo "agents under test: $AGENTS"

TOK="$SKILLS/figma/scripts/extract-design-tokens.sh"
PROJ="$TMP/proj"
HOME_DIR="$TMP/home"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

# A clean environment with a fixed git identity. GIT_CEILING_DIRECTORIES stops git from
# looking for a repository above the temp dir.
cenv() {
  env -i PATH="$PATH" HOME="$HOME_DIR" GIT_CONFIG_NOSYSTEM=1 GIT_CEILING_DIRECTORIES="$TMP" \
    GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com "$@"
}

# run_in <dir> <cmd...>: run in a clean env from <dir>; sets OUT (stdout), ERR (stderr), RC.
run_in() {
  local dir="$1"
  shift
  RC=0
  OUT="$(cd "$dir" && cenv "$@" 2>"$TMP/err")" || RC=$?
  ERR="$(cat "$TMP/err")"
}

# check <label> <want-rc|nonzero> [stdout-regex [stderr-regex]]  (uses OUT ERR RC from run_in)
check() {
  local label="$1" want="$2" ore="${3:-}" ere="${4:-}"
  if [[ "$want" == nonzero ]]; then
    if [[ "$RC" == 0 ]]; then
      bad "$label" "exit 0, want non-zero. stdout: $(printf '%s' "$OUT" | head -2)"
      return 0
    fi
  elif [[ "$RC" != "$want" ]]; then
    bad "$label" "exit $RC, want $want. stdout: $(printf '%s' "$OUT" | head -2) stderr: $(printf '%s' "$ERR" | head -2)"
    return 0
  fi
  if [[ -n "$ore" ]] && ! printf '%s' "$OUT" | grep -Eq -- "$ore"; then
    bad "$label" "stdout lacks /$ore/: $(printf '%s' "$OUT" | head -4)"
  elif [[ -n "$ere" ]] && ! printf '%s' "$ERR" | grep -Eq -- "$ere"; then
    bad "$label" "stderr lacks /$ere/: $(printf '%s' "$ERR" | head -4)"
  else
    ok "$label"
  fi
}

# json_is <label> <python-expr over d>: OUT must be valid JSON and the expression true.
# The expressions are literals written in this file, never input, so eval is safe here.
json_is() {
  local label="$1" expr="$2" res
  if res="$(printf '%s' "$OUT" | python3 -c 'import json,sys
d = json.load(sys.stdin)
print("yes" if eval(sys.argv[1]) else "no")' "$expr" 2>&1)" && [[ "$res" == "yes" ]]; then
    ok "$label"
  else
    bad "$label" "JSON check failed ($expr): $res; stdout: $(printf '%s' "$OUT" | head -c 300)"
  fi
}

# has <label> <file> <fixed-string>: the file contains the text.
has()  { grep -Fq -- "$3" "$2" && ok "$1" || bad "$1" "no '$3' in $2"; }
# lacks <label> <file> <fixed-string>: the file does not contain the text.
lacks() { grep -Fq -- "$3" "$2" && bad "$1" "found '$3' in $2" || ok "$1"; }

# The scripts start with `#!/usr/bin/env bash`. EXPECT_BASH_MAJOR (set by CI) pins the version.
echo "bash under test: $BASH_VERSION"
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

echo "figma ships no validator of its own"
[[ ! -e "$SKILLS/figma/scripts/validate-skill.sh" ]] && ok "figma has no scripts/validate-skill.sh" || bad "figma has no scripts/validate-skill.sh" "it exists"

# ---------------------------------------------------------------------------
echo "extract-design-tokens.sh (figma)"
FE="$TMP/work/my frontend"
mkdir -p "$FE/src"
cat > "$FE/src/index.css" <<'EOF'
:root {
  --brand-color: #123456;
  --radius: 8px;
}
.dark {
  --brand-color: #abcdef;
}
EOF
cat > "$FE/tailwind.config.js" <<'EOF'
module.exports = {
  theme: { extend: { fontFamily: {
    sans: ['Fixture Sans', 'sans-serif'],
  } } },
};
EOF
cat > "$FE/index.html" <<'EOF'
<html><head><link href="https://fonts.googleapis.com/css2?family=Fixture+Sans&display=swap" rel="stylesheet"></head></html>
EOF

run_in "$PROJ" "$TOK" "$FE"
check "html (the default) exits 0 and has the :root variables" 0 '--brand-color: #123456'
check "html has the dark-mode variables" 0 '\.dark \{'
check "html has the Tailwind font" 0 'Fixture Sans'
check "html has the Google Fonts link" 0 'fonts\.googleapis\.com/css2\?family=Fixture\+Sans'
run_in "$PROJ" "$TOK" "$FE" --format json
check "--format json exits 0" 0
json_is "--format json is valid JSON with the fixture tokens" 'd["source"].endswith("my frontend") and "--brand-color: #123456" in d["cssVariables"] and "#abcdef" in d["darkModeVariables"] and "Fixture Sans" in d["tailwindFonts"] and d["cssFile"].endswith("index.css") and d["googleFontsUrl"].startswith("https://fonts.googleapis.com/css2")'
run_in "$PROJ" "$TOK" "$FE" --format css
check "--format css exits 0 and has the variables" 0 '^:root \{'
check "--format css has the --brand-color variable" 0 '--brand-color: #123456'

echo "extract-design-tokens.sh: edge cases and bad input"
mkdir -p "$TMP/work/bare"
run_in "$PROJ" "$TOK" "$TMP/work/bare"
check "a project with no CSS file: html exits 0 (no unbound variable under set -u)" 0 'No CSS custom properties found'
run_in "$PROJ" "$TOK" "$TMP/work/bare" --format json
check "a project with no CSS file: json exits 0" 0
json_is "a project with no CSS file: json is valid, every value not found is null" 'd["cssFile"] is None and d["tailwindConfig"] is None and d["googleFontsUrl"] is None and d["cssVariables"] is None and d["darkModeVariables"] is None and d["tailwindFonts"] is None'
check "a project with no CSS file: a warning on stderr" 0 "" 'WARNING: no :root custom properties'
run_in "$PROJ" "$TOK" "$TMP/work/bare" --format css
check "a project with no CSS file: css exits 0" 0
ODD="$TMP/work/odd \"dir\\x"
mkdir -p "$ODD"
run_in "$PROJ" "$TOK" "$ODD" --format json
check "a quote and a backslash in the project path: json exits 0" 0
json_is "a quote and a backslash in the project path keep the JSON valid" 'd["source"].endswith("odd \"dir\\x")'
run_in "$PROJ" "$TOK" "$TMP/work/missing"
check "a missing directory exits 1 with a message" 1 "" 'does not exist'
run_in "$PROJ" "$TOK" "$FE" --format yaml
check "an unknown format exits 2 with a message" 2 "" "Unknown format 'yaml'"
run_in "$PROJ" "$TOK" "$FE" --format
check "--format with no value exits 2 with a message" 2 "" '--format needs a value'
run_in "$FE" "$TOK"
check "with no argument it reads the current directory" 0 '--brand-color: #123456'
run_in "$PROJ" "$TOK" --help
check "--help exits 0 and shows usage" 0 'Usage: extract-design-tokens.sh'
printf '%s' "$OUT" | grep -Eiq 'spacing|tailwind colou?rs' && bad "--help claims no spacing or Tailwind colors" "$OUT" || ok "--help claims no spacing or Tailwind colors"
check "--help names the CSS files it reads" 0 'src/app/globals\.css'

echo "extract-design-tokens.sh: which files it reads"
# The first CSS candidate has no :root variables; the third one has them.
P1="$TMP/work/second"
mkdir -p "$P1/src/app"
printf 'body { margin: 0; }\n' > "$P1/src/index.css"
printf ':root {\n  --brand: #f00;\n}\n.dark {\n  --brand: #0f0;\n}\n' > "$P1/src/app/globals.css"
run_in "$PROJ" "$TOK" "$P1" --format json
check "a first CSS file with no variables: json exits 0" 0
json_is "a first CSS file with no variables: the next file that has them is used" 'd["cssFile"].endswith("src/app/globals.css") and d["cssVariables"] == "--brand: #f00;" and d["darkModeVariables"] == "--brand: #0f0;"'
[[ -z "$ERR" ]] && ok "variables found: no warning" || bad "variables found: no warning" "$ERR"
# Dark mode from @media (prefers-color-scheme: dark), and its :root stays out of the light set.
P2="$TMP/work/media"
mkdir -p "$P2/src"
cat > "$P2/src/index.css" <<'EOF'
:root {
    --bg: #ffffff;
	--fg: #111111;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #000000;
  }
}
EOF
run_in "$PROJ" "$TOK" "$P2" --format json
json_is "dark mode from @media (prefers-color-scheme: dark) is read" 'd["darkModeVariables"] == "--bg: #000000;"'
json_is "the dark :root inside @media stays out of cssVariables" 'd["cssVariables"] == "--bg: #ffffff;\n--fg: #111111;"'
json_is "json strips leading spaces and tabs from each variable" 'all(not l[:1].isspace() for l in d["cssVariables"].split("\n"))'
json_is "no Tailwind config and no fonts link: those are null" 'd["tailwindFonts"] is None and d["tailwindConfig"] is None and d["googleFontsUrl"] is None'
# The Google Fonts link is read from public/index.html when index.html has none.
P3="$TMP/work/html"
mkdir -p "$P3/public"
printf '<html></html>\n' > "$P3/index.html"
printf '<link href="https://fonts.googleapis.com/css2?family=Public+Font" rel="stylesheet">\n' > "$P3/public/index.html"
run_in "$PROJ" "$TOK" "$P3"
check "the fonts link is read from public/index.html when index.html has none" 0 'family=Public\+Font'
# --format json with no jq on PATH.
NOJQ="$TMP/nojq"
mkdir -p "$NOJQ"
for tool in bash env sed grep head tr cat awk dirname basename; do
  src="$(command -v "$tool" || true)"
  [[ -n "$src" ]] && ln -s "$src" "$NOJQ/$tool"
done
RC=0
OUT="$(cd "$PROJ" && env -i PATH="$NOJQ" HOME="$HOME_DIR" "$TOK" "$FE" --format json 2>"$TMP/err")" || RC=$?
ERR="$(cat "$TMP/err")"
check "--format json with no jq exits 1 and says it needs jq" 1 "" 'needs jq'
[[ -z "$OUT" ]] && ok "--format json with no jq prints nothing on stdout" || bad "--format json with no jq prints nothing on stdout" "$OUT"

echo "extract-design-tokens.sh: which blocks are light and which are dark"
# tok_case <name>: write stdin to <name>/src/index.css and run --format json on it.
tok_case() {
  mkdir -p "$TMP/work/sel-$1/src"
  cat > "$TMP/work/sel-$1/src/index.css"
  run_in "$PROJ" "$TOK" "$TMP/work/sel-$1" --format json
}
tok_case rootdark <<'EOF'
:root {
  --bg: white;
  --fg: black;
}
:root.dark {
  --bg: black;
  --fg: white;
}
EOF
json_is ":root.dark: its values stay out of the light set" 'd["cssVariables"] == "--bg: white;\n--fg: black;"'
json_is ":root.dark: its values are the dark set" 'd["darkModeVariables"] == "--bg: black;\n--fg: white;"'
tok_case datatheme <<'EOF'
:root {
  --bg: white;
}
[data-theme="dark"]:root, :root[data-theme="dark"] {
  --bg: black;
}
EOF
json_is "[data-theme=\"dark\"] with :root: light set is the plain :root only" 'd["cssVariables"] == "--bg: white;"'
json_is "[data-theme=\"dark\"] with :root: its values are the dark set" 'd["darkModeVariables"] == "--bg: black;"'
tok_case darkforms <<'EOF'
:root { }
:root {
  --a: 1;
}
html.dark {
  --a: 2;
}
.dark:root {
  --a: 3;
}
[data-theme=dark] {
  --a: 4;
}
.dark .card {
  --a: 5;
}
EOF
json_is "html.dark, .dark:root and [data-theme=dark] are dark; .dark .card is neither" 'd["cssVariables"] == "--a: 1;" and d["darkModeVariables"] == "--a: 2;\n--a: 3;\n--a: 4;"'
tok_case layer <<'EOF'
@layer base {
  :root {
    --background: 0 0% 100%;
  }
  .dark {
    --background: 0 0% 4%;
  }
}
@layer {
  :root {
    --ring: blue;
  }
}
EOF
json_is "@layer is transparent: its :root is the light set" 'd["cssVariables"] == "--background: 0 0% 100%;\n--ring: blue;"'
json_is "@layer is transparent: its .dark is the dark set" 'd["darkModeVariables"] == "--background: 0 0% 4%;"'
tok_case wrappers <<'EOF'
:root {
  --gap: 4px;
}
@media (min-width: 768px) {
  :root {
    --gap: 8px;
  }
}
@supports (display: grid) {
  :root {
    --grid: 1;
  }
}
@layer base {
  @media (min-width: 768px) {
    :root {
      --gap: 16px;
    }
  }
}
EOF
json_is "@media (min-width) and @supports :root stay out of the light set" 'd["cssVariables"] == "--gap: 4px;" and d["darkModeVariables"] is None'
tok_case comment <<'EOF'
/* Example { */
/*
  a multi-line comment { with
  --fake: 1;
*/
:root {
  --primary: red; /* } */
}
EOF
json_is "a brace inside a comment does not change nesting" 'd["cssVariables"] == "--primary: red; /* } */"'
tok_case quote <<'EOF'
:root {
  --a: "{";
  --q: '}}';
  --b: blue;
}
.dark {
  --b: navy;
}
EOF
json_is "a brace inside a quoted value does not change nesting" 'd["cssVariables"] == "--a: \"{\";\n--q: '"'"'}}'"'"';\n--b: blue;" and d["darkModeVariables"] == "--b: navy;"'

echo "figma reaches its agent through the plugin agent type, and nothing points at ~/.claude/agents"
grep -Fq 'subagent_type: "ui-design:figma-ux-expert"' "$SKILLS/figma/SKILL.md" && ok "figma starts subagent_type ui-design:figma-ux-expert" || bad "figma starts subagent_type ui-design:figma-ux-expert" "line not found in figma/SKILL.md"
grep -Fq 'subagent_type: "general-purpose"' "$SKILLS/figma/SKILL.md" && bad "figma no longer starts a general-purpose agent" "found subagent_type general-purpose" || ok "figma no longer starts a general-purpose agent"
for f in "$SKILLS/figma/SKILL.md" "$AGENTS/figma-ux-expert.md"; do
  if grep -Fq '~/.claude/agents' "$f"; then
    bad "$(basename "$f") does not mention ~/.claude/agents" "$(grep -Fn '~/.claude/agents' "$f" | head -2)"
  else
    ok "$(basename "$f") does not mention ~/.claude/agents"
  fi
done
[[ -f "$AGENTS/figma-ux-expert.md" ]] && ok "agents/figma-ux-expert.md is in the plugin" || bad "agents/figma-ux-expert.md is in the plugin" "missing"
grep -Eq '^name: figma-ux-expert$' "$AGENTS/figma-ux-expert.md" 2>/dev/null && ok "the agent keeps the bare name: figma-ux-expert" || bad "the agent keeps the bare name: figma-ux-expert" "no 'name: figma-ux-expert' line"
[[ ! -e "$SKILLS/figma/agents" ]] && ok "figma has no agents/ directory (agents live at the plugin root)" || bad "figma has no agents/ directory" "skills/figma/agents exists"
grep -Fq 'figma-ui-designer' "$AGENTS/figma-ux-expert.md" && bad "the agent text does not name the old skill" "$(grep -Fn figma-ui-designer "$AGENTS/figma-ux-expert.md" | head -1)" || ok "the agent text does not name the old skill"

# ---------------------------------------------------------------------------
echo "every script named in a SKILL.md exists, is executable and answers --help"
# Pull each "${CLAUDE_SKILL_DIR}/scripts/<name>" out of a SKILL.md, resolve it against that
# skill's directory in the plugin copy, and run it with --help from the project dir.
for skill in figma; do
  names="$(python3 - "$SKILLS/$skill/SKILL.md" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
seen = []
for m in re.finditer(r'"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_.-]+\.(?:sh|py))"', text):
    if m.group(1) not in seen:
        seen.append(m.group(1))
print("\n".join(seen))
EOF
)" || names=""  # a python error leaves no names, and the count check below fails
  n=0
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    n=$((n + 1))
    if [[ ! -x "$SKILLS/$skill/scripts/$name" ]]; then
      bad "$skill SKILL.md names scripts/$name" "missing or not executable"
      continue
    fi
    run_in "$PROJ" "$SKILLS/$skill/scripts/$name" --help
    check "$skill SKILL.md command runs: scripts/$name --help" 0
  done <<< "$names"
  [[ "$n" -ge 1 ]] && ok "$skill SKILL.md: found $n script command(s) to run" || bad "$skill SKILL.md: found no script commands to run" "the extractor matched nothing"
done

echo "figma never shows the substituted path tokens in prose"
# Claude Code replaces "${CLAUDE_SKILL_DIR}" and "${CLAUDE_PLUGIN_ROOT}" everywhere in a SKILL.md,
# prose and inline code included, before the model reads it. In a fenced code block the token is a
# real command for this skill's own scripts, which is what we want. Outside one the model would read
# this skill's absolute path where the text says something else. So outside fenced blocks the token
# must not appear.
for skill in figma; do
  hits="$(python3 - "$SKILLS/$skill/SKILL.md" <<'EOF'
import re, sys
fence = None  # (char, length) of the open fence, or None
for no, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    line = re.sub(r'^\s*(>\s*)*', '', line)  # a fence may sit inside a blockquote
    m = re.match(r'(`{3,}|~{3,})', line)
    if m:
        tok = m.group(1)
        if fence is None:
            fence = (tok[0], len(tok))
            continue
        if tok[0] == fence[0] and len(tok) >= fence[1] and not line.strip()[len(tok):]:
            fence = None
            continue
    if fence is None and re.search(r'\$\{CLAUDE_(SKILL_DIR|PLUGIN_ROOT)\}', line):
        print(f"line {no}: {line.strip()[:100]}")
if fence is not None:
    print("unclosed code fence")
EOF
)" || hits="the python check failed (exit $?)"
  [[ -z "$hits" ]] && ok "$skill SKILL.md: no path token outside code blocks" \
    || bad "$skill SKILL.md: path token outside a code block (it is substituted, so the model sees an absolute path)" "$hits"
done

echo "the scripts do not depend on their old install path"
for f in "$SKILLS"/figma/scripts/extract-design-tokens.sh "$SKILLS"/figma/SKILL.md; do
  if grep -Eq '~/\.claude/skills|\.claude/skills/' "$f"; then
    bad "$(basename "$f") does not name ~/.claude/skills" "$(grep -En '~/\.claude/skills|\.claude/skills/' "$f" | head -2)"
  else
    ok "$(basename "$f") does not name ~/.claude/skills"
  fi
done

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
