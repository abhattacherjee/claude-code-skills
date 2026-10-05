#!/usr/bin/env bash
set -euo pipefail

# run-tests.sh — smoke tests for the scripts and the wiring of the demo-video plugin.
#
# Every script runs the way its SKILL.md calls it: by absolute path, from a temp
# project directory (never the skill directory), in a clean environment (`env -i`,
# so nothing leaks in from the caller's shell). HOME points at a temp dir. The plugin
# is copied to a path with a space first, so a script that finds its files relative
# to its own location, or does not quote a path, fails here.
#
# Nothing here touches the network, the screen, npm, Homebrew or a TTS service. The
# scripts run with stub `brew`, `pip`, `pip3`, `npm`, `npx`, `curl` and `open` first on
# PATH. A stub only logs its call, and the run fails at the end if any call was
# logged, so a script that starts an install or a request cannot pass.
#
# Needs bash 3.2+ and python3 (standard library). ffmpeg, opencv and a screen are NOT
# needed: a test that would need one prints a SKIP line, or is run with the module
# blocked, so it gives the same answer on a runner that has none.
#
# Usage: bash plugins/demo-video/tests/run-tests.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin copy" "$TMP/home" "$TMP/proj" "$TMP/work" "$TMP/stubs" "$TMP/nocv"
# Copy everything but tests/, so a scan of the copy does not read this file.
for item in .claude-plugin skills agents README.md CHANGELOG.md LICENSE; do
  cp -R "$PLUGIN/$item" "$TMP/plugin copy/$item"
done
ROOT="$TMP/plugin copy"
SKILLS="$ROOT/skills"
AGENTS="$ROOT/agents"
REC="$SKILLS/record/scripts"
PRO="$SKILLS/produce/scripts"
echo "plugin under test: $ROOT"

PROJ="$TMP/proj"
HOME_DIR="$TMP/home"
STUB_LOG="$TMP/stub-calls"
: > "$STUB_LOG"

# Stubs that log a call and do nothing. If a script reaches one, the final check fails.
for name in brew pip pip3 npm npx curl open; do
  printf '#!/bin/sh\necho "%s $*" >> "$STUB_LOG"\nexit 0\n' "$name" > "$TMP/stubs/$name"
  chmod +x "$TMP/stubs/$name"
done
# A module that cannot be imported, to make "opencv is not installed" true on any machine.
for mod in cv2 numpy Quartz; do
  printf 'raise ImportError("blocked by run-tests.sh")\n' > "$TMP/nocv/$mod.py"
done

PASS=0
FAIL=0
SKIPPED=0
ok()   { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }
skip() { SKIPPED=$((SKIPPED + 1)); printf '  SKIP  %s\n' "$1"; }

