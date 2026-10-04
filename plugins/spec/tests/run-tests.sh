#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts in the spec plugin.
#
# It also runs every script command written in the three SKILL.md files (see the
# last section), so a wrong argument order or workflow name in the text fails here.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a
# temp project directory (never the skill directory), in a clean environment
# (`env -i`, so nothing leaks in from the caller's shell). Needs bash 3.2+
# and python3 (standard library only, used to read JSON). Nothing here touches
# the network or anything outside the temp dir.
#
# Usage: bash plugins/spec/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

# A copy of the plugin under a path with a space proves the scripts find nothing
# relative to their own location and survive quoting. SKILLS may be set by the
# caller to test another copy.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy"
cp -R "$PLUGIN/skills" "$TMP/plugin copy/skills"
SKILLS="${SKILLS:-$TMP/plugin copy/skills}"

CREATE="$SKILLS/create/scripts"
REVIEW="$SKILLS/review/scripts"
IMPLEMENT="$SKILLS/implement/scripts"

PASS=0
FAIL=0

echo "bash under test: $BASH_VERSION"
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

# run_in <dir> <cmd...>: run in a clean env from <dir>; sets OUT (stdout), ERR (stderr), RC.
run_in() {
  local dir="$1"
  shift
  RC=0
  OUT="$(cd "$dir" && env -i PATH="$PATH" HOME="$TMP/home" "$@" 2>"$TMP/err")" || RC=$?
  ERR="$(cat "$TMP/err")"
}

# check <label> <want-rc> [stdout-regex [stderr-regex]]  (uses OUT ERR RC from run_in)
check() {
  local label="$1" want="$2" ore="${3:-}" ere="${4:-}"
  if [[ "$RC" != "$want" ]]; then
    bad "$label" "exit $RC, want $want. stdout: $(printf '%s' "$OUT" | head -2) stderr: $(printf '%s' "$ERR" | head -2)"
  elif [[ -n "$ore" ]] && ! printf '%s' "$OUT" | grep -Eq -- "$ore"; then
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
  local label="$1" expr="$2" res arg="${3:-}"
  if res="$(printf '%s' "$OUT" | python3 -c 'import json,sys
d = json.load(sys.stdin)
print("yes" if eval(sys.argv[1]) else "no")' "$expr" "$arg" 2>&1)" && [[ "$res" == "yes" ]]; then
    ok "$label"
  else
    bad "$label" "JSON check failed ($expr): $res; stdout: $(printf '%s' "$OUT" | head -c 300)"
  fi
}

# --- fixture project: two specs under epic-1, a web and an api package ---
PROJ="$TMP/proj"
mkdir -p "$PROJ/specs/stories/epic-1" "$PROJ/web" "$PROJ/api" "$PROJ/sub"
git -C "$PROJ" init -q
for n in 1 2; do
  cat > "$PROJ/specs/stories/epic-1/story-1.$n-thing.md" <<'EOF'
# Story 1.1: Login

**Epic:** 1
**Priority:** P1
**Status:** Draft

**As a** user
**I want** to log in
**So that** I see my data

## Acceptance Criteria

- [ ] AC1 user can log in
- [x] AC2 error is shown

## Sub-Tasks

### Sub-Task 1: Form

Edit `web/src/login.ts`.

### Sub-Task 2: Endpoint

Add `POST /api/login`.

## Testing

Unit tests.
EOF
done
echo '{"name":"web","dependencies":{"react":"18","vite":"5"},"devDependencies":{"vitest":"1"}}' > "$PROJ/web/package.json"
echo '{"name":"api","dependencies":{"express":"4"}}' > "$PROJ/api/package.json"

# The scripts start with `#!/usr/bin/env bash`. In the clean env they must get the same
# bash major version as this test shell, and EXPECT_BASH_MAJOR (set by CI) pins it.
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

