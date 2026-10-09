#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts in the skill-kit plugin.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a temp
# project directory (never the skill directory), in a clean environment (`env -i`,
# so nothing leaks in from the caller's shell). The plugin is copied to a path with
# a space first, so a script that finds its files relative to its own location, or
# does not quote a path, fails here. Needs bash 3.2+, python3 (standard library) and
# jq (prepare-plugin.sh needs it). Nothing here touches the network or anything
# outside the temp dir: `gh` always fails in the PATH the scripts get.
#
# The long-running sync, release and publish scripts have their own suite
# (scripts/test-sync-hygiene.sh). Here each one gets --help and one bad-input case.
#
# Usage: bash plugins/skill-kit/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy" "$TMP/home" "$TMP/proj"
cp -R "$PLUGIN/skills" "$TMP/plugin copy/skills"
# SKILLS may be set by the caller to test another copy.
SKILLS="${SKILLS:-$TMP/plugin copy/skills}"

AUTHOR="$SKILLS/author/scripts"
PUBLISH="$SKILLS/publish/scripts"
EXTRACT="$SKILLS/extract/scripts"
PROJ="$TMP/proj"

# A `gh` that always fails sits first on the PATH, so no script can reach GitHub whatever
# this machine is logged in to. The scripts treat a failing `gh` as "no GitHub user".
BIN="$TMP/bin"
mkdir -p "$BIN"
printf '#!/bin/sh\necho "gh is disabled in the skill-kit tests" >&2\nexit 1\n' > "$BIN/gh"
chmod +x "$BIN/gh"
CLEAN_PATH="$BIN:$PATH"

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