# A clean environment with the stubs first on PATH.
cenv() {
  env -i PATH="$TMP/stubs:$PATH" HOME="$HOME_DIR" STUB_LOG="$STUB_LOG" PYTHONDONTWRITEBYTECODE=1 \
    GIT_CONFIG_NOSYSTEM=1 "$@"
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

# file_json_is <label> <file> <python-expr over d>: the file must be valid JSON and the expression true.
file_json_is() {
  local label="$1" file="$2" expr="$3" res
  if res="$(python3 -c 'import json,sys
d = json.load(open(sys.argv[1]))
print("yes" if eval(sys.argv[2]) else "no")' "$file" "$expr" 2>&1)" && [[ "$res" == "yes" ]]; then
    ok "$label"
  else
    bad "$label" "JSON check failed ($expr): $res"
  fi
}

# has <label> <file> <fixed-string>: the file contains the text.
has()   { grep -Fq -- "$3" "$2" && ok "$1" || bad "$1" "no '$3' in $2"; }
# lacks <label> <file> <fixed-string>: the file does not contain the text.
lacks() { grep -Fq -- "$3" "$2" && bad "$1" "found '$3' in $2" || ok "$1"; }

# The scripts start with `#!/usr/bin/env bash`. EXPECT_BASH_MAJOR (set by CI) pins the version.
echo "bash under test: $BASH_VERSION"
run_in "$PROJ" /usr/bin/env bash -c 'echo "${BASH_VERSINFO[0]}"'
[[ "$OUT" == "${BASH_VERSINFO[0]}" ]] && ok "scripts run under bash $OUT, the same major version as the tests" || bad "scripts run under the same bash as the tests" "env bash is $OUT, test shell is ${BASH_VERSINFO[0]}"
if [[ -n "${EXPECT_BASH_MAJOR:-}" ]]; then
  [[ "$OUT" == "$EXPECT_BASH_MAJOR" ]] && ok "bash major version is the expected $EXPECT_BASH_MAJOR" || bad "bash major version is the expected $EXPECT_BASH_MAJOR" "got $OUT"
fi

# ---------------------------------------------------------------------------
echo "plugin layout"
EXPECTED_AGENTS="demo-storyteller demo-director zoom-qa-verifier voiceover-timing-fixer demo-post-production-editor product-video-storyteller product-video-narrator product-video-music-curator product-video-audio-mixer"
n_agents="$(find "$AGENTS" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')"
[[ "$n_agents" == 9 ]] && ok "agents/ has 9 agent files" || bad "agents/ has 9 agent files" "found $n_agents"
for a in $EXPECTED_AGENTS; do
  if [[ -f "$AGENTS/$a.md" ]] && grep -Eq "^name: $a\$" "$AGENTS/$a.md"; then
    ok "agents/$a.md exists and keeps the bare name: $a"
  else
    bad "agents/$a.md exists and keeps the bare name: $a" "missing file or no 'name: $a' line"
  fi
done
plugin_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
for skill in record produce; do
  [[ -f "$SKILLS/$skill/SKILL.md" ]] && ok "skills/$skill/SKILL.md exists" || bad "skills/$skill/SKILL.md exists" "missing"
  grep -Eq "^name: $skill\$" "$SKILLS/$skill/SKILL.md" && ok "$skill SKILL.md has name: $skill" || bad "$skill SKILL.md has name: $skill" "no such line"
  grep -Eq "^  version: $plugin_version\$" "$SKILLS/$skill/SKILL.md" && ok "$skill SKILL.md version is the plugin version ($plugin_version)" || bad "$skill SKILL.md version is the plugin version ($plugin_version)" "no 'version: $plugin_version' line"
done
for dir in "$SKILLS"/*/; do
  [[ "$(basename "$dir")" == record || "$(basename "$dir")" == produce ]] || bad "only record and produce are skills" "found $(basename "$dir")"
done

# ---------------------------------------------------------------------------
echo "every script named in a SKILL.md exists, is executable and answers --help"
# Pull each "${CLAUDE_SKILL_DIR}/scripts/<name>" out of a SKILL.md, resolve it against that
# skill's directory in the plugin copy, and run it with --help from the project dir. The
# stubs are first on PATH, so an installer that ignores --help only logs a call, and the
# stub-call check at the end fails.
for skill in record produce; do
  names="$(python3 - "$SKILLS/$skill/SKILL.md" <<'PYEND'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
seen = []
for m in re.finditer(r'"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_.-]+\.(?:sh|py))"', text):
    if m.group(1) not in seen:
        seen.append(m.group(1))
print("\n".join(seen))
PYEND
)" || names=""  # a python error leaves no names, and the count check below fails
  n=0
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    n=$((n + 1))
    if [[ ! -x "$SKILLS/$skill/scripts/$name" ]]; then
      bad "$skill SKILL.md names scripts/$name" "missing or not executable"
      continue
    fi
    # Without opencv and numpy (the blocked modules), --help must still work.
    run_in "$PROJ" env PYTHONPATH="$TMP/nocv" "$SKILLS/$skill/scripts/$name" --help
    check "$skill SKILL.md command runs: scripts/$name --help (no opencv)" 0
  done <<< "$names"
  [[ "$n" -ge 1 ]] && ok "$skill SKILL.md: found $n script command(s) to run" || bad "$skill SKILL.md: found no script commands to run" "the extractor matched nothing"
done

echo "SKILL.md never shows the substituted path tokens in prose"
# Claude Code replaces "${CLAUDE_SKILL_DIR}" and "${CLAUDE_PLUGIN_ROOT}" everywhere in a SKILL.md,
# prose and inline code included, before the model reads it. In a fenced code block the token is a
# real command for this skill's own scripts, which is what we want. Outside one the model would read
# this skill's absolute path where the text says something else. So outside fenced blocks the token
# must not appear.
for skill in record produce; do
  hits="$(python3 - "$SKILLS/$skill/SKILL.md" <<'PYEND'
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
PYEND
)" || hits="the python check failed (exit $?)"
  [[ -z "$hits" ]] && ok "$skill SKILL.md: no path token outside code blocks" \
    || bad "$skill SKILL.md: path token outside a code block (it is substituted, so the model sees an absolute path)" "$hits"
done

# ---------------------------------------------------------------------------
echo "nothing under the plugin depends on an old install path"
# The skills and agents run from the plugin cache. A path in a user's ~/.claude skills or
# agents folder is a loose copy that the plugin replaces.
hits="$(grep -rEn '\.claude/(agents|skills)' "$ROOT" 2>/dev/null | head -3 || true)"
[[ -z "$hits" ]] && ok "no .claude/agents or .claude/skills path anywhere in the plugin" || bad "no .claude/agents or .claude/skills path anywhere in the plugin" "$hits"
for skill in record produce; do
  grep -Eq '^description: "Was the (smart-screen-recorder|product-video-creation) skill' "$SKILLS/$skill/SKILL.md" \
    && ok "$skill description names the old skill (a \"Was\" note)" || bad "$skill description names the old skill (a \"Was\" note)" "no 'Was the ... skill' at the start of the description"
done
hits="$(grep -rEn 'smart-screen-recorder|product-video-creation' "$SKILLS"/*/scripts "$AGENTS" 2>/dev/null | head -3 || true)"
[[ -z "$hits" ]] && ok "no script or agent names an old skill" || bad "no script or agent names an old skill" "$hits"