echo "discover-conventions.sh (create)"
run_in "$PROJ" "$CREATE/discover-conventions.sh" .
check "report from project dir exits 0" 0 'Spec directory: +specs/stories'
check "report counts the specs" 0 'Total specs: +2'
check "report names the next story" 0 'Epic 1: latest story = 1\.2, next = 1\.3'
run_in "$PROJ" "$CREATE/discover-conventions.sh" "$PROJ" --json
check "--json exits 0" 0
json_is "--json is valid and names the spec dir" 'd["specDir"] == "specs/stories" and d["specCount"] == 2'
json_is "--json has the next story number" 'd["epics"][0]["nextStory"] == 3 and d["epicStructure"] == "epic-subdirs"'
run_in "$PROJ/sub" "$CREATE/discover-conventions.sh" "$PROJ" --json
json_is "runs from a subdirectory with the root as argument" 'd["specCount"] == 2'
run_in "$PROJ" "$CREATE/discover-conventions.sh" "$TMP/nope"
check "missing directory exits 1" 1 "" 'Directory not found'
run_in "$PROJ" "$CREATE/discover-conventions.sh"
check "no argument exits 2" 2 "" 'project root required'
run_in "$PROJ" "$CREATE/discover-conventions.sh" --help
check "--help exits 0" 0 'Usage: discover-conventions\.sh'
# An empty spec directory used to be reported as epic-subdirs (#62).
mkdir -p "$TMP/emptyspecs/specs"
run_in "$TMP/emptyspecs" "$CREATE/discover-conventions.sh" . --json
json_is "empty spec dir is flat with no specs" 'd["specCount"] == 0 and d["epicStructure"] == "flat"'

# --- hostile names: epics, story files and headings come from the project, so they are untrusted ---
# json_ok <label>: OUT is valid JSON. no_file <label> <path>: the path must not exist.
json_ok() { json_is "$1" 'True'; }
no_file() { [[ ! -e "$2" ]] && ok "$1" || bad "$1" "$2 was created"; }
EVIL="$TMP/evil"
mkdir -p "$EVIL/specs/stories/epic-1" "$EVIL/specs/stories/epic-2" "$EVIL/specs/stories/epic-08"
mkdir "$EVIL/specs/stories/epic-q\"z" "$EVIL/specs/stories/epic-q\\z" "$EVIL/specs/stories/epic-[a]" "$EVIL/specs/stories/epic-\$(touch PWNED)"
CTRL_NAME="epic-q$(printf '\001')z"
if mkdir "$EVIL/specs/stories/$CTRL_NAME" 2>/dev/null; then HAVE_CTRL=1; else HAVE_CTRL=0; echo "  note: filesystem refused a control character in a name; that case is skipped"; fi
touch "$EVIL/specs/stories/epic-1/story-1.3-[\$(touch PWNED)].md" "$EVIL/specs/stories/epic-1/story-1.1-ok.md"
touch "$EVIL/specs/stories/epic-2/story-2.1-a.md" "$EVIL/specs/stories/epic-2/story-2.9-b.md" "$EVIL/specs/stories/epic-08/story-08.3-c.md"
mkdir "$EVIL/specs/stories/epic-3"
mkdir "$EVIL/specs/stories/epic-4"
touch "$EVIL/specs/stories/epic-3/story-3.08-d.md" "$EVIL/specs/stories/epic-3/story-3.7-e.md"
run_in "$EVIL" "$CREATE/discover-conventions.sh" . --json
check "hostile names: --json exits 0" 0
json_ok "hostile names: --json stdout parses as JSON"
no_file "hostile names: nothing was executed (no PWNED file)" "$EVIL/PWNED"
json_is "hostile names: only numeric epics are listed" 'sorted(e["epic"] for e in d["epics"]) == ["08", "1", "2", "3", "4"]'
json_is "hostile names: a normal epic still reports latest and next" '[e for e in d["epics"] if e["epic"] == "2"][0]["latestStory"] == 9 and [e for e in d["epics"] if e["epic"] == "2"][0]["nextStory"] == 10'
json_is "hostile names: a story number with a leading zero (08) is not read as octal" '[e for e in d["epics"] if e["epic"] == "3"][0]["latestStory"] == 8 and [e for e in d["epics"] if e["epic"] == "3"][0]["nextStory"] == 9'
json_is "hostile names: an epic with no stories reports latest 0, next 1" '[e for e in d["epics"] if e["epic"] == "4"][0]["latestStory"] == 0 and [e for e in d["epics"] if e["epic"] == "4"][0]["nextStory"] == 1'
json_is "hostile names: a leading-zero epic is not read as octal" '[e for e in d["epics"] if e["epic"] == "08"][0]["nextStory"] == 4'
run_in "$EVIL" "$CREATE/discover-conventions.sh" .
check "hostile names: text mode exits 0, skips bad epics on stderr" 0 'Epic 2: latest story = 2\.9, next = 2\.10' 'skipped epic with a non-numeric name'
no_file "hostile names: text mode executed nothing" "$EVIL/PWNED"
run_in "$EVIL" "$CREATE/discover-conventions.sh" . --json
[[ -z "$ERR" ]] && ok "hostile names: --json prints nothing on stderr" || bad "hostile names: --json prints nothing on stderr" "$ERR"
json_is "hostile names: --json lists the skipped (non-numeric) epic dirs, escaped" '"epic-q\"z" in d["skippedEpics"] and "epic-q\\z" in d["skippedEpics"] and "epic-[a]" in d["skippedEpics"] and "epic-$(touch PWNED)" in d["skippedEpics"] and not any(n.startswith("epic-1") for n in d["skippedEpics"])'
if [[ "$HAVE_CTRL" == 1 ]]; then
  json_is "a control character in an epic name is escaped in skippedEpics" '"epic-q\x01z" in d["skippedEpics"]'
