#!/usr/bin/env bash
set -euo pipefail

# test-ci-skill-detect.sh — tests for the "Detect changed skill directories" and
# "Validate changed skills" steps of the validate-skills job (#167).
#
# The steps are `run:` blocks inside a workflow file. This test pulls the
# blocks out of the YAML text and runs them in a fixture git repo, so the
# regexes that CI uses are the ones under test. It checks both copies of the
# workflow: the repo's own and the template that skill-kit:publish writes out.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PYTHONDONTWRITEBYTECODE=1

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }

# extract_step <workflow> <step name> <out file>: the step's `run: |` body, de-indented.
extract_step() {
  python3 - "$1" "$2" "$3" <<'PY'
import re, sys
wf, name, out = sys.argv[1:4]
lines = open(wf).read().split("\n")
i = next(n for n, l in enumerate(lines) if l.strip() == "- name: " + name)
j = next(n for n in range(i, len(lines)) if lines[n].strip() == "run: |")
base = len(lines[j]) - len(lines[j].lstrip()) + 2
body = []
for l in lines[j + 1:]:
    if l.strip() and len(l) - len(l.lstrip()) < base:
        break
    body.append(l[base:])
open(out, "w").write("\n".join(body) + "\n")
PY
}

# new_repo <dir>: a git repo whose origin/main is a commit with one top-level old skill,
# one plugin skill "pg/skills/gone" and one plugin skill "pg/skills/kept"; HEAD then changes them.
new_repo() {
  local r="$1"
  mkdir -p "$r"
  (
    cd "$r"
    git init -q . && git config user.email t@t && git config user.name t
    mkdir -p old plugins/pg/skills/gone plugins/pg/skills/kept plugins/pg/skills/nomd scripts
    echo x > old/SKILL.md; echo x > plugins/pg/skills/gone/SKILL.md; echo x > plugins/pg/skills/kept/SKILL.md
    echo x > plugins/pg/README.md
    printf '#!/usr/bin/env bash\necho "validated $1"\n' > scripts/validate-skill.sh; chmod +x scripts/validate-skill.sh
    git add -A && git commit -q -m base
    git update-ref refs/remotes/origin/main HEAD
    git checkout -q -b change
    echo y >> old/SKILL.md                                   # top-level: no longer scanned
    echo y >> plugins/pg/README.md                            # plugin file outside a skill: not a skill dir
    mkdir -p plugins/pg/skills/kept/scripts
    echo y > plugins/pg/skills/kept/scripts/run.sh            # inside a plugin skill
    git rm -q -r plugins/pg/skills/gone                       # skill removed in the PR
    echo y > plugins/pg/skills/nomd/notes.txt                 # skill dir with no SKILL.md
    git add -A && git commit -q -m change
  )
}

for WF in "$REPO_ROOT/.github/workflows/validate-skill.yml" "$REPO_ROOT/plugins/skill-kit/skills/publish/references/workflow-monorepo.yml"; do
  LABEL="${WF#"$REPO_ROOT"/}"
  echo "$LABEL"
  W="$TMP/$(printf '%s' "$LABEL" | tr '/.' '__')"; mkdir -p "$W"
  extract_step "$WF" "Detect changed skill directories" "$W/detect.sh"
  extract_step "$WF" "Validate changed skills" "$W/validate.sh"
  new_repo "$W/repo"

  : > "$W/gh_out"
  DET_OUT="$(cd "$W/repo" && GITHUB_OUTPUT="$W/gh_out" bash "$W/detect.sh" 2>&1)" && DET_RC=0 || DET_RC=$?
  DIRS="$(sed -n '/^dirs<<EOF$/,/^EOF$/p' "$W/gh_out" | sed '1d;$d')"
  [[ $DET_RC -eq 0 ]] && ok "detect step exits 0" || bad "detect step exits 0" "$DET_OUT"
  EXPECT="$(printf '%s\n' plugins/pg/skills/gone plugins/pg/skills/kept plugins/pg/skills/nomd)"
  [[ "$DIRS" == "$EXPECT" ]] && ok "detect lists the three changed plugin skill dirs, not old/ or the plugin README" || bad "detect lists the three changed plugin skill dirs, not old/ or the plugin README" "got: $DIRS"

  # Only a top-level change: the old regex matched it, the new one must not.
  new_repo "$W/repo2"
  (cd "$W/repo2" && git reset -q --hard origin/main && echo z >> old/SKILL.md && git commit -q -am top)
  : > "$W/gh_out2"
  (cd "$W/repo2" && GITHUB_OUTPUT="$W/gh_out2" bash "$W/detect.sh" >/dev/null 2>&1) || true
  grep -q '^dirs=$' "$W/gh_out2" && ok "a change to a top-level skill dir is not a skill change" || bad "a change to a top-level skill dir is not a skill change" "$(cat "$W/gh_out2")"

  # Validate step: removed dir is fine, a dir without SKILL.md is an error, a real skill is validated.
  VAL_OUT="$(cd "$W/repo" && DIRS="$DIRS" bash "$W/validate.sh" 2>&1)" && VAL_RC=0 || VAL_RC=$?
  [[ $VAL_RC -eq 1 ]] && ok "validate step fails when a changed skill dir has no SKILL.md" || bad "validate step fails when a changed skill dir has no SKILL.md" "rc=$VAL_RC $VAL_OUT"
  [[ "$VAL_OUT" == *"plugins/pg/skills/nomd"*"no SKILL.md"* ]] && ok "the error names the dir" || bad "the error names the dir" "$VAL_OUT"
  [[ "$VAL_OUT" == *"validated plugins/pg/skills/kept"* ]] && ok "an existing skill is validated" || bad "an existing skill is validated" "$VAL_OUT"
  [[ "$VAL_OUT" == *"removed"*"plugins/pg/skills/gone"* || "$VAL_OUT" == *"plugins/pg/skills/gone"*"removed"* ]] && ok "a removed skill dir is skipped with a note, not an error" || bad "a removed skill dir is skipped with a note, not an error" "$VAL_OUT"
  VAL_OUT="$(cd "$W/repo" && DIRS="$(printf '%s\n' plugins/pg/skills/gone plugins/pg/skills/kept)" bash "$W/validate.sh" 2>&1)" && VAL_RC=0 || VAL_RC=$?
  [[ $VAL_RC -eq 0 ]] && ok "removed plus valid skills: validate step passes" || bad "removed plus valid skills: validate step passes" "rc=$VAL_RC $VAL_OUT"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