# ---------------------------------------------------------------------------
echo "agents are started by plugin agent type"
# Each SKILL.md names its agents as subagent_type: "demo-video:<agent>". Every such name has an
# agent file with that bare name, and every agent is started by some SKILL.md.
types="$(grep -hoE 'subagent_type: "[^"]*"' "$SKILLS"/record/SKILL.md "$SKILLS"/produce/SKILL.md | sort -u || true)"
n_types="$(printf '%s\n' "$types" | grep -c . || true)"
[[ "$n_types" -ge 1 ]] && ok "found $n_types subagent_type launch name(s)" || bad "found subagent_type launch names" "none found"
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  t="${line#subagent_type: \"}"
  t="${t%\"}"
  case "$t" in
    demo-video:*)
      a="${t#demo-video:}"
      if [[ -f "$AGENTS/$a.md" ]] && grep -Eq "^name: $a\$" "$AGENTS/$a.md"; then
        ok "launch type $t has an agent file with that name"
      else
        bad "launch type $t has an agent file with that name" "no agents/$a.md with 'name: $a'"
      fi ;;
    *) bad "launch type $t is demo-video:<agent>" "other types are not plugin agents" ;;
  esac
done <<< "$types"
for a in $EXPECTED_AGENTS; do
  if grep -Fq "subagent_type: \"demo-video:$a\"" "$SKILLS/record/SKILL.md" "$SKILLS/produce/SKILL.md"; then
    ok "agent $a is started by a SKILL.md as demo-video:$a"
  else
    bad "agent $a is started by a SKILL.md as demo-video:$a" "no subagent_type: \"demo-video:$a\" in either SKILL.md"
  fi
done
for skill in record produce; do
  grep -Fq 'general-purpose' "$SKILLS/$skill/SKILL.md" && bad "$skill SKILL.md does not start a general-purpose agent" "$(grep -Fn general-purpose "$SKILLS/$skill/SKILL.md" | head -1)" || ok "$skill SKILL.md does not start a general-purpose agent"
done

# ---------------------------------------------------------------------------
echo "install-deps.sh (record)"
run_in "$PROJ" "$REC/install-deps.sh" --help
check "--help exits 0 and shows usage" 0 'USAGE:'
run_in "$PROJ" "$REC/install-deps.sh" --bogus
check "an unknown option exits 2 with a message" 2 "" 'Unknown option: --bogus'