fi
# Section headings are sampled from the first few specs only, so test them in a project of their own.
HEADS="$TMP/heads"
mkdir -p "$HEADS/specs/stories/epic-1"
printf '# T\n\n## Say "hi"\\there\r\n## Tab\tand\001ctl\n' > "$HEADS/specs/stories/epic-1/story-1.2-heads.md"
run_in "$HEADS" "$CREATE/discover-conventions.sh" . --json
json_ok "headings with quote, CR and control chars: --json parses"
json_is "headings with quote, CR and control chars: the heading text survives" 'any(s["section"].startswith("Say \"hi\"") for s in d["commonSections"])'
# Control characters in a title and in a package directory must not break the other two scripts' JSON.
printf '# Title\twith\001ctl\r\n' > "$EVIL/ctl-title.md"
run_in "$EVIL" "$REVIEW/extract-spec-sections.sh" ctl-title.md --json
check "extract: control chars in the title, exits 0" 0
json_ok "extract: --json parses with control chars in the title"
json_is "extract: the title round-trips" 'd["title"] == "Title\twith\x01ctl\r"'
# Package directories with a quote, a real control character, a literal backslash
# sequence (\c would cut off %b output), and a space. A plain "zz" package comes last.
ARCH="$TMP/archnames"
mkdir -p "$ARCH"
NAMES=('pk"g' 'z\cq' 'sp ace' 'zz')
if mkdir "$ARCH/pk$(printf '\001')x" 2>/dev/null; then NAMES+=("pk$(printf '\001')x"); else echo "  note: filesystem refused a control character in a directory name; that case is skipped"; fi
for n in "${NAMES[@]}"; do
  mkdir -p "$ARCH/$n"
  echo '{"name":"pkg"}' > "$ARCH/$n/package.json"
done
run_in "$ARCH" "$REVIEW/discover-project-architecture.sh" . --json
check "architecture: odd package directory names, exits 0" 0
json_ok "architecture: --json parses with odd directory names"
for n in "${NAMES[@]}"; do
  want="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$n")"
  json_is "architecture: directory $(printf '%s' "$n" | tr -c '[:print:]' '?') is listed exactly" 'any(p["directory"] == json.loads(sys.argv[2]) for p in d["packages"])' "$want"
done
run_in "$ARCH" "$REVIEW/discover-project-architecture.sh" .
check "architecture: text report lists the last package after a backslash name" 0 'zz \(pkg\)'

