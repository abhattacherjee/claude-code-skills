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
run_in "$PROJ" "$PUBLISH/apply-branch-protection.sh" --no-such-option
check "apply-branch-protection: unknown option exits non-zero" nonzero "" 'Unknown option'
for name in prepare-plugin validate-plugin validate-pre-sync sync-monorepo release-monorepo install-plugin prepare-skill-repo sync-individual-repos apply-branch-protection; do
  run_in "$PROJ" "$PUBLISH/$name.sh" --help
  check "$name: --help exits 0" 0 "Usage: $name\\.sh"
done

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
  # extract's SKILL.md names no script today; the others must name at least one.
  if [[ "$skill" == extract ]]; then
    ok "extract SKILL.md: $n script command(s) checked"
  else
    [[ "$n" -ge 1 ]] && ok "$skill SKILL.md: found $n script command(s) to run" || bad "$skill SKILL.md: found no script commands to run" "the extractor matched nothing"
  fi
done

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