echo "record.sh"
run_in "$PROJ" "$REC/record.sh" --help
check "--help exits 0 and shows usage" 0 'USAGE:'
case "$OUT" in
  *"$REC/install-deps.sh"*) ok "--help names the install-deps.sh path next to the script" ;;
  *) bad "--help names the install-deps.sh path next to the script" "got: $(printf '%s' "$OUT" | tail -2)" ;;
esac
run_in "$PROJ" "$REC/record.sh" --bogus
check "an unknown option exits 2" 2
run_in "$PROJ" "$REC/record.sh" -o
check "an option with no value exits 2 with a message" 2 "" 'Option -o needs a value'
run_in "$PROJ" "$REC/record.sh" --fps
check "--fps with no value exits 2 with a message" 2 "" 'Option --fps needs a value'

# ---------------------------------------------------------------------------
# build-timeline.py, generate-tts.py, render-timeline.py and mix-audio.py read and write
# fixed paths under ~/Desktop/zoom-analysis. HOME is a temp dir here, so the fixture goes
# in $HOME/Desktop/zoom-analysis. build-timeline.py also has a fixed list of speech groups
# (seg_00, seg_02 ...), so the fixture uses those ids.
ZA="$HOME_DIR/Desktop/zoom-analysis"
mkdir -p "$ZA/tts"
cat > "$ZA/zoom-script.json" <<'PYEND'
{"trim": {"start": 0, "end": 40},
 "hold_frames": [
   {"source_time": 2.0,  "hold_duration": 3.0, "description": "landing"},
   {"source_time": 19.0, "hold_duration": 3.0, "description": "interests"},
   {"source_time": 28.0, "hold_duration": 2.0, "description": "generation"}]}
PYEND
cat > "$ZA/voiceover-script.json" <<'PYEND'
{"voice": "nova",
 "segments": [{"id": "seg_00", "text": "Hello.", "duration": 2, "start_time": 0}]}
PYEND
cat > "$ZA/tts/tts-manifest.json" <<PYEND
[{"id": "seg_00", "file": "$ZA/tts/seg_00.mp3", "actual_duration": 4.0},
 {"id": "seg_06", "file": "$ZA/tts/seg_06.mp3", "actual_duration": 2.0},
 {"id": "seg_07", "file": "$ZA/tts/seg_07.mp3", "actual_duration": 2.5},
 {"id": "seg_09", "file": "$ZA/tts/seg_09.mp3", "actual_duration": 3.0}]
PYEND

echo "build-timeline.py"
run_in "$PROJ" "$REC/build-timeline.py"
check "builds the timeline from the fixture" 0 'Timeline segments: 7'
file_json_is "the output has the source duration, the output duration, a timeline and TTS placements" "$ZA/integrated-timeline.json" \
  'd["source_duration"] == 40 and isinstance(d["output_duration"], float) and isinstance(d["timeline"], list) and isinstance(d["tts_placement"], list)'
file_json_is "3 holds and 4 plays, in the order play/hold" "$ZA/integrated-timeline.json" \
  '[t["type"] for t in d["timeline"]] == ["play","hold_narrate","play","hold_narrate","play","hold_narrate","play"]'
file_json_is "the output duration is the sum of the segment durations" "$ZA/integrated-timeline.json" \
  'abs(sum(t.get("duration", t.get("hold_duration", 0)) for t in d["timeline"]) - d["output_duration"]) < 1e-6'
file_json_is "a hold lasts as long as its speech: seg_00 is 4.0s plus a 0.3s buffer, seg_06 and seg_07 are 2.0s and 2.5s plus a 0.5s gap and the buffer" "$ZA/integrated-timeline.json" \
  'abs(d["timeline"][1]["hold_duration"] - 4.3) < 1e-6 and abs(d["timeline"][3]["hold_duration"] - 5.3) < 1e-6'
file_json_is "all 4 TTS segments are placed, in time order, the first after the first play (1.5s) and a 0.3s lead-in" "$ZA/integrated-timeline.json" \
  'len(d["tts_placement"]) == 4 and [p["output_time"] for p in d["tts_placement"]] == sorted(p["output_time"] for p in d["tts_placement"]) and abs(d["tts_placement"][0]["output_time"] - 1.8) < 1e-6 and d["tts_placement"][0]["file"].endswith("seg_00.mp3")'