echo "discover-project-architecture.sh (review)"
run_in "$PROJ" "$REVIEW/discover-project-architecture.sh" "$(git -C "$PROJ" rev-parse --show-toplevel)"
check "report exits 0 and names the packages" 0 'api \(api\) +\[backend\] +Express'
check "report finds the front-end framework and test tool" 0 'web \(web\).*React,Vite.*Vitest'
# From a subdirectory, with the project root as the argument: the script must cd to the root.
run_in "$PROJ/sub" "$REVIEW/discover-project-architecture.sh" "$PROJ" --json
json_is "runs from a subdirectory with the root as argument (both packages listed)" 'sorted(p["name"] for p in d["packages"] if p["name"] in ("web", "api")) == ["api", "web"]'
run_in "$PROJ" "$REVIEW/discover-project-architecture.sh" . --json
check "--json exits 0" 0
json_is "--json is valid with the expected keys" 'set(["packages", "apiTestTools", "e2eFramework", "brunoFolders", "dataFlow", "i18n", "security"]) <= set(d)'
json_is "--json lists both packages" 'sorted(p["name"] for p in d["packages"] if p["name"] in ("web", "api")) == ["api", "web"]'
# A markdown-only project must not be reported as having i18n, security or data-flow patterns (#62).
mkdir -p "$TMP/mdonly"
echo "# readme" > "$TMP/mdonly/README.md"
run_in "$TMP/mdonly" "$REVIEW/discover-project-architecture.sh" . --json
json_is "markdown-only project reports no invented patterns" 'd["packages"] == [] and d["i18n"] == "" and d["security"] == "" and d["dataFlow"] == ""'
run_in "$PROJ" "$REVIEW/discover-project-architecture.sh" "$TMP/nope"
check "missing directory exits 1" 1 "" 'Directory not found'
run_in "$PROJ" "$REVIEW/discover-project-architecture.sh"
check "no argument exits 2" 2 "" 'project root required'

echo "unreadable input (create, review)"
# chmod 000 does nothing for root, so check that the file really is unreadable first.
printf '# Locked\n' > "$PROJ/locked.md"
chmod 000 "$PROJ/locked.md"
if [[ -r "$PROJ/locked.md" ]]; then
  echo "  note: this user can read a chmod 000 file (root?); the unreadable-input cases are skipped"
else
  run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" locked.md --json
  check "extract: an unreadable spec exits 1 with a message" 1 "" 'cannot read'
  [[ -z "$OUT" ]] && ok "extract: an unreadable spec prints no false report" || bad "extract: an unreadable spec prints no false report" "$OUT"
  UNR="$TMP/unreadable"
  mkdir -p "$UNR/specs/stories/epic-1" "$UNR/specs/stories/epic-2"
  touch "$UNR/specs/stories/epic-1/story-1.4-a.md" "$UNR/specs/stories/epic-2/story-2.1-b.md"
  chmod 000 "$UNR/specs/stories/epic-1"
  run_in "$UNR" "$CREATE/discover-conventions.sh" . --json
  check "discover-conventions: an unreadable epic dir exits 1 with a message" 1 "" 'cannot read directory'
  [[ "$OUT" != *nextStory* ]] && ok "discover-conventions: no false nextStory is printed (json)" || bad "discover-conventions: no false nextStory is printed (json)" "$OUT"
  run_in "$UNR" "$CREATE/discover-conventions.sh" .
  check "discover-conventions: an unreadable epic dir exits 1 in text mode too" 1 "" 'cannot read directory'
  chmod 755 "$UNR/specs/stories/epic-1"
fi
chmod 644 "$PROJ/locked.md"

