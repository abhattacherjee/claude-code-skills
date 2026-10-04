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
# SKILLS may be set by the caller to test another copy of the skills.
SKILLS="${SKILLS:-$TMP/plugin copy/skills}"

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
run_in "$CR" "$CL"
check "write mode exits 0" 0 'Updated '
CLOG="$CR/CHANGELOG.md"
res="$(python3 - "$CLOG" <<'EOF'
import re, sys
raw = open(sys.argv[1], encoding="utf-8").read()
lines = raw.split("\n")
problems = []
heads = [i for i, l in enumerate(lines) if l.startswith("## [")]
titles = [lines[i] for i in heads]
if titles.count("## [Unreleased]") != 1:
    problems.append("want one [Unreleased], got %r" % titles)
if not any(t.startswith("## [1.0.0]") for t in titles):
    problems.append("the 1.0.0 entry is gone")
if titles and titles[0] != "## [Unreleased]":
    problems.append("[Unreleased] is not the first entry")
u = lines.index("## [Unreleased]")
nxt = [i for i in heads if i > u][0]
block = "\n".join(lines[u:nxt])
for want in ("- add widget", "- stop the crash", "- update the guide", "- keep \\n and \\t literal in subjects"):
    if want not in block:
        problems.append("[Unreleased] block lacks %r" % want)
# Markdown: a heading is preceded by a blank line, and the file ends with one newline.
for i, l in enumerate(lines):
    if re.match(r"#{2,3} ", l) and i > 0 and lines[i - 1].strip() != "":
        problems.append("line %d: heading %r has no blank line before it" % (i + 1, l))
if not raw.endswith("\n") or raw.endswith("\n\n"):
    problems.append("the file does not end with exactly one newline")
print("\n".join(problems))
EOF
)"
[[ -z "$res" ]] && ok "write mode puts the entry in the [Unreleased] block, keeps 1.0.0 and the Markdown intact" || bad "write mode puts the entry in the [Unreleased] block, keeps 1.0.0 and the Markdown intact" "$res"
[[ "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$CLOG")" == 0o640 ]] && ok "write mode keeps the file mode of CHANGELOG.md" || bad "write mode keeps the file mode of CHANGELOG.md" "mode changed"
[[ -z "$(ls -A "$CR" | grep -F '.CHANGELOG.' || true)" ]] && ok "write mode leaves no temp file behind" || bad "write mode leaves no temp file behind" "$(ls -A "$CR")"

run_in "$CR" "$CL" --dry-run --version 2.0.0
today_now="$(date +%Y-%m-%d)"
printf '%s' "$OUT" | grep -Eq "## \[2\.0\.0\] - ($today_now|$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d yesterday +%Y-%m-%d))" && ok "--version 2.0.0 --dry-run names the version and today's date" || bad "--version 2.0.0 --dry-run names the version and today's date" "$OUT"
run_in "$CR" "$CL" --dry-run --since v1.0.0
check "--since v1.0.0 exits 0" 0 'changes since v1.0.0|Found 4 commits since v1.0.0'

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
  check "first heading '## [$head]' does not break the run" 0 'No tags found, using all commits since initial' 
  printf '%s' "$OUT" | grep -Fq 'Found 2 commits since' && ok "first heading '## [$head]': both commits are listed, the root commit included" || bad "first heading '## [$head]': both commits are listed, the root commit included" "$OUT"
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