mv "$ZA/zoom-script.json" "$ZA/zoom-script.json.off"
run_in "$PROJ" "$REC/build-timeline.py"
check "a missing zoom-script.json exits non-zero with a message" nonzero "" 'zoom-script.json'
mv "$ZA/zoom-script.json.off" "$ZA/zoom-script.json"

echo "generate-tts.py"
run_in "$PROJ" "$REC/generate-tts.py"
check "no OPENAI_API_KEY exits 1 with a message, before any request" 1 "" 'OPENAI_API_KEY not set'
mv "$ZA/voiceover-script.json" "$ZA/voiceover-script.json.off"
run_in "$PROJ" "$REC/generate-tts.py"
check "a missing voiceover-script.json exits non-zero with a message" nonzero "" 'voiceover-script.json'
mv "$ZA/voiceover-script.json.off" "$ZA/voiceover-script.json"

echo "mix-audio.py"
printf '{"tts_placement": []}' > "$ZA/integrated-timeline.json"
run_in "$PROJ" "$REC/mix-audio.py"
check "a timeline with no TTS placements exits 1 with a message" 1 "" 'No TTS segments'
rm -f "$ZA/integrated-timeline.json"
run_in "$PROJ" "$REC/mix-audio.py"
check "a missing integrated-timeline.json exits non-zero with a message" nonzero "" 'integrated-timeline.json'

echo "render-timeline.py and the opencv scripts"
run_in "$PROJ" env PYTHONPATH="$TMP/nocv" "$REC/render-timeline.py"
check "render-timeline.py without opencv exits 1 and says what to install" 1 "" 'pip3 install opencv-python numpy'
run_in "$PROJ" env PYTHONPATH="$TMP/nocv" "$REC/extract-frames.py" video.mp4 cursor.jsonl
check "extract-frames.py without opencv exits 1 and says what to install" 1 "" 'pip3 install opencv-python'
skip "render-timeline.py rendering: needs opencv, ffmpeg and a fixed raw-video path (a real recording)"
skip "record.sh recording: needs a screen and ffmpeg"

# ---------------------------------------------------------------------------
echo "task-manifest.sh (produce)"
for wf in full-video visual-only screenshots brand-update voiceover-only; do
  run_in "$PROJ" "$PRO/task-manifest.sh" "$wf"
  check "$wf exits 0" 0
  json_is "$wf is a JSON array of tasks, each with subject, activeForm and description" \
    'isinstance(d, list) and len(d) >= 1 and all(set(t) == {"subject","activeForm","description"} and all(isinstance(v, str) and v for v in t.values()) for t in d)'
  # The help says how many tasks each workflow has. Count them from the JSON.
  want="$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo '?')"
  run_in "$PROJ" "$PRO/task-manifest.sh" --help
  got="$(printf '%s\n' "$OUT" | sed -n -E "s/^ +$wf +.*\(([0-9]+) tasks\).*/\1/p")"
  [[ "$got" == "$want" ]] && ok "the help says $wf has $want tasks" || bad "the help says $wf has $want tasks" "help says '$got'"
  # Any agent the manifest tells you to launch is a plugin agent type.
  run_in "$PROJ" "$PRO/task-manifest.sh" "$wf"
  bare="$(printf '%s' "$OUT" | grep -oE 'Launch [A-Za-z:_-]+' | grep -v 'Launch demo-video:' || true)"
  [[ -z "$bare" ]] && ok "$wf: every Launch line names demo-video:<agent>" || bad "$wf: every Launch line names demo-video:<agent>" "$bare"
  for t in $(printf '%s' "$OUT" | grep -oE 'Launch demo-video:[A-Za-z-]+' | sed 's/Launch demo-video://' | sort -u); do
    [[ -f "$AGENTS/$t.md" ]] && ok "$wf: agent $t exists" || bad "$wf: agent $t exists" "no agents/$t.md"
  done
done
run_in "$PROJ" "$PRO/task-manifest.sh" --list
check "--list names 5 workflows" 0 'voiceover-only'
[[ "$(printf '%s\n' "$OUT" | grep -c .)" == 5 ]] && ok "--list prints exactly 5 names" || bad "--list prints exactly 5 names" "$OUT"
run_in "$PROJ" "$PRO/task-manifest.sh" nope
check "an unknown workflow exits 2 with a message" 2 "" 'Unknown workflow: nope'
run_in "$PROJ" "$PRO/task-manifest.sh"
check "no workflow exits 2 with the usage" 2 "" 'Usage: task-manifest.sh'
run_in "$PROJ" "$PRO/task-manifest.sh" --help
check "--help exits 0 and shows usage" 0 'Usage: task-manifest.sh'