# Headings with a non-UTF-8 byte: valid JSON in the C locale and in a UTF-8 locale.
LOCALE_BAD="$TMP/localebad"
mkdir -p "$LOCALE_BAD/specs/stories/epic-1"
printf '# T\n\n## caf\303\251 \377 bad\n' > "$LOCALE_BAD/specs/stories/epic-1/story-1.1-a.md"
# A spec with one invalid byte must still be read in full under a UTF-8 locale (GNU grep
# called such a file "binary"). Same for extract-spec-sections.sh and its endpoints.
printf '# Caf\303\251 title\n\n## Acceptance Criteria\n- [ ] one \377\n- [x] two\n\nPOST /api/x here\n' > "$LOCALE_BAD/bad.md"
run_in "$LOCALE_BAD" "$CREATE/discover-conventions.sh" . --json
json_ok "a non-UTF-8 byte in a heading: --json parses (default locale)"
json_is "a non-UTF-8 byte in a heading: the valid text is kept, the bad byte dropped" 'any(s["section"].startswith("caf\u00e9") for s in d["commonSections"])'
UTF8_LOCALE="$(locale -a 2>/dev/null | grep -i 'utf-\{0,1\}8' | head -1 || true)"
if [[ -n "$UTF8_LOCALE" ]]; then
  run_in "$LOCALE_BAD" env LC_ALL="$UTF8_LOCALE" "$CREATE/discover-conventions.sh" . --json
  run_in "$LOCALE_BAD" env LC_ALL="$UTF8_LOCALE" "$REVIEW/extract-spec-sections.sh" bad.md --json
  json_is "a spec with an invalid byte is read in full under $UTF8_LOCALE (criteria and endpoint counted)" 'd["criteriaCounts"] == "total=2 checked=1 unchecked=1" and d["referencedEndpointCount"] == 1 and d["title"].startswith("Caf\u00e9")'
  run_in "$LOCALE_BAD" env LC_ALL="$UTF8_LOCALE" "$CREATE/discover-conventions.sh" . --json
  json_ok "a non-UTF-8 byte in a heading: --json parses under $UTF8_LOCALE"
  json_is "a non-UTF-8 byte in a heading: text kept under $UTF8_LOCALE" 'any(s["section"].startswith("caf\u00e9") for s in d["commonSections"])'
else
  echo "  note: no UTF-8 locale installed; the UTF-8 locale case is skipped"
fi

echo "extract-spec-sections.sh (review)"
SPEC_REL="specs/stories/epic-1/story-1.1-thing.md"
run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" "$SPEC_REL" --json
check "--json exits 0" 0
json_is "--json has the title and criteria counts" 'd["title"] == "Story 1.1: Login" and d["criteriaCounts"] == "total=2 checked=1 unchecked=1"'
json_is "--json counts the sub-tasks, files and distinct endpoints (POST /api/login and /api/login are one)" 'd["subtaskCount"] == 2 and d["referencedFileCount"] == 1 and d["referencedEndpointCount"] == 1'
json_is "--json reports both gaps for a spec without those sections" 'd["gaps"]["missingCodebaseState"] and d["gaps"]["missingApiTests"]'
run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" "$PROJ/$SPEC_REL"
check "report from an absolute path names the sections" 0 'Acceptance Criteria \(total=2 checked=1 unchecked=1\)'
check "report has the sub-tasks heading" 0 'Sub-Tasks \(2 found\)'
printf '# S\n\n## Current Codebase State\nx\n\n## API Test Plan\ny\n' > "$PROJ/gaps-closed.md"
run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" gaps-closed.md --json
json_is "--json reports no gaps when both sections exist" 'not d["gaps"]["missingCodebaseState"] and not d["gaps"]["missingApiTests"]'
# A relative path typed from a subdirectory means that subdirectory. It used to be
# joined to the repo root only: not found, or the wrong file with the same name.
printf '# Sub spec\n' > "$PROJ/sub/local.md"
printf '# Root spec\n' > "$PROJ/local.md"
run_in "$PROJ/sub" "$REVIEW/extract-spec-sections.sh" local.md --json
json_is "a relative path from a subdirectory finds the file in that subdirectory" 'd["title"] == "Sub spec"'
run_in "$PROJ/sub" "$REVIEW/extract-spec-sections.sh" "$SPEC_REL" --json
json_is "a repo-root-relative path still works from a subdirectory" 'd["title"] == "Story 1.1: Login"'
# Text mode must list every endpoint, and agree with --json on the count. A grep that finds
# nothing used to end the group under `set -e`, so later endpoints went missing.
endpoint_case() { # <label> <spec text> <expected count> <expected lines (newline separated)>
  printf '%b' "$2" > "$PROJ/ep.md"
  run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" ep.md
  local listed
  listed="$(printf '%s\n' "$OUT" | sed -n '/^--- Referenced Endpoints/,/^$/p' | sed '1d;/^$/d')"
  [[ "$listed" == "$4" ]] && ok "$1: text mode lists exactly the endpoints" || bad "$1: text mode lists exactly the endpoints" "got [$listed], want [$4]"
  run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" ep.md --json
  json_is "$1: --json counts $3, the same as the text list" 'd["referencedEndpointCount"] == '"$3"
}
endpoint_case "tools and api paths only" '# S\n\nCall /tools/search and /api/users here\n' 2 '/api/users
/tools/search'
endpoint_case "a method path and a bare path" '# S\n\nPOST /api/login then /api/users/me here\n' 2 '/api/users/me
POST /api/login'
endpoint_case "only a method path" '# S\n\nGET /health ok.\n' 1 'GET /health'
endpoint_case "no endpoints" '# S\n\nNothing here.\n' 0 ''