# run_in <dir> <cmd...>: run in a clean env from <dir>; sets OUT (stdout), ERR (stderr), RC.
run_in() {
  local dir="$1"
  shift
  RC=0
  OUT="$(cd "$dir" && env -i PATH="$CLEAN_PATH" HOME="$TMP/home" "$@" 2>"$TMP/err")" || RC=$?
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

# The scripts start with `#!/usr/bin/env bash`. EXPECT_BASH_MAJOR (set by CI) pins the version.
echo "bash under test: $BASH_VERSION"
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

echo "validate-skill.sh (all three skills carry the same validator)"
for s in author publish extract; do
  run_in "$PROJ" "$SKILLS/$s/scripts/validate-skill.sh" "$SKILLS/$s"
  check "$s: validate-skill.sh passes on its own skill" 0 'Result: PASS'
done
ROOT_VALIDATOR="$PLUGIN/../../scripts/validate-skill.sh"
if [[ -f "$ROOT_VALIDATOR" ]]; then
  for s in author publish extract; do
    cmp -s "$ROOT_VALIDATOR" "$SKILLS/$s/scripts/validate-skill.sh" && ok "$s: validate-skill.sh is byte-identical to the repo-root copy" || bad "$s: validate-skill.sh is byte-identical to the repo-root copy" "they differ"
  done
else
  # A skipped check reads as a pass, so a missing root validator fails the run.
  bad "validate-skill.sh copies can be compared with the repo-root copy" "no scripts/validate-skill.sh at $ROOT_VALIDATOR (run the tests from a checkout of the repo)"
fi
mkdir -p "$TMP/badskill"
printf -- '---\nname: Bad_Name\nowner: me\n---\n\n# Body\n' > "$TMP/badskill/SKILL.md"
for s in author publish extract; do
  run_in "$PROJ" "$SKILLS/$s/scripts/validate-skill.sh" "$TMP/badskill"
  check "$s: validate-skill.sh fails on a skill with bad frontmatter" nonzero 'Result: FAIL'
  run_in "$PROJ" "$SKILLS/$s/scripts/validate-skill.sh" "$TMP/does-not-exist"
  check "$s: validate-skill.sh fails on a missing directory" nonzero "" 'not found'
done

echo "validate-skill.sh rules from Anthropic's skill authoring guide (#214)"
V="$SKILLS/author/scripts/validate-skill.sh"
# vskill <dir> <name> <body-lines>: a valid skill whose SKILL.md body has that many lines.
vskill() {
  rm -rf "$1"; mkdir -p "$1"
  { printf -- '---\nname: %s\ndescription: "Does a thing. Use when: (1) testing."\nmetadata:\n  version: 1.0.0\n---\n' "$2"
    local i; for ((i = 1; i <= $3; i++)); do printf 'line %d\n' "$i"; done; } > "$1/SKILL.md"
}
VS="$TMP/vskill/my-skill"
vskill "$VS" my-skill 499; run_in "$PROJ" "$V" "$VS"
check "a 499-line body passes" 0 'body: 499 lines'
check "…and a skill with no reference files says so" 0 'PASS  no reference Markdown files to check'
vskill "$VS" my-skill 500; run_in "$PROJ" "$V" "$VS"
check "a 500-line body fails" 1 'FAIL  body: 500 lines \(must be under 500\)'
vskill "$VS" my-skill 500; printf '%s' "$(cat "$VS/SKILL.md")" > "$VS/SKILL.md.tmp"; mv "$VS/SKILL.md.tmp" "$VS/SKILL.md"; run_in "$PROJ" "$V" "$VS"
check "a 500-line body with no final newline fails" 1 'FAIL  body: 500 lines'
N64="$(printf 'a%.0s' $(seq 1 64))"
vskill "$VS" "$N64" 10; run_in "$PROJ" "$V" "$VS"
check "a 64-character name passes" 0 'name: length OK \(64 chars'
vskill "$VS" "${N64}b" 10; run_in "$PROJ" "$V" "$VS"
check "a 65-character name fails" 1 'FAIL  name: too long \(65 chars'
for nm in my-claude-helper anthropic-tools headless-claude-job-hardening; do
  vskill "$VS" "$nm" 10; run_in "$PROJ" "$V" "$VS"
  check "the name $nm fails (reserved word)" 1 "FAIL  name: must not contain the reserved word"
done
vskill "$VS" Claude-Tools 10; run_in "$PROJ" "$V" "$VS"
check "the reserved-word check ignores case" 1 'FAIL  name: must not contain the reserved word "claude"'
for nm in clad-tools anthro-pic cla-ude; do
  vskill "$VS" "$nm" 10; run_in "$PROJ" "$V" "$VS"
  check "the name $nm passes (only looks like a reserved word)" 0 'name: no reserved words'
done

# Reference files: every .md file is named in SKILL.md or read by a script, and one over
# 100 lines has a ## Contents heading in its first 30 lines. rskill: a clean skill whose
# SKILL.md names references/short.md; each case plants one change, then runs vref.
rskill() { vskill "$VS" my-skill 10; mkdir -p "$VS/references" "$VS/scripts"; printf 'Read references/short.md.\n' >> "$VS/SKILL.md"; printf '# Short\n' > "$VS/references/short.md"; }
vref() { run_in "$PROJ" "$V" "$VS"; }
nlines() { local i; for ((i = 1; i <= $1; i++)); do printf 'line %d\n' "$i"; done; }
O='references/orphan.md: not named in SKILL.md or read by a script'
rskill; vref; check "a skill whose references are all named passes" 0 'references/short.md: named'
rskill; printf '# o\n' > "$VS/references/orphan.md"; vref; check "an unnamed reference fails" 1 "FAIL  $O"
rskill; mkdir -p "$VS/resources/deep"; printf '# x\n' > "$VS/resources/deep/x.md"; vref
check "an unnamed .md file at any depth fails" 1 'FAIL  resources/deep/x.md: not named'
for how in './references/orphan.md' '${CLAUDE_SKILL_DIR}/references/orphan.md' '[o](references/orphan.md)' 'references/orphan.md.'; do
  rskill; printf '# o\n' > "$VS/references/orphan.md"; printf 'See %s\n' "$how" >> "$VS/SKILL.md"; vref
  check "SKILL.md naming it as $how counts" 0 'references/orphan.md: named'
done
for how in 'references/orphan.md.bak' 'other/./references/orphan.md' 'other/references/orphan.md' 'references/orphan.md-old'; do
  rskill; printf '# o\n' > "$VS/references/orphan.md"; printf 'See %s\n' "$how" >> "$VS/SKILL.md"; vref
  check "SKILL.md naming $how does not count" 1 "FAIL  $O"
done
rskill; printf '# o\n' > "$VS/references/orphan.md"; printf '#!/usr/bin/env bash\n# --help\ncat "$DIR/orphan.md"\n' > "$VS/scripts/run.sh"; chmod +x "$VS/scripts/run.sh"; vref
check "a file a script in scripts/ reads counts" 0 'references/orphan.md: named'
for how in 'orphan.md.bak' 'my-orphan.md' 'x.orphan.md'; do
  rskill; printf '# o\n' > "$VS/references/orphan.md"; printf '#!/usr/bin/env bash\n# --help\ncat "$DIR/%s"\n' "$how" > "$VS/scripts/run.sh"; chmod +x "$VS/scripts/run.sh"; vref
  check "a script naming $how does not count" 1 "FAIL  $O"
done
rskill; for f in references/README.md references/CHANGELOG.md CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md; do mkdir -p "$VS/$(dirname "$f")"; printf '# x\n' > "$VS/$f"; done; vref
check "README, CHANGELOG, CONTRIBUTING and .md files under a dot-directory are never orphans" 0 'Result: PASS'
S3='references/short.md: 150 lines with no .## Contents. heading in the first 30 lines'
rskill; nlines 150 > "$VS/references/short.md"; vref; check "a 150-line reference with no Contents fails" 1 "FAIL  $S3"
rskill; nlines 100 > "$VS/references/short.md"; vref; check "a 100-line reference needs no Contents" 0 'Result: PASS'
rskill; printf '%s' "$(nlines 101)" > "$VS/references/short.md"; vref
check "a 101-line reference with no final newline needs Contents" 1 'FAIL  references/short.md: 101 lines'
rskill; { nlines 30; printf '## Contents\n'; nlines 119; } > "$VS/references/short.md"; vref
check "a Contents heading after line 30 fails" 1 "FAIL  $S3"
rskill; { printf '# T\n## Table of contents\n'; nlines 148; } > "$VS/references/short.md"; vref
check "## Table of contents is accepted" 0 'references/short.md: has a Contents heading'
rskill; { printf '# T\n##  CONTENTS  \n'; nlines 148; } > "$VS/references/short.md"; vref
check "the heading ignores case and extra spaces" 0 'references/short.md: has a Contents heading'
rskill; { printf '# T\n```markdown\n## Contents\n```\n'; nlines 146; } > "$VS/references/short.md"; vref
check "a ## Contents inside a code fence does not count" 1 "FAIL  $S3"
rskill; { printf '# T\n   ~~~\n## Contents\n~~~~\n## Contents\n'; nlines 145; } > "$VS/references/short.md"; vref
check "a real ## Contents after a closed fence counts" 0 'references/short.md: has a Contents heading'
rskill; { printf '# T\n````\n```\n## Contents\n````\n'; nlines 145; } > "$VS/references/short.md"; vref
check "a shorter fence line does not close a longer fence" 1 "FAIL  $S3"
rskill; { printf '# T\n```\n``` not a close\n## Contents\n'; nlines 146; } > "$VS/references/short.md"; vref
check "a fence line with text after it does not close the fence" 1 "FAIL  $S3"
rskill; { printf '# T\n```inline``` is not a fence\n## Contents\n'; nlines 147; } > "$VS/references/short.md"; vref
check "a line like \`\`\`inline\`\`\` is not a fence" 0 'references/short.md: has a Contents heading'
rskill; { printf '# T\n    ```\n## Contents\n'; nlines 147; } > "$VS/references/short.md"; vref
check "a fence indented 4 spaces is not a fence" 0 'references/short.md: has a Contents heading'
rskill; { printf '# T\n### Contents\n'; nlines 148; } > "$VS/references/short.md"; vref
check "a ### Contents heading fails" 1 "FAIL  $S3"
rskill; mkdir -p "$VS/tests/fixtures"; nlines 150 > "$VS/tests/fixtures/issue.md"; vref
check "a top-level tests/ directory is not checked (test fixtures)" 0 'Result: PASS'
rskill; mkdir -p "$VS/references/tests"; printf '# x\n' > "$VS/references/tests/x.md"; vref
check "a tests/ directory deeper down is still checked" 1 'FAIL  references/tests/x.md: not named'
rskill; printf '# o\n' > "$VS/references/orphan.md"; printf '#!/usr/bin/env bash\n# --help\ncat "$DIR/orphan.md"\n' > "$TMP/reader.sh"; chmod +x "$TMP/reader.sh"; ln -s "$TMP/reader.sh" "$VS/scripts/reader.sh"; vref
check "a symlinked script that reads the file counts" 0 'references/orphan.md: named'
rskill; printf '# b\n' > "$VS/references/a\\tb.md"; printf 'See references/a\tb.md\n' >> "$VS/SKILL.md"; vref
check "a backslash in a file name is not read as an escape" 1 'FAIL  references/a\\tb.md: not named'
rskill; printf '# b\n' > "$VS/references/a\\b.md"; printf 'See references/a\\b.md\n' >> "$VS/SKILL.md"; vref
check "…and a file name with a backslash can be named" 0 'references/a\\b.md: named'
rskill; printf '# n\n' > "$VS/references/a
b.md"; vref
check "a file name with a newline is checked, not skipped" 1 'FAIL  references/a\\nb.md: not named'
rskill; printf '# x\n' > "$VS/references/x.md"; cp "$V" "$VS/scripts/validate-skill.sh"; vref
check "a skill that ships validate-skill.sh still fails an unnamed references/x.md" 1 'FAIL  references/x.md: not named'
bad_names="$( { grep -oE '[A-Za-z0-9_.-]+\.md' "$V" || true; } | { grep -vxE 'SKILL\.md|README\.md|CHANGELOG\.md|CONTRIBUTING\.md|\.md' || true; } | sort -u | tr '\n' ' ')"
[[ -z "$bad_names" ]] && ok "validate-skill.sh names no .md file a skill could ship" || bad "validate-skill.sh names no .md file a skill could ship" "$bad_names"
if [[ "$(id -u)" != 0 ]]; then   # root reads anything, so these cannot fail there
  rskill; printf '# s\n' > "$VS/references/secret.md"; printf 'See references/secret.md\n' >> "$VS/SKILL.md"; chmod 000 "$VS/references/secret.md"; vref
  chmod 644 "$VS/references/secret.md"
  check "an unreadable reference fails, exit 1 (not a crash)" 1 'FAIL  references/secret.md: cannot read'
  rskill; mkdir -p "$VS/hidden"; printf '# o\n' > "$VS/hidden/orphan.md"; chmod 000 "$VS/hidden"; vref
  chmod 755 "$VS/hidden"
  check "a directory find cannot read fails, not skipped" 1 'FAIL  cannot list every Markdown file'
  rskill; mkdir -p "$VS/scripts/locked"; chmod 000 "$VS/scripts/locked"; vref
  chmod 755 "$VS/scripts/locked"
  check "a scripts/ directory find cannot read fails, not skipped" 1 'FAIL  cannot list every file in scripts/'
fi

# author teaches the four guide rules the validator cannot check, each exactly once (#214).
for rule in 'gerund form' 'head -100' 'Write evaluations first' 'Justify every constant'; do
  n="$(cat "$SKILLS/author/SKILL.md" "$SKILLS"/author/references/*.md | grep -c -- "$rule" || true)"
  [[ "$n" == 1 ]] && ok "author says '$rule' once" || bad "author says '$rule' once" "found $n times"
done

echo "generate-task-manifest.sh (author)"
mkdir -p "$PROJ/my-skill"
# The command as author/SKILL.md writes it, with the placeholder path filled in.
run_in "$PROJ" "$AUTHOR/generate-task-manifest.sh" --skill-dir "$PROJ/my-skill" --workflows "full-audit:3,quick-check:2"
check "generate from the project dir exits 0" 0 'task-manifest\.sh'
[[ -x "$PROJ/my-skill/scripts/task-manifest.sh" ]] && ok "the generated task-manifest.sh is executable" || bad "the generated task-manifest.sh is executable" "missing or not executable"
run_in "$PROJ" "$PROJ/my-skill/scripts/task-manifest.sh" --list
check "generated --list names both workflows" 0 'full-audit quick-check'
run_in "$PROJ" "$PROJ/my-skill/scripts/task-manifest.sh" full-audit
json_is "generated full-audit is a JSON array of 3 tasks" 'len(d) == 3 and all(set(["subject", "activeForm", "description"]) <= set(t) for t in d)'
run_in "$PROJ" "$PROJ/my-skill/scripts/task-manifest.sh" quick-check
json_is "generated quick-check is a JSON array of 2 tasks" 'len(d) == 2'
run_in "$PROJ" "$PROJ/my-skill/scripts/task-manifest.sh" no-such-workflow
check "generated script rejects an unknown workflow" nonzero "" 'unknown workflow'
run_in "$PROJ" "$AUTHOR/generate-task-manifest.sh" --help
check "--help exits 0" 0 'Usage: generate-task-manifest\.sh'
run_in "$PROJ" "$AUTHOR/generate-task-manifest.sh" --skill-dir "$TMP/does-not-exist" --workflows "a:2"
check "missing skill dir exits 1" 1 "" 'not found'
run_in "$PROJ" "$AUTHOR/generate-task-manifest.sh"
check "no arguments exits 2" 2 "" 'required'

echo "claudeception-activator.sh (extract)"
run_in "$PROJ" "$EXTRACT/claudeception-activator.sh"
check "prints the reminder and exits 0" 0 'MANDATORY SKILL EVALUATION'
check "names Skill(skill-kit:extract)" 0 'Skill\(skill-kit:extract\)'
printf '%s' "$OUT" | grep -Fq 'Skill(claudeception)' && bad "does not name the old Skill(claudeception)" "found it" || ok "does not name the old Skill(claudeception)"
run_in "$PROJ" "$EXTRACT/claudeception-activator.sh" --help
check "--help exits 0 and prints no reminder" 0 'Usage: claudeception-activator\.sh'
printf '%s' "$OUT" | grep -q 'MANDATORY' && bad "--help prints no reminder" "it printed the reminder" || ok "--help prints no reminder"
if grep -rq 'hooks' "$PLUGIN/.claude-plugin/plugin.json" 2>/dev/null || [[ -e "$PLUGIN/hooks" ]]; then
  bad "the plugin does not register the activator as a hook" "plugin.json mentions hooks or a hooks/ dir exists"
else
  ok "the plugin does not register the activator as a hook (it is opt-in)"
fi

echo "prepare-plugin.sh and validate-plugin.sh (publish)"
FX="$TMP/fx"
mkdir -p "$FX/tiny"
printf -- '---\nname: tiny\ndescription: "A tiny fixture skill. Use when: (1) testing."\nmetadata:\n  version: 1.0.0\n---\n\n# Tiny\n\nBody.\n' > "$FX/tiny/SKILL.md"
printf '# Changelog\n\n## [1.0.0] - 2026-01-01\n\n- First.\n' > "$FX/tiny/CHANGELOG.md"
cat > "$FX/plugin-manifest.json" <<'EOF'
{
  "name": "tiny-plugin",
  "version": "2.3.4",
  "description": "A fixture plugin with one skill.",
  "skills": [{ "name": "tiny", "source": "./tiny" }],
  "commands": []
}
EOF
OUTDIR="$TMP/out/tiny-plugin"
run_in "$PROJ" "$PUBLISH/prepare-plugin.sh" --output-dir "$OUTDIR" --github-user someone --author Tester "$FX/plugin-manifest.json"
check "prepare-plugin assembles the fixture plugin, exit 0" 0 'Plugin:[[:space:]]+tiny-plugin v2\.3\.4'
if [[ -f "$OUTDIR/.claude-plugin/plugin.json" ]]; then
  OUT="$(cat "$OUTDIR/.claude-plugin/plugin.json")"
  json_is "assembled plugin.json has the manifest's name and version" 'd["name"] == "tiny-plugin" and d["version"] == "2.3.4"'
else
  bad "assembled plugin.json exists" "$OUTDIR/.claude-plugin/plugin.json is missing"
fi
[[ -f "$OUTDIR/skills/tiny/SKILL.md" ]] && ok "the skill's SKILL.md is in the assembled plugin" || bad "the skill's SKILL.md is in the assembled plugin" "missing"
cmp -s "$FX/tiny/SKILL.md" "$OUTDIR/skills/tiny/SKILL.md" && ok "the assembled SKILL.md is the source file, unchanged" || bad "the assembled SKILL.md is the source file, unchanged" "differs"
for f in README.md LICENSE .gitignore; do
  [[ -f "$OUTDIR/$f" ]] && ok "the assembled plugin has $f" || bad "the assembled plugin has $f" "missing"
done
run_in "$PROJ" "$PUBLISH/validate-plugin.sh" "$OUTDIR"
check "validate-plugin passes on the assembled plugin" 0 'Result: PASS'
# A default run writes to ./build/<name> under the cwd, as publish/SKILL.md says.
run_in "$PROJ" "$PUBLISH/prepare-plugin.sh" --github-user someone --author Tester "$FX/plugin-manifest.json"
check "prepare-plugin with no --output-dir exits 0" 0
[[ -f "$PROJ/build/tiny-plugin/.claude-plugin/plugin.json" ]] && ok "the default output is ./build/<plugin-name> under the cwd" || bad "the default output is ./build/<plugin-name> under the cwd" "not found under $PROJ/build"
# Break the assembled plugin: validate-plugin must fail.
rm -rf "$TMP/broken" && cp -R "$OUTDIR" "$TMP/broken" && rm -f "$TMP/broken/.claude-plugin/plugin.json"
run_in "$PROJ" "$PUBLISH/validate-plugin.sh" "$TMP/broken"
check "validate-plugin fails on a plugin with no plugin.json" nonzero 'FAIL'
# A manifest missing 'version'.
printf '{"name":"x","description":"d","skills":[],"commands":[]}\n' > "$FX/no-version.json"
run_in "$PROJ" "$PUBLISH/prepare-plugin.sh" --output-dir "$TMP/out/x" --github-user someone "$FX/no-version.json"
check "prepare-plugin rejects a manifest with no version" nonzero "" "missing required field 'version'"
# A skill source that does not exist.
printf '{"name":"x","version":"1.0.0","description":"d","skills":[{"name":"gone","source":"./gone"}],"commands":[]}\n' > "$FX/gone.json"
run_in "$PROJ" "$PUBLISH/prepare-plugin.sh" --output-dir "$TMP/out/gone" --github-user someone "$FX/gone.json"
check "prepare-plugin rejects a skill source that does not exist" nonzero "" 'skill source not found'

echo "bad input and --help, one case per publish script"
run_in "$PROJ" "$PUBLISH/prepare-plugin.sh" "$TMP/no-such-manifest.json"
check "prepare-plugin: missing manifest exits non-zero" nonzero "" 'manifest file not found'
run_in "$PROJ" "$PUBLISH/validate-plugin.sh" "$TMP/no-such-dir"
check "validate-plugin: missing directory exits non-zero" nonzero "" 'directory not found'
run_in "$PROJ" "$PUBLISH/validate-pre-sync.sh" "$TMP/no-such-dir"
check "validate-pre-sync: missing monorepo directory exits non-zero" nonzero "" 'does not exist'
run_in "$PROJ" "$PUBLISH/sync-monorepo.sh" --no-such-option
check "sync-monorepo: unknown option exits non-zero" nonzero "" 'Unknown option'
run_in "$PROJ" "$PUBLISH/release-monorepo.sh"
check "release-monorepo: no bump level exits non-zero" nonzero "" 'bump level required'
run_in "$PROJ" "$PUBLISH/release-monorepo.sh" patch "$TMP/no-such-dir"
check "release-monorepo: a directory that is not a git repo exits non-zero" nonzero "" 'not a git repository'
run_in "$PROJ" "$PUBLISH/install-plugin.sh" "$TMP/no-such-dir"
check "install-plugin: missing plugin directory exits non-zero" nonzero "" 'plugin directory not found'
run_in "$PROJ" "$PUBLISH/prepare-skill-repo.sh" "$TMP/no-such-dir"
check "prepare-skill-repo: missing skill directory exits non-zero with a message" nonzero "" 'skill directory not found'
run_in "$PROJ" "$PUBLISH/sync-individual-repos.sh" --no-such-option
check "sync-individual-repos: unknown option exits non-zero" nonzero "" 'Unknown option'
# Happy paths. Both scripts read their templates from ../references and skip a missing template
# silently, so a wrong path would drop these files with no error: assert they are produced.
RS="$TMP/repo-skill"
mkdir -p "$RS"
cp "$FX/tiny/SKILL.md" "$FX/tiny/CHANGELOG.md" "$RS/"
run_in "$PROJ" "$PUBLISH/prepare-skill-repo.sh" --github-user tester "$RS"
check "prepare-skill-repo: runs on the fixture skill, exit 0" 0
for f in CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md .github/workflows/validate-skill.yml; do
  [[ -s "$RS/$f" ]] && ok "prepare-skill-repo writes $f from the templates" || bad "prepare-skill-repo writes $f from the templates" "missing or empty (templates not found?)"
done
SH="$TMP/skills-home"
mkdir -p "$SH/tiny/.git"
cp "$FX/tiny/SKILL.md" "$FX/tiny/CHANGELOG.md" "$SH/tiny/"
run_in "$PROJ" env SKILLS_HOME="$SH" "$PUBLISH/sync-individual-repos.sh" --dry-run --github-user tester tiny
check "sync-individual-repos: --dry-run on the fixture skill, exit 0" 0
for f in CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md .github/workflows/validate-skill.yml; do
  printf '%s' "$OUT" | grep -Fq "WOULD UPDATE  $f" && ok "sync-individual-repos announces $f from the templates" || bad "sync-individual-repos announces $f from the templates" "not announced (templates not found?)"
done
run_in "$PROJ" "$PUBLISH/apply-branch-protection.sh" --no-such-option
check "apply-branch-protection: unknown option exits non-zero" nonzero "" 'Unknown option'
for name in prepare-plugin validate-plugin validate-pre-sync sync-monorepo release-monorepo install-plugin prepare-skill-repo sync-individual-repos apply-branch-protection; do
  run_in "$PROJ" "$PUBLISH/$name.sh" --help
  check "$name: --help exits 0" 0 "Usage: $name\\.sh"
done

echo "release-monorepo.sh: main-only guard and --co-author (temp repo, bare remote, no network)"
# A bare remote and a clone with one plugin skill, committed and pushed on main. `gh` fails
# (the stub on CLEAN_PATH), so the GitHub release step only warns.
REL="$TMP/rel"
mkdir -p "$REL"
git init -q --bare "$REL/remote.git"
git -C "$REL/remote.git" symbolic-ref HEAD refs/heads/main
rel_git() { env -i PATH="$CLEAN_PATH" HOME="$TMP/home" GIT_CONFIG_NOSYSTEM=1 git -c user.name=T -c user.email=t@example.invalid -c commit.gpgsign=false -c tag.gpgsign=false "$@"; }
rel_clone() {
  rm -rf "$1"
  rel_git clone -q "$REL/remote.git" "$1" 2>/dev/null
  rel_git -C "$1" symbolic-ref HEAD refs/heads/main
}
rel_clone "$REL/seed"
mkdir -p "$REL/seed/plugins/pg/skills/one"
printf -- '---\nname: one\ndescription: "A fixture. Use when: (1) testing."\nmetadata:\n  version: 1.0.0\n---\n# One\n' > "$REL/seed/plugins/pg/skills/one/SKILL.md"
printf '# Changelog\n\n## [0.0.0] - 2026-01-01\n\nBaseline.\n' > "$REL/seed/CHANGELOG.md"
rel_git -C "$REL/seed" add -- CHANGELOG.md plugins
rel_git -C "$REL/seed" commit -q -m "feat: baseline"
rel_git -C "$REL/seed" push -q origin main
rel_run() { RC=0; OUT="$(cd "$PROJ" && env -i PATH="$CLEAN_PATH" HOME="$TMP/home" GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=T GIT_COMMITTER_EMAIL=t@example.invalid "$PUBLISH/release-monorepo.sh" --github-user tester "$@" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"; }

rel_clone "$REL/a"
rel_git -C "$REL/a" switch -q -c feature/x
rel_run patch "$REL/a"
check "on a feature branch: refuses, non-zero" nonzero "" 'not on main'
[[ -z "$(rel_git -C "$REL/a" tag -l)" && "$(rel_git -C "$REL/a" rev-list --count HEAD)" == 1 ]] \
  && ok "…before any commit or tag" || bad "…before any commit or tag" "tags: $(rel_git -C "$REL/a" tag -l), commits: $(rel_git -C "$REL/a" rev-list --count HEAD)"

rel_clone "$REL/b"
rel_clone "$REL/c"
printf 'more\n' >> "$REL/c/CHANGELOG.md"
rel_git -C "$REL/c" commit -q -am "docs: newer on origin"
rel_git -C "$REL/c" push -q origin main
rel_run patch "$REL/b"
check "main behind origin/main: refuses, non-zero" nonzero "" 'behind origin/main'
[[ -z "$(rel_git -C "$REL/b" tag -l)" && -z "$(rel_git --git-dir="$REL/remote.git" tag -l)" ]] \
  && ok "…before any commit or tag, locally or on the remote" || bad "…before any commit or tag, locally or on the remote" "local: $(rel_git -C "$REL/b" tag -l) remote: $(rel_git --git-dir="$REL/remote.git" tag -l)"

rel_clone "$REL/d"
rel_run --co-author "Co-Authored-By: Fixture Bot <bot@example.invalid>" patch "$REL/d"
check "on main, up to date: releases v0.0.1, exit 0" 0 'PUSHED'
rel_git --git-dir="$REL/remote.git" tag -l | grep -qx v0.0.1 && ok "…the tag reaches the remote" || bad "…the tag reaches the remote" "$(rel_git --git-dir="$REL/remote.git" tag -l)"
MSG="$(rel_git -C "$REL/d" log -1 --format=%B)"
printf '%s' "$MSG" | grep -qx 'Co-Authored-By: Fixture Bot <bot@example.invalid>' && ok "--co-author: the release commit ends with that line" || bad "--co-author: the release commit ends with that line" "$MSG"

rel_clone "$REL/e"
rel_run minor "$REL/e"
check "no --co-author: releases v0.1.0, exit 0" 0 'PUSHED'
MSG="$(rel_git -C "$REL/e" log -1 --format=%B)"
printf '%s' "$MSG" | grep -qi 'co-authored-by' && bad "no --co-author: no trailer" "$MSG" || ok "no --co-author: no trailer, and no model name"
printf '%s' "$MSG" | grep -q 'release: v0.1.0' && ok "…the commit is the release commit" || bad "…the commit is the release commit" "$MSG"
rel_clone "$REL/f"
rel_git -C "$REL/f" remote set-url origin "$REL/no-such-remote.git"
REFS_BEFORE="$(rel_git -C "$REL/f" for-each-ref)"
rel_run --dry-run patch "$REL/f"
check "--dry-run with an unreachable origin still previews, exit 0" 0 'Dry run complete'
[[ "$(rel_git -C "$REL/f" for-each-ref)" == "$REFS_BEFORE" && -z "$(rel_git -C "$REL/f" status --porcelain)" ]] \
  && ok "…and writes no refs and no files" || bad "…and writes no refs and no files" "$(rel_git -C "$REL/f" for-each-ref; rel_git -C "$REL/f" status --porcelain)"
grep -q 'Opus 4.6' "$PUBLISH/release-monorepo.sh" && bad "release-monorepo.sh hard-codes no model name" "found Opus 4.6" || ok "release-monorepo.sh hard-codes no model name"

echo "every script named in a SKILL.md exists, is executable and answers --help"
# Pull each "${CLAUDE_SKILL_DIR}/scripts/<name>" out of a SKILL.md, resolve it against that
# skill's directory in the plugin copy, and run it with --help from the project dir.
for skill in author publish extract; do
  names="$(python3 - "$SKILLS/$skill/SKILL.md" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
seen = []
for m in re.finditer(r'"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_.-]+\.(?:sh|py))"', text):
    if m.group(1) not in seen:
        seen.append(m.group(1))
print("\n".join(seen))
EOF
)"
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