echo "scaffold-project.sh (produce)"
SP="$TMP/work/my video"
run_in "$PROJ" "$PRO/scaffold-project.sh" "$SP" --skip-install --aspect 16:9
check "scaffolds into a directory with a space (--skip-install)" 0 'Project scaffolded'
for f in package.json remotion.config.ts tsconfig.json eslint.config.mjs src/index.css src/index.ts src/Root.tsx src/Composition.tsx; do
  [[ -f "$SP/$f" ]] && ok "scaffold wrote $f" || bad "scaffold wrote $f" "missing"
done
for d in src/scenes public/screenshots public/audio; do
  [[ -d "$SP/$d" ]] && ok "scaffold made $d/" || bad "scaffold made $d/" "missing"
done
file_json_is "package.json is valid JSON, named after the directory, and does not name an old skill" "$SP/package.json" \
  'd["name"] == "my video" and "product-video-creation" not in d["description"] and "demo-video:produce" in d["description"] and "remotion" in d["dependencies"]'
has "--aspect 16:9 sets the width in Root.tsx" "$SP/src/Root.tsx" "width={1920}"
has "--aspect 16:9 sets the height in Root.tsx" "$SP/src/Root.tsx" "height={1080}"
before="$(cksum < "$SP/package.json")"
run_in "$PROJ" "$PRO/scaffold-project.sh" "$SP" --skip-install
check "an existing Remotion project is left alone, exit 0" 0 'already exists'
[[ "$(cksum < "$SP/package.json")" == "$before" ]] && ok "the existing project's package.json is unchanged" || bad "the existing project's package.json is unchanged" "checksum changed"
run_in "$PROJ" "$PRO/scaffold-project.sh" "$TMP/work/quoted" --skip-install --name 'a"b\c'
check "a quote and a backslash in --name: exits 0" 0
file_json_is "a quote and a backslash in --name still give valid JSON, with the name intact" "$TMP/work/quoted/package.json" 'd["name"] == "a\"b\\c"'
# Without --skip-install the script runs npm install. A failing install must fail the script
# (a pipe to tail used to hide it), and a working one must be called once, in the project.
mkdir -p "$TMP/npm-fail" "$TMP/npm-ok"
printf '#!/bin/sh\necho "npm ERR! boom"\nexit 1\n' > "$TMP/npm-fail/npm"
printf '#!/bin/sh\necho "$PWD: npm $*" >> "%s/npm-ok-log"\necho added 1 package\n' "$TMP" > "$TMP/npm-ok/npm"
chmod +x "$TMP/npm-fail/npm" "$TMP/npm-ok/npm"
run_in "$PROJ" env PATH="$TMP/npm-fail:$PATH" "$PRO/scaffold-project.sh" "$TMP/work/npm-fails"
check "a failing npm install exits 1 and says so" 1 "" 'npm install failed'
run_in "$PROJ" env PATH="$TMP/npm-ok:$PATH" "$PRO/scaffold-project.sh" "$TMP/work/npm-works"
check "a working npm install exits 0" 0 'Project scaffolded'
[[ "$(cat "$TMP/npm-ok-log" 2>/dev/null)" == "$TMP/work/npm-works: npm install" ]] && ok "npm install ran once, inside the new project" || bad "npm install ran once, inside the new project" "log: $(cat "$TMP/npm-ok-log" 2>/dev/null)"
run_in "$PROJ" "$PRO/scaffold-project.sh" "$TMP/work/bad-aspect" --skip-install --aspect 4:3
check "an unknown aspect ratio exits 2 with a message" 2 "" 'Unknown aspect ratio'
[[ ! -e "$TMP/work/bad-aspect" ]] && ok "an unknown aspect ratio creates nothing" || bad "an unknown aspect ratio creates nothing" "directory exists"
run_in "$PROJ" "$PRO/scaffold-project.sh" --skip-install
check "no project directory exits 2 with a message" 2 "" 'project directory is required'
run_in "$PROJ" "$PRO/scaffold-project.sh" "$TMP/work/x" --name
check "--name with no value exits 2 with a message" 2 "" 'Option --name needs a value'
run_in "$PROJ" "$PRO/scaffold-project.sh" "$TMP/work/x" --bogus
check "an unknown option exits 2" 2 "" 'Unknown option: --bogus'