run_in "$PROJ" "$REVIEW/extract-spec-sections.sh" does-not-exist.md
check "missing spec file exits 1" 1 "" 'File not found'
run_in "$PROJ" "$REVIEW/extract-spec-sections.sh"
check "no argument exits 2, message on stderr" 2 "" 'spec file required'

echo "task-manifest.sh (create, review, implement)"
# manifest <label> <script> <workflow> <expected task count>
manifest() {
  run_in "$PROJ" "$2" "$3"
  check "$1 $3 exits 0" 0
  json_is "$1 $3 is a JSON array of $4 tasks with subject, activeForm and description" \
    'len(d) == '"$4"' and all(set(["subject", "activeForm", "description"]) <= set(t) for t in d)'
}
manifest create "$CREATE/task-manifest.sh" single-story 5
manifest create "$CREATE/task-manifest.sh" vertical-split 6
manifest review "$REVIEW/task-manifest.sh" full-review 5
manifest review "$REVIEW/task-manifest.sh" quick-check 2
manifest implement "$IMPLEMENT/task-manifest.sh" standard 7
manifest implement "$IMPLEMENT/task-manifest.sh" ui-heavy 9

# Every workflow in --list must run, so a new workflow cannot ship without a case here.
for pair in "create:$CREATE" "review:$REVIEW" "implement:$IMPLEMENT"; do
  name="${pair%%:*}"
  dir="${pair#*:}"
  run_in "$PROJ" "$dir/task-manifest.sh" --list
  wfs="$OUT"
  for wf in $wfs; do
    run_in "$PROJ" "$dir/task-manifest.sh" "$wf"
    check "$name listed workflow $wf runs" 0
    json_is "$name listed workflow $wf is a non-empty task array" 'len(d) > 0 and all(set(["subject", "activeForm", "description"]) <= set(t) for t in d)'
  done
  run_in "$PROJ" "$dir/task-manifest.sh" --list
  listed="$(printf '%s' "$OUT" | tr -s ' \n' '\n\n' | grep -c .)"
  expected=2
  [[ "$listed" == "$expected" ]] && ok "$name --list names $expected workflows" || bad "$name --list names $expected workflows" "got $listed: $OUT"
  run_in "$PROJ" "$dir/task-manifest.sh" --help
  check "$name --help exits 0" 0 'Usage: task-manifest\.sh'
  run_in "$PROJ" "$dir/task-manifest.sh" no-such-workflow
  [[ "$RC" != 0 ]] && ok "$name unknown workflow exits non-zero" || bad "$name unknown workflow exits non-zero" "exit 0"
  printf '%s' "$ERR$OUT" | grep -Eqi 'unknown workflow' && ok "$name unknown workflow says so" || bad "$name unknown workflow says so" "$ERR$OUT"
  run_in "$PROJ" "$dir/task-manifest.sh"
  [[ "$RC" != 0 ]] && ok "$name with no workflow exits non-zero" || bad "$name with no workflow exits non-zero" "exit 0"
