#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts of the dev-flow plugin.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a temp
# project directory (never the skill directory), in a clean environment (`env -i`,
# so nothing leaks in from the caller's shell). HOME points at a temp dir, and git
# gets a fixed identity and no system config. The plugin is copied to a path with a
# space first, so a script that finds its files relative to its own location, or does
# not quote a path, fails here. Needs bash 3.2+, git, python3 (standard library). Nothing
# here touches the network or anything outside the temp dir.
#
# Usage: bash plugins/dev-flow/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy" "$TMP/home" "$TMP/proj" "$TMP/work"
cp -R "$PLUGIN/skills" "$TMP/plugin copy/skills"
# DEVFLOW_SKILLS may be set by the caller to test another copy of the skills.
SKILLS="${DEVFLOW_SKILLS:-$TMP/plugin copy/skills}"
echo "skills under test: $SKILLS"

WT="$SKILLS/worktree/scripts/setup-worktree.sh"
CL="$SKILLS/changelog/scripts/update-changelog.sh"
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

# gitc <dir> <git args...>: run git in <dir> and stop the suite if it fails (test setup).
gitc() {
  local dir="$1"
  shift
  (cd "$dir" && cenv git "$@" >/dev/null 2>&1) || { echo "setup failed: git $* in $dir" >&2; exit 1; }
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

# has <label> <file> <fixed-string>: the file contains the text.
has()  { grep -Fq -- "$3" "$2" && ok "$1" || bad "$1" "no '$3' in $2"; }
# lacks <label> <file> <fixed-string>: the file does not contain the text.
lacks() { grep -Fq -- "$3" "$2" && bad "$1" "found '$3' in $2" || ok "$1"; }

# newrepo <dir>: an empty git repo on branch main (the dir is removed first).
newrepo() {
  rm -rf "$1"
  mkdir -p "$1"
  gitc "$1" init -q
  gitc "$1" symbolic-ref HEAD refs/heads/main
}

# py_ok <label> <script.py> <args...>: run a python check. The script prints its problems,
# one per line, and nothing when all is well. A python error or crash is a FAIL line, never an
# abort of the suite (set -e).
py_ok() {
  local label="$1" res rc=0
  shift
  res="$(python3 "$@" 2>&1)" || rc=$?
  if [[ "$rc" != 0 ]]; then
    bad "$label" "python check exited $rc: $res"
  elif [[ -n "$res" ]]; then
    bad "$label" "$res"
  else
    ok "$label"
  fi
}

# The python helpers below are read from these files by py_ok.
PYDIR="$TMP/py"
mkdir -p "$PYDIR"
# subseq.py <old> <new>: every line of <old> is in <new>, in order.
cat > "$PYDIR/subseq.py" <<'EOF'
import sys
old = open(sys.argv[1], encoding="utf-8").read().split("\n")
new = open(sys.argv[2], encoding="utf-8").read().split("\n")
j = 0
for i, line in enumerate(old):
    while j < len(new) and new[j] != line:
        j += 1
    if j == len(new):
        print("line %d of the old file is gone or out of order: %r" % (i + 1, line))
        break
    j += 1
EOF
# under.py <file> <heading> <line>...: each <line> sits in the section that starts with the
# line <heading> (exact), before the next line that starts with the same number of '#'.
cat > "$PYDIR/under.py" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
head = sys.argv[2]
level = len(head) - len(head.lstrip("#"))
if head not in lines:
    print("no heading %r" % head)
    sys.exit(0)
start = lines.index(head)
end = len(lines)
for i in range(start + 1, len(lines)):
    l = lines[i]
    n = len(l) - len(l.lstrip("#"))
    if 1 <= n <= level and l[n:n + 1] == " ":
        end = i
        break
block = lines[start + 1:end]
for want in sys.argv[3:]:
    if want not in block:
        print("%r is not under %r (section: %r)" % (want, head, block))
EOF
# md.py <file>: every heading has a blank line before it, and the file ends with one newline.
cat > "$PYDIR/md.py" <<'EOF'
import re, sys
raw = open(sys.argv[1], encoding="utf-8").read()
lines = raw.split("\n")
for i, l in enumerate(lines):
    if re.match(r"#{2,3} ", l) and i > 0 and lines[i - 1].strip() != "":
        print("line %d: heading %r has no blank line before it" % (i + 1, l))
if not raw.endswith("\n") or raw.endswith("\n\n"):
    print("the file does not end with exactly one newline")
EOF
# subseq/under/md wrappers. `under` reads OUT when the file is "-".
subseq() { py_ok "$1" "$PYDIR/subseq.py" "$2" "$3"; }
under() {
  local label="$1" file="$2"
  shift 2
  if [[ "$file" == - ]]; then
    printf '%s\n' "$OUT" > "$TMP/out.txt"
    file="$TMP/out.txt"
  fi
  py_ok "$label" "$PYDIR/under.py" "$file" "$@"
}
mdok() { py_ok "$1" "$PYDIR/md.py" "$2"; }

# The scripts start with `#!/usr/bin/env bash`. EXPECT_BASH_MAJOR (set by CI) pins the version.
echo "bash under test: $BASH_VERSION"
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

echo "validate-skill.sh (each skill ships the repo-root validator)"
ROOT_VALIDATOR="$PLUGIN/../../scripts/validate-skill.sh"
for skill in worktree changelog; do
  if [[ -f "$ROOT_VALIDATOR" ]]; then
    cmp -s "$ROOT_VALIDATOR" "$SKILLS/$skill/scripts/validate-skill.sh" && ok "$skill: validate-skill.sh is byte-identical to the repo-root copy" || bad "$skill: validate-skill.sh is byte-identical to the repo-root copy" "they differ"
  else
    # A skipped check reads as a pass, so a missing root validator fails the run.
    bad "$skill: validate-skill.sh can be compared with the repo-root copy" "no scripts/validate-skill.sh at $ROOT_VALIDATOR (run the tests from a checkout of the repo)"
  fi
  run_in "$PROJ" "$SKILLS/$skill/scripts/validate-skill.sh" "$SKILLS/$skill"
  check "$skill: validate-skill.sh passes on its own skill" 0 'Result: PASS'
done

# ---------------------------------------------------------------------------
echo "setup-worktree.sh (worktree)"
# origin (bare) <- repo (develop). Worktrees are siblings of the repo, so they land in $TMP/work.
gitc "$TMP" init -q --bare "$TMP/origin.git"
REPO="$TMP/work/repo"
mkdir -p "$REPO"
gitc "$REPO" init -q
gitc "$REPO" symbolic-ref HEAD refs/heads/develop
echo hi > "$REPO/a.txt"
gitc "$REPO" add a.txt
gitc "$REPO" commit -q -m "chore: init"
gitc "$REPO" remote add origin "$TMP/origin.git"
gitc "$REPO" push -q origin develop
gitc "$REPO" branch feature/old develop

run_in "$REPO" "$WT" list
check "list exits 0 and shows the worktrees" 0 'Existing Worktrees'
run_in "$REPO" "$WT" create --new demo
check "create --new exits 0 and prints the cd line" 0 "cd $TMP/work/repo--demo && claude"
[[ -d "$TMP/work/repo--demo" ]] && ok "create --new makes the worktree directory" || bad "create --new makes the worktree directory" "missing $TMP/work/repo--demo"
(cd "$REPO" && cenv git show-ref --verify --quiet refs/heads/feature/demo) && ok "create --new adds the feature/ prefix to the branch" || bad "create --new adds the feature/ prefix to the branch" "no feature/demo"
run_in "$REPO" "$WT" list
check "list shows the new worktree against its branch" 0 'feature/demo  \[worktree: '
run_in "$REPO" "$WT" create --new demo
check "create twice exits 0 and says the worktree exists" 0 'Worktree already exists'
run_in "$REPO" "$WT" create feature/old
check "create for an existing branch exits 0" 0 "cd $TMP/work/repo--old && claude"
[[ -d "$TMP/work/repo--old" ]] && ok "create for an existing branch makes the worktree directory" || bad "create for an existing branch makes the worktree directory" "missing $TMP/work/repo--old"
run_in "$REPO" "$WT" remove feature/demo
check "remove exits 0" 0 'Worktree removed'
[[ ! -d "$TMP/work/repo--demo" ]] && ok "remove deletes the worktree directory" || bad "remove deletes the worktree directory" "$TMP/work/repo--demo is still there"
(cd "$REPO" && cenv git show-ref --verify --quiet refs/heads/feature/demo) && ok "remove keeps the branch" || bad "remove keeps the branch" "feature/demo is gone"
run_in "$REPO" "$WT" remove feature/old
check "remove of the second worktree exits 0" 0 'Worktree removed'

echo "setup-worktree.sh: bad input"
run_in "$REPO" "$WT" frobnicate
check "an unknown command exits 2 with a message" 2 "" "Unknown command 'frobnicate'"
run_in "$REPO" "$WT" remove feature/none
check "remove of a branch with no worktree exits non-zero with a message" nonzero "" 'Worktree not found'
run_in "$REPO" "$WT" create
check "create with no branch exits non-zero with a message" nonzero "" 'Branch name required'
run_in "$REPO" "$WT" create feature/missing
check "create for a branch that does not exist exits non-zero with a message" nonzero "" "Branch 'feature/missing' not found"
mkdir -p "$TMP/notrepo"
run_in "$TMP/notrepo" "$WT" list
check "outside a git repo, list exits non-zero with a message" nonzero "" 'Not in a git repository'
run_in "$PROJ" "$WT" --help
check "--help exits 0 and shows usage" 0 'Usage: setup-worktree.sh'
check "--help documents remove --force" 0 'remove <branch> \[--force\]'
for f in "$WT" "$SKILLS/worktree/SKILL.md"; do
  grep -Eq 'mcp-events-server|backend|frontend' "$f" && bad "$(basename "$f") names no project-specific package directory" "$(grep -En 'mcp-events-server|backend|frontend' "$f" | head -2)" || ok "$(basename "$f") names no project-specific package directory"
done

echo "setup-worktree.sh: remove keeps uncommitted work unless --force"
run_in "$REPO" "$WT" create --new dirty --no-install
check "create --new dirty exits 0" 0
echo "precious" > "$TMP/work/repo--dirty/unsaved.txt"
run_in "$REPO" "$WT" remove feature/dirty
check "remove of a worktree with an untracked file exits non-zero and says why" nonzero "" 'untracked|modified|--force'
[[ -f "$TMP/work/repo--dirty/unsaved.txt" ]] && ok "the refused remove keeps the uncommitted file" || bad "the refused remove keeps the uncommitted file" "it is gone"
run_in "$REPO" "$WT" remove --force feature/dirty
check "remove --force exits 0" 0 'Worktree removed'
[[ ! -e "$TMP/work/repo--dirty" ]] && ok "remove --force deletes the worktree directory" || bad "remove --force deletes the worktree directory" "still there"
run_in "$REPO" git worktree list
printf '%s' "$OUT" | grep -Fq 'repo--dirty' && bad "git worktree list no longer lists the removed worktree" "$OUT" || ok "git worktree list no longer lists the removed worktree"

echo "setup-worktree.sh: worktrees are found by branch, not by directory name"
run_in "$REPO" "$WT" create --new x/y --no-install
check "create --new x/y exits 0 (directory repo--x-y)" 0
gitc "$REPO" branch feature/x-y develop
run_in "$REPO" "$WT" create feature/x-y --no-install
check "create for feature/x-y, whose directory is feature/x/y's worktree, exits non-zero" nonzero "" 'already exists'
[[ "$(cd "$TMP/work/repo--x-y" && cenv git branch --show-current)" == feature/x/y ]] && ok "the x/y worktree is untouched" || bad "the x/y worktree is untouched" "branch changed"
echo "unsaved" > "$TMP/work/repo--x-y/u.txt"
run_in "$REPO" "$WT" remove feature/x-y
check "remove feature/x-y (no worktree of its own) exits non-zero" nonzero "" 'Worktree not found'
[[ -f "$TMP/work/repo--x-y/u.txt" ]] && ok "remove feature/x-y leaves feature/x/y's worktree alone" || bad "remove feature/x-y leaves feature/x/y's worktree alone" "it was removed"
run_in "$REPO" "$WT" remove --force feature/x/y
check "remove --force feature/x/y exits 0" 0
mkdir -p "$TMP/work/repo--plain"
run_in "$REPO" "$WT" create --new plain --no-install
check "create --new into a plain directory that is in the way exits non-zero" nonzero "" 'already exists'
(cd "$REPO" && cenv git show-ref --verify --quiet refs/heads/feature/plain) && bad "the refused create makes no branch" "feature/plain exists" || ok "the refused create makes no branch"

echo "setup-worktree.sh: the base of a new branch"
# Local develop is one commit ahead of origin/develop: the new branch must start at origin/develop.
gitc "$REPO" commit -q --allow-empty -m "chore: local only"
ORIGIN_DEV="$(cd "$REPO" && cenv git rev-parse origin/develop)"
run_in "$REPO" "$WT" create --new based --no-install
check "create --new with origin/develop exits 0" 0
[[ "$(cd "$REPO" && cenv git rev-parse feature/based)" == "$ORIGIN_DEV" ]] && ok "the new branch starts at origin/develop, not the local develop ahead of it" || bad "the new branch starts at origin/develop" "$(cd "$REPO" && cenv git log --oneline -2 feature/based)"
(cd "$REPO" && cenv git rev-parse --abbrev-ref 'feature/based@{upstream}' >/dev/null 2>&1) && bad "the new branch has no upstream (--no-track)" "it tracks $(cd "$REPO" && cenv git rev-parse --abbrev-ref 'feature/based@{upstream}')" || ok "the new branch has no upstream (--no-track)"
run_in "$REPO" "$WT" remove feature/based
# A fetch that fails is reported, not hidden.
gitc "$REPO" remote set-url origin "$TMP/no-such-origin.git"
run_in "$REPO" "$WT" create --new stale --no-install
check "a failed fetch still creates the branch" 0
printf '%s' "$ERR" | grep -q 'WARNING.*fetch' && ok "a failed fetch prints a warning" || bad "a failed fetch prints a warning" "stderr: $ERR"
gitc "$REPO" remote set-url origin "$TMP/origin.git"
run_in "$REPO" "$WT" remove feature/stale
# A remote-only branch.
gitc "$REPO" branch feature/remote develop
gitc "$REPO" push -q origin feature/remote
gitc "$REPO" branch -D feature/remote
run_in "$REPO" "$WT" create feature/remote --no-install
check "create for a branch that only exists on origin exits 0" 0 'remote branch'
[[ "$(cd "$TMP/work/repo--remote" && cenv git branch --show-current)" == feature/remote ]] && ok "the remote-only branch is checked out in its worktree" || bad "the remote-only branch is checked out in its worktree" "wrong branch"
run_in "$REPO" "$WT" remove feature/remote

# A repo with only main, no origin.
MO="$TMP/work/mainonly"
newrepo "$MO"
gitc "$MO" commit -q --allow-empty -m "chore: init"
run_in "$MO" "$WT" create --new q --no-install
check "a main-only repo with no origin: create --new exits 0" 0 'from main'
[[ "$(cd "$MO" && cenv git rev-parse feature/q)" == "$(cd "$MO" && cenv git rev-parse main)" ]] && ok "a main-only repo: the new branch starts at main" || bad "a main-only repo: the new branch starts at main" ""
# A clone whose origin has main only: origin/HEAD names the base.
gitc "$TMP" init -q --bare "$TMP/origin-main.git"
gitc "$TMP/origin-main.git" symbolic-ref HEAD refs/heads/main
gitc "$MO" remote add origin "$TMP/origin-main.git"
gitc "$MO" push -q origin main
gitc "$TMP/work" clone -q "$TMP/origin-main.git" "$TMP/work/clone"
run_in "$TMP/work/clone" "$WT" create --new c --no-install
check "a clone with no develop: create --new starts from origin/HEAD's branch" 0 'from origin/main'
# No base at all: a repo on another branch with no develop, main or origin.
NB="$TMP/work/nobase"
mkdir -p "$NB"
gitc "$NB" init -q
gitc "$NB" symbolic-ref HEAD refs/heads/trunk
gitc "$NB" commit -q --allow-empty -m "chore: init"
run_in "$NB" "$WT" create --new z --no-install
check "no develop, origin or main: create --new exits non-zero with a message" nonzero "" 'No base branch'

echo "setup-worktree.sh: dependency install"
FAKE="$TMP/fakebin"
mkdir -p "$FAKE"
printf '#!/bin/sh\necho "npm boom" >&2\nexit 1\n' > "$FAKE/npm"
chmod +x "$FAKE/npm"
NP="$TMP/work/npmrepo"
newrepo "$NP"
echo '{}' > "$NP/package.json"
mkdir -p "$NP/web"
echo '{}' > "$NP/web/package.json"
gitc "$NP" add package.json web/package.json
gitc "$NP" commit -q -m "chore: init"
run_in "$NP" env PATH="$FAKE:$PATH" "$WT" create --new fails
check "npm install failing: create exits 1" 1 "" 'npm install failed'
check "npm install failing: the cd line is still printed" 1 "cd .*npmrepo--fails && claude"
printf '%s' "$OUT" | grep -q 'Installed dependencies' && bad "npm install failing: no 'Installed' success line" "$OUT" || ok "npm install failing: no 'Installed' success line"
printf '%s' "$ERR" | grep -Fq 'web' && ok "npm install failing: the failed package is named" || bad "npm install failing: the failed package is named" "$ERR"
printf '#!/bin/sh\nmkdir node_modules\nexit 0\n' > "$FAKE/npm"
run_in "$NP" env PATH="$FAKE:$PATH" "$WT" create --new works
check "npm install in the repo root and each subdirectory with a package.json: 2 packages" 0 'Installed dependencies in 2 package'
run_in "$NP" env PATH="$FAKE:$PATH" "$WT" install feature/works
check "install again: every package already has node_modules" 0 'already have node_modules'

echo "setup-worktree.sh: printed commands work when pasted, even with a space in the path"
SPR="$TMP/work/sp ace/proj"
newrepo "$SPR"
gitc "$SPR" commit -q --allow-empty -m "chore: init"
gitc "$SPR" branch feature/y
run_in "$SPR" "$WT" create feature/y --no-install
check "a repo under a path with a space: create exits 0" 0
line="$(printf '%s\n' "$OUT" | grep -E '^  cd .* && claude$' | head -1 | sed 's/^  //; s/ && claude$//')"
got="$(cd "$PROJ" && bash -c "$line && pwd -P" 2>&1 || true)"
[[ "$got" == "$TMP/work/sp ace/proj--y" ]] && ok "the printed cd line, pasted into a shell, lands in the worktree" || bad "the printed cd line, pasted into a shell, lands in the worktree" "line: $line -> $got"

# ---------------------------------------------------------------------------
echo "update-changelog.sh (changelog)"
CR="$TMP/work/clrepo"
mkdir -p "$CR"
gitc "$CR" init -q
gitc "$CR" symbolic-ref HEAD refs/heads/main
cat > "$CR/CHANGELOG.md" <<'EOF'
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- a hand-written note

## [1.0.0] - 2026-01-01

### Added

- first release
EOF
gitc "$CR" add CHANGELOG.md
gitc "$CR" commit -q -m "chore: init"
gitc "$CR" tag v1.0.0
gitc "$CR" commit -q --allow-empty -m "feat: add widget"
gitc "$CR" commit -q --allow-empty -m "fix(core): stop the crash"
gitc "$CR" commit -q --allow-empty -m "docs: update the guide"
gitc "$CR" commit -q --allow-empty -m 'fix: keep \n and \t literal in subjects'
# A newer tag that is not a version. `git describe` would pick it as the starting point.
gitc "$CR" tag sync-2026-10-01

before="$(cksum < "$CR/CHANGELOG.md")"
run_in "$CR" "$CL" --dry-run
check "--dry-run exits 0 and starts from the last version tag, not the newer sync tag" 0 'changes since tag v1.0.0'
check "--dry-run puts the feat commit under Added" 0 '### Added'
printf '%s' "$OUT" | grep -Fq -- '- add widget' && ok "--dry-run lists 'add widget'" || bad "--dry-run lists 'add widget'" "$OUT"
printf '%s' "$OUT" | grep -Eq '### Fixed' && ok "--dry-run has a Fixed section" || bad "--dry-run has a Fixed section" "$OUT"
printf '%s' "$OUT" | grep -Fq -- '- stop the crash' && ok "--dry-run strips the scope from 'fix(core):'" || bad "--dry-run strips the scope from 'fix(core):'" "$OUT"
printf '%s' "$OUT" | grep -Fq 'fix(core)' && bad "--dry-run drops the 'fix(core):' prefix" "found it" || ok "--dry-run drops the 'fix(core):' prefix"
printf '%s' "$OUT" | grep -Fq '### Documentation' && ok "--dry-run has a Documentation section" || bad "--dry-run has a Documentation section" "$OUT"
printf '%s' "$OUT" | grep -Fq -- 'keep \n and \t literal in subjects' && ok "--dry-run shows backslashes in a subject as typed" || bad "--dry-run shows backslashes in a subject as typed" "$OUT"
[[ "$(cksum < "$CR/CHANGELOG.md")" == "$before" ]] && ok "--dry-run leaves CHANGELOG.md byte-identical" || bad "--dry-run leaves CHANGELOG.md byte-identical" "checksum changed"
printf '%s' "$OUT" | grep -Fq 'Dry run' && ok "--dry-run says nothing was written" || bad "--dry-run says nothing was written" "$OUT"

chmod 640 "$CR/CHANGELOG.md"
cp "$CR/CHANGELOG.md" "$TMP/cr-before.md"
run_in "$CR" "$CL"
check "write mode exits 0" 0 'Updated '
CLOG="$CR/CHANGELOG.md"
under "write mode puts every new bullet in the [Unreleased] block" "$CLOG" '## [Unreleased]' \
  '- add widget' '- stop the crash' '- update the guide' '- keep \n and \t literal in subjects'
under "write mode keeps the hand-written bullet, in its own ### Added" "$CLOG" '### Added' '- a hand-written note' '- add widget'
[[ "$(grep -c '^## \[Unreleased\]' "$CLOG")" == 1 ]] && ok "write mode leaves one [Unreleased] heading" || bad "write mode leaves one [Unreleased] heading" "$(grep -n '^## ' "$CLOG")"
[[ "$(grep -c '^### Added' "$CLOG")" == 2 ]] && ok "write mode adds to the existing ### Added, it does not add a second one" || bad "write mode adds to the existing ### Added" "$(grep -n '^##' "$CLOG")"
subseq "write mode keeps every line of the old file, in order" "$TMP/cr-before.md" "$CLOG"
mdok "write mode keeps the Markdown intact (blank line before headings, one final newline)" "$CLOG"
[[ "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$CLOG")" == 0o640 ]] && ok "write mode keeps the file mode of CHANGELOG.md" || bad "write mode keeps the file mode of CHANGELOG.md" "mode changed"
[[ -z "$(ls -A "$CR" | grep -F '.CHANGELOG.' || true)" ]] && ok "write mode leaves no temp file behind" || bad "write mode leaves no temp file behind" "$(ls -A "$CR")"
cp "$CLOG" "$TMP/cr-once.md"
run_in "$CR" "$CL"
check "a second write with nothing new exits 0" 0
cmp -s "$CLOG" "$TMP/cr-once.md" && ok "a second write adds no duplicate bullets (file unchanged)" || bad "a second write adds no duplicate bullets" "$(diff "$TMP/cr-once.md" "$CLOG")"

run_in "$CR" "$CL" --dry-run --version 2.0.0
today_now="$(date +%Y-%m-%d)"
printf '%s' "$OUT" | grep -Eq "## \[2\.0\.0\] - ($today_now|$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d))" && ok "--version 2.0.0 --dry-run names the version and today's date" || bad "--version 2.0.0 --dry-run names the version and today's date" "$OUT"
run_in "$CR" "$CL" --dry-run --since v1.0.0
check "--since v1.0.0 exits 0 and counts the 4 commits after the tag" 0 'Found 4 commits since v1.0.0'
run_in "$CR" "$CL" --dry-run
check "with no --since it starts at the tag: 4 commits" 0 'Found 4 commits since v1\.0\.0'
run_in "$CR" "$CL" --dry-run --since HEAD~2
check "--since HEAD~2 is accepted and counts 2 commits, not 4" 0 'Found 2 commits since HEAD~2'
under "--since HEAD~2 lists only the last 2 commits" - '### Fixed' '- keep \n and \t literal in subjects'
printf '%s' "$OUT" | grep -Fq -- '- add widget' && bad "--since HEAD~2 leaves out the older commits" "$OUT" || ok "--since HEAD~2 leaves out the older commits"
run_in "$CR" "$CL" --dry-run --since 'HEAD^'
check "--since HEAD^ is accepted (a ^ in a ref)" 0 'Found 1 commits since HEAD\^'
run_in "$CR" "$CL" --help
check "--help lists the Other category" 0 'Other'

echo "update-changelog.sh: write mode keeps every other line"
KR="$TMP/work/keep"
newrepo "$KR"
cat > "$KR/CHANGELOG.md" <<'EOF'
# Changelog

## [Unreleased]

- x

## v1.0.0 (2024-01-01)

- important history

## v0.9.0

- more history

[Unreleased]: https://example.com/compare/v1.0.0...HEAD
[1.0.0]: https://example.com/releases/v1.0.0
EOF
cp "$KR/CHANGELOG.md" "$TMP/keep-before.md"
gitc "$KR" add CHANGELOG.md
gitc "$KR" commit -q -m "feat: a new thing"
run_in "$KR" "$CL"
check "a file with '## v1.0.0 (...)' sections: write mode exits 0" 0 'Updated '
subseq "'## v1.0.0 (...)' sections, their bullets and the footer links survive, in order" "$TMP/keep-before.md" "$KR/CHANGELOG.md"
under "the new bullet goes into [Unreleased], before '## v1.0.0 (2024-01-01)'" "$KR/CHANGELOG.md" '## [Unreleased]' '- x' '### Added' '- a new thing'
mdok "'## v1.0.0 (...)' file: the Markdown is intact" "$KR/CHANGELOG.md"

# An [Unreleased] section right before the footer links, with no other section.
FR="$TMP/work/footer"
newrepo "$FR"
printf '# Changelog\n\n## [Unreleased]\n\n- note\n\n[Unreleased]: https://example.com/compare/v1...HEAD\n' > "$FR/CHANGELOG.md"
cp "$FR/CHANGELOG.md" "$TMP/footer-before.md"
gitc "$FR" add CHANGELOG.md
gitc "$FR" commit -q -m "feat: x"
run_in "$FR" "$CL"
check "[Unreleased] then footer links: write mode exits 0" 0 'Updated '
subseq "[Unreleased] then footer links: every old line survives, in order" "$TMP/footer-before.md" "$FR/CHANGELOG.md"
python3 - "$FR/CHANGELOG.md" <<'EOF' >/dev/null 2>&1 && ok "[Unreleased] then footer links: the new bullet is above the link line" || bad "[Unreleased] then footer links: the new bullet is above the link line" "$(cat "$FR/CHANGELOG.md")"
import sys
l = open(sys.argv[1]).read().split("\n")
sys.exit(0 if l.index("- x") < l.index("[Unreleased]: https://example.com/compare/v1...HEAD") else 1)
EOF

# A file that is only a title gets an [Unreleased] section.
TR="$TMP/work/title"
newrepo "$TR"
printf '# Changelog\n' > "$TR/CHANGELOG.md"
gitc "$TR" add CHANGELOG.md
gitc "$TR" commit -q -m "feat: first"
run_in "$TR" "$CL"
check "a CHANGELOG.md that is only '# Changelog': write mode exits 0" 0 'Updated '
under "a CHANGELOG.md that is only '# Changelog' gets an [Unreleased] entry" "$TR/CHANGELOG.md" '## [Unreleased]' '### Added' '- first'
[[ "$(head -1 "$TR/CHANGELOG.md")" == '# Changelog' ]] && ok "the title stays the first line" || bad "the title stays the first line" "$(head -3 "$TR/CHANGELOG.md")"
mdok "title-only file: the Markdown is intact" "$TR/CHANGELOG.md"

# A file with versions but no [Unreleased] gets one above the first version, not above the intro.
IR2="$TMP/work/nounrel"
newrepo "$IR2"
printf '# Changelog\n\nAll notable changes.\n\n## [1.0.0] - 2026-01-01\n\n- first\n' > "$IR2/CHANGELOG.md"
cp "$IR2/CHANGELOG.md" "$TMP/nounrel-before.md"
gitc "$IR2" add CHANGELOG.md
gitc "$IR2" commit -q -m "fix: a bug"
run_in "$IR2" "$CL"
check "no [Unreleased] section: write mode exits 0" 0 'Updated '
subseq "no [Unreleased] section: every old line survives, in order" "$TMP/nounrel-before.md" "$IR2/CHANGELOG.md"
python3 - "$IR2/CHANGELOG.md" <<'EOF' >/dev/null 2>&1 && ok "no [Unreleased] section: it goes after the intro and before [1.0.0]" || bad "no [Unreleased] section: it goes after the intro and before [1.0.0]" "$(cat "$IR2/CHANGELOG.md")"
import sys
l = open(sys.argv[1]).read().split("\n")
sys.exit(0 if l.index("All notable changes.") < l.index("## [Unreleased]") < l.index("- a bug") < l.index("## [1.0.0] - 2026-01-01") else 1)
EOF
mdok "no [Unreleased] section: the Markdown is intact" "$IR2/CHANGELOG.md"

# CHANGELOG.md is a directory.
DR="$TMP/work/dirlog"
newrepo "$DR"
mkdir "$DR/CHANGELOG.md"
gitc "$DR" commit -q --allow-empty -m "feat: a"
run_in "$DR" "$CL"
check "CHANGELOG.md is a directory: exits 1 with a message" 1 "" 'not a regular file'
[[ -d "$DR/CHANGELOG.md" && -z "$(ls -A "$DR/CHANGELOG.md")" ]] && ok "CHANGELOG.md is a directory: nothing is written into it" || bad "CHANGELOG.md is a directory: nothing is written into it" "$(ls -lA "$DR/CHANGELOG.md")"

echo "update-changelog.sh: --version promotes [Unreleased]"
PR="$TMP/work/promote"
newrepo "$PR"
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n\n- feat a (hand)\n\n## [0.1.0] - 2024-01-01\n\n- old\n' > "$PR/CHANGELOG.md"
cp "$PR/CHANGELOG.md" "$TMP/promote-before.md"
gitc "$PR" add CHANGELOG.md
gitc "$PR" commit -q -m "chore: init"
gitc "$PR" tag v0.1.0
gitc "$PR" commit -q --allow-empty -m "feat: new thing"
gitc "$PR" commit -q --allow-empty -m "fix: a bug"
run_in "$PR" "$CL" --version 0.2.0
check "--version 0.2.0 exits 0" 0 'Updated '
PV="$(grep -m1 '^## \[0\.2\.0\]' "$PR/CHANGELOG.md" || true)"
[[ -n "$PV" && "$(grep -c '^## \[0\.2\.0\]' "$PR/CHANGELOG.md")" == 1 ]] && ok "--version adds one [0.2.0] heading" || bad "--version adds one [0.2.0] heading" "$(grep -n '^## ' "$PR/CHANGELOG.md")"
under "--version moves the hand-written bullet and the new bullets into [0.2.0]" "$PR/CHANGELOG.md" "${PV:-## [0.2.0]}" '- feat a (hand)' '- new thing' '- a bug' '### Added' '### Fixed'
python3 - "$PR/CHANGELOG.md" <<'EOF' >/dev/null 2>&1 && ok "--version leaves [Unreleased] as an empty heading above [0.2.0]" || bad "--version leaves [Unreleased] as an empty heading above [0.2.0]" "$(cat "$PR/CHANGELOG.md")"
import sys
l = open(sys.argv[1]).read().split("\n")
u = l.index("## [Unreleased]")
v = [i for i, x in enumerate(l) if x.startswith("## [0.2.0]")][0]
sys.exit(0 if u < v and all(x.strip() == "" for x in l[u + 1:v]) else 1)
EOF
[[ "$(grep -c -- '^- new thing$' "$PR/CHANGELOG.md")" == 1 && "$(grep -c -- '^- feat a (hand)$' "$PR/CHANGELOG.md")" == 1 ]] && ok "--version writes each bullet once" || bad "--version writes each bullet once" "$(cat "$PR/CHANGELOG.md")"
subseq "--version keeps every old line" "$TMP/promote-before.md" "$PR/CHANGELOG.md"
mdok "--version keeps the Markdown intact" "$PR/CHANGELOG.md"
cp "$PR/CHANGELOG.md" "$TMP/promote-once.md"
run_in "$PR" "$CL" --version 0.2.0
check "a second --version 0.2.0 is refused" 1 "" 'already'
cmp -s "$PR/CHANGELOG.md" "$TMP/promote-once.md" && ok "a refused --version leaves the file unchanged" || bad "a refused --version leaves the file unchanged" "$(diff "$TMP/promote-once.md" "$PR/CHANGELOG.md")"

echo "update-changelog.sh: the starting point"
# A release candidate tag and the final tag on later commits: the final tag wins.
RT="$TMP/work/rctag"
newrepo "$RT"
gitc "$RT" commit -q --allow-empty -m "feat: a"
gitc "$RT" tag v1.1.0-rc1
gitc "$RT" commit -q --allow-empty -m "fix: between rc and final"
gitc "$RT" tag v1.1.0
gitc "$RT" commit -q --allow-empty -m "feat: after final"
run_in "$RT" "$CL" --dry-run
check "v1.1.0 beats v1.1.0-rc1 as the starting point" 0 'changes since tag v1\.1\.0$'
check "after v1.1.0 there is 1 commit" 0 'Found 1 commits since v1\.1\.0$'
# Version order, not text order: v1.10.0 is newer than v1.9.0.
gitc "$RT" tag v1.9.0 HEAD~1
gitc "$RT" tag v1.10.0 HEAD~1
run_in "$RT" "$CL" --dry-run
check "v1.10.0 beats v1.9.0 (version order)" 0 'changes since tag v1\.10\.0$'

# Tags exist, none is a release version.
NT="$TMP/work/nonsemver"
newrepo "$NT"
gitc "$NT" commit -q --allow-empty -m "feat: one"
gitc "$NT" commit -q --allow-empty -m "feat: two"
gitc "$NT" tag 20261001-snap
gitc "$NT" tag release-2.0.0
gitc "$NT" commit -q --allow-empty -m "feat: three"
run_in "$NT" "$CL" --dry-run
check "only non-release tags: says none of the tags is a release version" 0 'none is a release version'
printf '%s' "$OUT" | grep -Fq 'No tags found' && bad "only non-release tags: does not say 'No tags found'" "$OUT" || ok "only non-release tags: does not say 'No tags found'"
check "only non-release tags: uses the whole history, 3 commits" 0 'Found 3 commits in the whole history'
# No tags at all.
NN="$TMP/work/notags"
newrepo "$NN"
gitc "$NN" commit -q --allow-empty -m "feat: one"
run_in "$NN" "$CL" --dry-run
check "no tags: says so and uses the whole history" 0 'No tags found'
check "no tags: 1 commit in the whole history" 0 'Found 1 commits in the whole history'

# CHANGELOG.md fallback: skips [Unreleased] and reads the first versioned heading.
CF="$TMP/work/clfallback"
newrepo "$CF"
printf '# Changelog\n\n## [Unreleased]\n\n## [1.0] - 2024-01-01\n\n- old\n' > "$CF/CHANGELOG.md"
gitc "$CF" add CHANGELOG.md
gitc "$CF" commit -q -m "chore: init"
gitc "$CF" tag v1.0
gitc "$CF" commit -q --allow-empty -m "feat: after"
run_in "$CF" "$CL" --dry-run
check "CHANGELOG.md fallback skips [Unreleased] and uses the [1.0] heading (tag v1.0)" 0 'changes since v1\.0 \(from CHANGELOG\.md\)'
check "CHANGELOG.md fallback: 1 commit since v1.0" 0 'Found 1 commits since v1\.0$'

echo "update-changelog.sh: categories"
CT="$TMP/work/cats"
newrepo "$CT"
gitc "$CT" commit -q --allow-empty -m "chore: init"
gitc "$CT" tag v1.0.0
mkdir -p "$CT/src"
echo x > "$CT/src/a.js"
gitc "$CT" add src/a.js
gitc "$CT" commit -q -m "refactor(core): tidy the loop"
gitc "$CT" commit -q --allow-empty -m "revert: drop the beta flag"
gitc "$CT" commit -q --allow-empty -m "test: cover the parser"
gitc "$CT" commit -q --allow-empty -m "Plain subject with no prefix"
run_in "$CT" "$CL" --dry-run
check "categories: exits 0" 0 'Found 4 commits'
under "refactor goes to Changed" - '### Changed' '- tidy the loop'
under "revert goes to Removed" - '### Removed' '- drop the beta flag'
under "test goes to Testing" - '### Testing' '- cover the parser'
under "in a range that has prefixed commits, an unprefixed one goes to Other (even with src/ changed)" - '### Other' '- Plain subject with no prefix'
# Only unprefixed commits: the file-path fallback. src/ changed -> Changed; otherwise Other.
UF="$TMP/work/unprefixed-src"
newrepo "$UF"
mkdir -p "$UF/src"
echo x > "$UF/src/a.js"
gitc "$UF" add src/a.js
gitc "$UF" commit -q -m "Rework the loader"
run_in "$UF" "$CL" --dry-run
under "only unprefixed commits and src/ changed: they go to Changed" - '### Changed' '- Rework the loader'
UD="$TMP/work/unprefixed-docs"
newrepo "$UD"
mkdir -p "$UD/docs" "$UD/tests"
echo x > "$UD/docs/a.md"
echo y > "$UD/tests/t.sh"
gitc "$UD" add docs tests
gitc "$UD" commit -q -m "Write docs and tests"
run_in "$UD" "$CL" --dry-run
under "only unprefixed commits and no src/, lib/ or scripts/ change: they stay in Other" - '### Other' '- Write docs and tests'

echo "update-changelog.sh: bad input and fail-closed paths"
run_in "$CR" "$CL" --frobnicate
check "an unknown option exits 1 with a message" 1 "" 'Unknown option: --frobnicate'
run_in "$CR" "$CL" --since
check "--since with no value exits 1 with a message" 1 "" '--since needs a value'
run_in "$CR" "$CL" --version
check "--version with no value exits 1 with a message" 1 "" '--version needs a value'
run_in "$CR" "$CL" --dry-run --since no-such-ref
check "--since with an unknown ref exits 1 (not 'no new commits' and exit 0)" 1 "" 'not a tag, branch or commit'
run_in "$CR" "$CL" --dry-run --since --output=since-out
check "--since that starts with a dash exits 1" 1 "" 'not a tag, branch or commit'
[[ ! -e "$CR/since-out" && ! -e "$CR/since-out..HEAD" ]] && ok "--since '--output=...' creates no file" || bad "--since '--output=...' creates no file" "$(ls -A "$CR")"
run_in "$TMP/notrepo" "$CL" --dry-run
check "outside a git repo it exits 1 with a message" 1 "" 'not a git repository'
run_in "$TMP/notrepo" "$CL" --dry-run "$TMP/nope"
check "a missing repo directory exits non-zero" nonzero

# A linked worktree has a .git FILE, not a directory.
gitc "$CR" worktree add -q "$TMP/work/clwt" -b other
run_in "$TMP/work/clwt" "$CL" --dry-run
check "it works inside a linked worktree (.git is a file)" 0 'Generated changelog entry'

echo "update-changelog.sh: CHANGELOG.md is untrusted input"
# 1. A first heading that looks like a git option must not reach git as an option.
for head in '--output=owned' '-n1' '--since=x'; do
  IR="$TMP/work/inj"
  rm -rf "$IR"
  mkdir -p "$IR"
  gitc "$IR" init -q
  printf '# Changelog\n\n## [%s]\n\n- x\n' "$head" > "$IR/CHANGELOG.md"
  gitc "$IR" add CHANGELOG.md
  gitc "$IR" commit -q -m "feat: one"
  gitc "$IR" commit -q --allow-empty -m "feat: two"
  files_before="$(ls -A "$IR" | sort | tr '\n' ' ')"
  run_in "$IR" "$CL" --dry-run
  check "first heading '## [$head]' does not break the run" 0 'Using the whole history'
  printf '%s' "$OUT" | grep -Fq 'Found 2 commits in the whole history' && ok "first heading '## [$head]': both commits are listed, the root commit included" || bad "first heading '## [$head]': both commits are listed, the root commit included" "$OUT"
  [[ "$(ls -A "$IR" | sort | tr '\n' ' ')" == "$files_before" ]] && ok "first heading '## [$head]' creates no file" || bad "first heading '## [$head]' creates no file" "$(ls -A "$IR")"
  printf '%s' "$ERR" | grep -Eiq 'usage|unknown option|unrecognized|invalid' && bad "first heading '## [$head]' causes no git option error" "$ERR" || ok "first heading '## [$head]' causes no git option error"
done

# 2. A CHANGELOG.md symlink must not be written through.
SR="$TMP/work/symrepo"
mkdir -p "$SR"
gitc "$SR" init -q
gitc "$SR" commit -q --allow-empty -m "feat: one"
gitc "$SR" commit -q --allow-empty -m "feat: two"
printf 'outside file\n' > "$TMP/outside.md"
ln -s "$TMP/outside.md" "$SR/CHANGELOG.md"
out_sum="$(cksum < "$TMP/outside.md")"
run_in "$SR" "$CL"
check "a CHANGELOG.md symlink to an existing file exits non-zero with a message" nonzero "" 'symlink'
[[ "$(cksum < "$TMP/outside.md")" == "$out_sum" ]] && ok "the file behind the symlink is unchanged" || bad "the file behind the symlink is unchanged" "$(cat "$TMP/outside.md")"
[[ -L "$SR/CHANGELOG.md" ]] && ok "the symlink is still a symlink" || bad "the symlink is still a symlink" "it was replaced"
rm -f "$SR/CHANGELOG.md" "$TMP/gone.md"
ln -s "$TMP/gone.md" "$SR/CHANGELOG.md"
run_in "$SR" "$CL"
check "a dangling CHANGELOG.md symlink exits non-zero with a message" nonzero "" 'symlink'
[[ ! -e "$TMP/gone.md" ]] && ok "a dangling symlink does not create its target" || bad "a dangling symlink does not create its target" "$TMP/gone.md exists"
run_in "$SR" "$CL" --dry-run
check "--dry-run through a symlink is allowed (it writes nothing)" 0 'Dry run'

# 3. A backslash in a commit subject is data, not an escape (echo -e and awk -v both read it as one).
VR="$TMP/work/verbatim"
mkdir -p "$VR"
gitc "$VR" init -q
printf '# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- first\n' > "$VR/CHANGELOG.md"
gitc "$VR" add CHANGELOG.md
gitc "$VR" commit -q -m "chore: init"
gitc "$VR" tag v0.1.0
gitc "$VR" commit -q --allow-empty -m 'fix: keep a\nb and c\td as typed'
run_in "$VR" "$CL"
check "a subject with a literal \\n and \\t: write mode exits 0" 0 'Updated '
has "a subject with a literal \\n and \\t is written as typed" "$VR/CHANGELOG.md" '- keep a\nb and c\td as typed'
[[ "$(grep -c '^- keep' "$VR/CHANGELOG.md")" == 1 ]] && ok "that subject is one bullet, not split across lines" || bad "that subject is one bullet, not split across lines" "$(cat "$VR/CHANGELOG.md")"

# 4. A new CHANGELOG.md is created when there is none.
NR="$TMP/work/newrepo"
mkdir -p "$NR"
gitc "$NR" init -q
gitc "$NR" commit -q --allow-empty -m 'feat: first \t thing'
run_in "$NR" "$CL"
check "with no CHANGELOG.md it creates one" 0 'Created '
has "the new CHANGELOG.md has the header and the entry, subject as typed" "$NR/CHANGELOG.md" '- first \t thing'
has "the new CHANGELOG.md has the title" "$NR/CHANGELOG.md" '# Changelog'

# ---------------------------------------------------------------------------
echo "every script named in a SKILL.md exists, is executable and answers --help"
# Pull each "${CLAUDE_SKILL_DIR}/scripts/<name>" out of a SKILL.md, resolve it against that
# skill's directory in the plugin copy, and run it with --help from the project dir.
for skill in worktree changelog; do
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

echo "the skills never show the substituted path tokens in prose"
# Claude Code replaces "${CLAUDE_SKILL_DIR}" and "${CLAUDE_PLUGIN_ROOT}" everywhere in a SKILL.md,
# prose and inline code included, before the model reads it. In a fenced code block the token is a
# real command for this skill's own scripts, which is what we want. Outside one the model would read
# this skill's absolute path where the text says something else. So outside fenced blocks the token
# must not appear.
for skill in worktree changelog; do
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

echo "the scripts do not depend on their old install path"
for f in "$SKILLS"/worktree/scripts/setup-worktree.sh "$SKILLS"/changelog/scripts/update-changelog.sh "$SKILLS"/worktree/SKILL.md "$SKILLS"/changelog/SKILL.md; do
  if grep -Eq '~/\.claude/skills|\.claude/skills/(worktree|changelog-keeper)' "$f"; then
    bad "$(basename "$f") does not name ~/.claude/skills" "$(grep -En '~/\.claude/skills|\.claude/skills/' "$f" | head -2)"
  else
    ok "$(basename "$f") does not name ~/.claude/skills"
  fi
done

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