echo "author and extract never show the substituted path tokens in prose"
# Claude Code replaces "${CLAUDE_SKILL_DIR}" and "${CLAUDE_PLUGIN_ROOT}" everywhere in a SKILL.md,
# prose and inline code included, before the model reads it. In a fenced code block the token is a
# real command for this skill's own scripts, which is what we want. Outside one it is usually advice
# about what to write in a NEW skill, and the model would read (and copy) this skill's absolute path.
# So outside fenced blocks these two skills (the ones that write skills) must not contain the token.
for skill in author extract; do
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
)"
  [[ -z "$hits" ]] && ok "$skill SKILL.md: no path token outside code blocks" \
    || bad "$skill SKILL.md: path token outside a code block (it is substituted, so the model sees an absolute path)" "$hits"
done

echo "find-skills.sh (extract Step 1)"
FS="$EXTRACT/find-skills.sh"
S1HOME="$TMP/s1home"
mkdir -p "$S1HOME/.claude/plugins" "$S1HOME/.claude/skills/user-skill" "$TMP/repo/src" "$TMP/repo2" "$TMP/other" "$TMP/inst-repo/skills/plug-skill"
printf -- '---\nname: user-skill\n---\nFixes the frobnicate timeout.\n' > "$S1HOME/.claude/skills/user-skill/SKILL.md"
printf -- '---\nname: plug-skill\n---\nNothing to see.\n' > "$TMP/inst-repo/skills/plug-skill/SKILL.md"
printf '{"plugins":{"p@m":[{"scope":"project","projectPath":"%s","installPath":"%s"}]}}\n' "$TMP/repo" "$TMP/inst-repo" > "$S1HOME/.claude/plugins/installed_plugins.json"
# An rg stub that prints its arguments, one per line, so the tests see exactly what would be searched.
mkdir -p "$TMP/s1bin"; printf '#!/bin/sh\nprintf "%%s\\n" "$@"\n' > "$TMP/s1bin/rg"; chmod +x "$TMP/s1bin/rg"
fs_from() { local dir="$1"; shift; RC=0; OUT="$(cd "$dir" && env -i PATH="$TMP/s1bin:$CLEAN_PATH" HOME="$S1HOME" "$FS" "$@" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"; }
fs_from "$TMP/repo" --dirs
printf '%s' "$OUT" | grep -qxF "$TMP/inst-repo" && ok "--dirs: searches a project install from the project root" || bad "--dirs: project root misses the install" "$OUT"
printf '%s' "$OUT" | grep -qxF "$S1HOME/.claude/skills" && ok "--dirs: searches ~/.claude/skills" || bad "--dirs: misses ~/.claude/skills" "$OUT"
fs_from "$TMP/repo/src" --dirs
printf '%s' "$OUT" | grep -qxF "$TMP/inst-repo" && ok "--dirs: searches a project install from a subdirectory" || bad "--dirs: subdirectory misses the project install" "$OUT"
fs_from "$TMP/other" --dirs
printf '%s' "$OUT" | grep -qxF "$TMP/inst-repo" && bad "--dirs: searched another project's install" "$OUT" || ok "--dirs: skips a project install from an unrelated directory"
fs_from "$TMP/repo2" --dirs
printf '%s' "$OUT" | grep -qxF "$TMP/inst-repo" && bad "--dirs: /repo matched /repo2 (prefix trap)" "$OUT" || ok "--dirs: projectPath /repo does not match /repo2"
fs_from "$TMP/repo"
[[ "$RC" == 0 && "$(printf '%s\n' "$OUT" | head -3)" == "$(printf -- '--files\n-g\nSKILL.md')" ]] && ok "no arguments: lists SKILL.md files" || bad "no arguments: lists SKILL.md files" "$OUT"
fs_from "$TMP/repo" -F "exact error"
[[ "$(printf '%s\n' "$OUT" | head -2)" == "$(printf -- '-F\nexact error')" ]] && printf '%s' "$OUT" | grep -qxF "$TMP/inst-repo" \
  && ok "arguments go to rg, then every skill directory" || bad "arguments go to rg, then every skill directory" "$OUT"