done

# The old skill names must be gone from every task line. The new names must be there.
run_in "$PROJ" "$CREATE/task-manifest.sh" single-story
single="$OUT"
run_in "$PROJ" "$CREATE/task-manifest.sh" vertical-split
all="$single$OUT"
for wf in full-review quick-check; do
  run_in "$PROJ" "$REVIEW/task-manifest.sh" "$wf"
  all="$all$OUT"
done
for wf in standard ui-heavy; do
  run_in "$PROJ" "$IMPLEMENT/task-manifest.sh" "$wf"
  all="$all$OUT"
done
if printf '%s' "$all" | grep -Eq 'spec-(creator|review|implement)'; then
  bad "no task line names an old skill" "$(printf '%s' "$all" | grep -Eo '.{20}spec-(creator|review|implement).{20}' | head -2)"
else
  ok "no task line names an old skill"
fi
[[ "$(printf '%s' "$single" | grep -c 'run /spec:review, /simplify, or done')" == 1 ]] \
  && ok "create's post-creation task offers /spec:review" \
  || bad "create's post-creation task offers /spec:review" "$single"

echo "commands written in the SKILL.md files"
# Pull every command that starts with "${CLAUDE_SKILL_DIR}/scripts/ out of a SKILL.md
# (fenced bash lines and inline code spans), swap in the skill dir and a fixture spec
# path, and run each one from the fixture project. <SPEC_FILE> is a placeholder the
# model fills in; "$(git rev-parse --show-toplevel)" and . stay exactly as written.
extract_commands() { # <SKILL.md> <skill dir> <spec file>
  python3 - "$1" "$2" "$3" <<'EOF'
import re, sys
text, skill_dir, spec = open(sys.argv[1], encoding="utf-8").read(), sys.argv[2], sys.argv[3]
cmds, inside, lang = [], False, ""
for line in text.splitlines():
    m = re.match(r"^\s*```(\w*)\s*$", line)
    if m:
        inside, lang = (not inside), (m.group(1) if not inside else "")
        continue
    if inside:
        if lang in ("bash", "sh", "shell") and line.lstrip().startswith('"${CLAUDE_SKILL_DIR}/scripts/'):
            cmds.append(re.sub(r"\s+#.*$", "", line.strip()))
    else:
        for span in re.findall(r"`([^`\n]+)`", line):
            if span.startswith('"${CLAUDE_SKILL_DIR}/scripts/') and "<name>" not in span:  # the Paths note shows the shape, not a command
                cmds.append(span)
for c in cmds:
    print(c.replace("${CLAUDE_SKILL_DIR}", skill_dir).replace("<SPEC_FILE>", spec))
EOF
}
# A spec path with a space: a placeholder written without quotes in the text splits into two arguments and fails.
SPEC_SPACE="specs/stories/epic-1/story with space.md"
cp "$PROJ/$SPEC_REL" "$PROJ/$SPEC_SPACE"
for skill in create review implement; do
  cmds="$(extract_commands "$SKILLS/$skill/SKILL.md" "$SKILLS/$skill" "$SPEC_SPACE")"
  n=0
  while IFS= read -r cmd; do
    [[ -z "$cmd" ]] && continue
    n=$((n + 1))
    run_in "$PROJ" bash -c "$cmd"
    [[ "$RC" == 0 && -n "$OUT" ]] && ok "$skill SKILL.md command runs: ${cmd#*/scripts/}" || bad "$skill SKILL.md command runs: ${cmd#*/scripts/}" "exit $RC, stderr: $ERR"
  done <<< "$cmds"
  [[ "$n" -ge 1 ]] && ok "$skill SKILL.md: found $n script command(s) to run" || bad "$skill SKILL.md: found no script commands to run" "the extractor matched nothing"
done

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