echo "generate-voiceover.sh (produce)"
run_in "$PROJ" "$PRO/generate-voiceover.sh" --list-voices --provider openai
check "--list-voices --provider openai exits 0" 0 'coral'
[[ "$(printf '%s\n' "$OUT" | grep -cE '^  [a-z]+ +- ')" == 13 ]] && ok "--list-voices lists 13 OpenAI voices" || bad "--list-voices lists 13 OpenAI voices" "$(printf '%s\n' "$OUT" | grep -cE '^  [a-z]+ +- ') listed"
# Every voice the script lists is in the voice table of SKILL.md.
for v in $(printf '%s\n' "$OUT" | sed -n -E 's/^  ([a-z]+) +- .*/\1/p'); do
  grep -Fq "| **$v** |" "$SKILLS/produce/SKILL.md" && ok "voice $v is in the SKILL.md voice table" || bad "voice $v is in the SKILL.md voice table" "missing"
done
run_in "$PROJ" "$PRO/generate-voiceover.sh" --list-voices --provider nope
check "--list-voices with an unknown provider exits 2 with a message" 2 "" 'Unknown provider: nope'
run_in "$PROJ" "$PRO/generate-voiceover.sh" --provider nope narration.json out
check "an unknown provider exits 2" 2 "" 'Unknown provider: nope'
run_in "$PROJ" "$PRO/generate-voiceover.sh" --provider openai
check "no script file and output dir exits 2 with a message" 2 "" 'script file and output directory are required'
run_in "$PROJ" "$PRO/generate-voiceover.sh" --provider openai missing.json "$TMP/work/audio"
check "a missing script file exits 1 with a message" 1 "" 'script file not found'
printf '[{"scene":"hook","text":"Hi."}]' > "$TMP/work/narration.json"
run_in "$PROJ" "$PRO/generate-voiceover.sh" --provider openai "$TMP/work/narration.json" "$TMP/work/audio"
check "openai with no OPENAI_API_KEY exits 1 with a message, before any request" 1 "" 'OPENAI_API_KEY not set'
run_in "$PROJ" "$PRO/generate-voiceover.sh" --voice
check "--voice with no value exits 2 with a message" 2 "" 'Option --voice needs a value'

echo "capture-screenshots.sh (produce)"
run_in "$PROJ" "$PRO/capture-screenshots.sh"
check "no output directory exits 2 with a message" 2 "" 'output directory is required'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --url
check "--url with no value exits 2 with a message" 2 "" 'Option --url needs a value'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --bogus out
check "an unknown option exits 2" 2 "" 'Unknown option: --bogus'
skip "capture-screenshots.sh capture: needs Playwright, a browser and a running app"

echo "render-and-preview.sh (produce)"
run_in "$PROJ" "$PRO/render-and-preview.sh" --output
check "--output with no value exits 2 with a message" 2 "" 'Option --output needs a value'
run_in "$PROJ" "$PRO/render-and-preview.sh" --bogus
check "an unknown option exits 2" 2 "" 'Unknown option: --bogus'
run_in "$PROJ" "$PRO/render-and-preview.sh" --no-open
check "no src/Root.tsx and no composition id exits 1 with a message, before lint" 1 "" 'Could not auto-detect composition ID'
skip "render-and-preview.sh render: needs a Remotion project, npm install and ffmpeg"

# ---------------------------------------------------------------------------
echo "nothing started an install or a request"
# The stubs log each call. A script that reached brew, pip, npm, npx, curl or open ends up here.
if [[ -s "$STUB_LOG" ]]; then
  bad "no stubbed command (brew pip npm npx curl open) was called" "$(head -3 "$STUB_LOG")"
else
  ok "no stubbed command (brew pip npm npx curl open) was called"
fi

echo
echo "passed: $PASS  failed: $FAIL  skipped: $SKIPPED"
[[ "$FAIL" -eq 0 ]]