fs_from "$TMP/repo" --help
check "--help exits 0" 0 'Usage: find-skills\.sh'
RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="/usr/bin:/bin" HOME="$S1HOME" "$FS" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
if [[ -x /usr/bin/rg || -x /bin/rg ]]; then
  echo "  SKIP  a missing rg exits 2 (rg is in /usr/bin or /bin here)"
else
  check "a missing rg exits 2" 2 "" 'ripgrep \(rg\) is not installed'
fi
RC=0; OUT="$(cd "$TMP/other" && env -i PATH="$TMP/s1bin:$CLEAN_PATH" HOME="$TMP/empty-home" "$FS" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
check "no skill directory exits 2" 2 "" 'no skill directories found'
mkdir -p "$TMP/s1bad"; printf '#!/bin/sh\necho "regex parse error" >&2\nexit 2\n' > "$TMP/s1bad/rg"; chmod +x "$TMP/s1bad/rg"
RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="$TMP/s1bad:$CLEAN_PATH" HOME="$S1HOME" "$FS" -e "(" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
check "an rg error (rg exits 2) exits 3, not 2 or 1" 3 "" 'the search failed'
printf '%s' "$ERR" | grep -q 'regex parse error' && ok "rg's own error reaches stderr" || bad "rg's own error reaches stderr" "$ERR"
if command -v rg >/dev/null; then
  RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="$CLEAN_PATH" HOME="$S1HOME" "$FS" -i "FROBNICATE" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
  check "real rg: a keyword search finds the user skill, exit 0" 0 'user-skill/SKILL.md'
  RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="$CLEAN_PATH" HOME="$S1HOME" "$FS" -F "no such text anywhere" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
  check "real rg: no match exits 1" 1
  RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="$CLEAN_PATH" HOME="$S1HOME" "$FS" -e "(" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
  check "real rg: a bad regex exits 3" 3 "" 'the search failed'
  RC=0; OUT="$(cd "$TMP/repo" && env -i PATH="$CLEAN_PATH" HOME="$S1HOME" "$FS" 2>"$TMP/err")" || RC=$?; ERR="$(cat "$TMP/err")"
  printf '%s' "$OUT" | grep -q 'plug-skill/SKILL.md' && printf '%s' "$OUT" | grep -q 'user-skill/SKILL.md' \
    && ok "real rg: lists the user and the plugin skill" || bad "real rg: lists the user and the plugin skill" "$OUT"
else
  echo "  SKIP  real rg searches (rg is not installed here)"
fi
grep -q 'installed_plugins.json' "$SKILLS/extract/SKILL.md" && grep -q 'python3 -' "$SKILLS/extract/SKILL.md" \
  && bad "extract SKILL.md no longer carries the inline Step 1 script" "found it" || ok "extract SKILL.md no longer carries the inline Step 1 script"

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
