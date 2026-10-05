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
# A fake opencv (and an empty numpy), first on PYTHONPATH, so the scripts that read video run
# without opencv or a real video. A "video" is a text file: line 1 is "FAKEVIDEO <frames>
# <width> <height> <fps>". Any other file does not open. Frames are tiny byte strings.
mkdir -p "$TMP/fakecv"
: > "$TMP/fakecv/numpy.py"
cat > "$TMP/fakecv/cv2.py" <<'PYEND'
CAP_PROP_POS_FRAMES, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT, CAP_PROP_FPS, CAP_PROP_FRAME_COUNT = 1, 3, 4, 5, 7
INTER_LANCZOS4 = 4
IMWRITE_JPEG_QUALITY = 1


class _Frame:
    def __init__(self, w, h):
        self.shape = (h, w, 3)
        self.size = w * h * 3

    def __getitem__(self, key):
        return self

    def tobytes(self):
        return b"f"


class VideoCapture:
    def __init__(self, path):
        self.pos = 0
        self.ok = False
        try:
            head = open(path).readline().split()
        except (OSError, UnicodeDecodeError):
            return
        if head[:1] == ["FAKEVIDEO"]:
            self.n, self.w, self.h, self.fps = int(head[1]), int(head[2]), int(head[3]), float(head[4])
            self.ok = True

    def isOpened(self):
        return self.ok

    def get(self, prop):
        if not self.ok:
            return 0
        return {CAP_PROP_FPS: self.fps, CAP_PROP_FRAME_COUNT: self.n,
                CAP_PROP_FRAME_WIDTH: self.w, CAP_PROP_FRAME_HEIGHT: self.h}.get(prop, 0)

    def set(self, prop, value):
        if prop == CAP_PROP_POS_FRAMES:
            self.pos = int(value)

    def read(self):
        if self.ok and 0 <= self.pos < self.n:
            self.pos += 1
            return True, _Frame(self.w, self.h)
        return False, None

    def release(self):
        pass


def resize(frame, size, interpolation=None):
    return _Frame(size[0], size[1])


def imwrite(path, frame, params=None):
    with open(path, "wb") as f:
        f.write(b"jpg")
    return True
PYEND

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
# no_traceback <label>: the last run's stderr has no Python traceback.
no_traceback() { case "$ERR" in *Traceback*) bad "$1" "$(printf '%s' "$ERR" | tail -3)" ;; *) ok "$1" ;; esac; }

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
no_traceback "a missing voiceover-script.json gives a clean message, not a traceback"
mv "$ZA/voiceover-script.json.off" "$ZA/voiceover-script.json"

# A fake OpenAI API on a free 127.0.0.1 port (OPENAI_BASE_URL points there). It answers 401
# with a JSON error body for any input holding "FAIL", and fake mp3 bytes otherwise, and logs
# each request. curl is the logging stub: the key must never go on a command line.
cat > "$TMP/tts-harness.py" <<'PYEND'
import http.server, json, os, subprocess, sys, threading
script, home, stubs, log = sys.argv[1:5]
seen = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, self.headers.get("Authorization"), body))
        if "FAIL" in body["input"]:
            out, code, ctype = b'{"error": {"message": "bad key"}}', 401, "application/json"
        else:
            out, code, ctype = b"ID3 fake mp3 " + body["input"].encode(), 200, "audio/mpeg"
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
za = os.path.join(home, "Desktop", "zoom-analysis")
os.makedirs(za, exist_ok=True)
results = []
def check(name, cond, detail=""):
    results.append(("PASS " if cond else "FAIL ") + name + ("" if cond else " :: " + str(detail)[:300]))
def run(segments):
    json.dump({"voice": "nova", "segments": segments}, open(os.path.join(za, "voiceover-script.json"), "w"))
    env = {"PATH": stubs + os.pathsep + os.environ["PATH"], "HOME": home, "STUB_LOG": log,
           "OPENAI_API_KEY": "sk-test-secret", "OPENAI_BASE_URL": "http://127.0.0.1:%d/v1" % srv.server_address[1]}
    return subprocess.run([script], env=env, capture_output=True, text=True)
seg = lambda i, t: {"id": i, "text": t, "duration": 1.5, "start_time": 0.0}
r = run([seg("seg_ok", "Hello there."), seg("seg_bad", "FAIL please"), seg("seg_quiet", "")])
check("one failed segment of two exits 1 with a count", r.returncode == 1 and "1 of 2 segments failed: seg_bad" in r.stderr, (r.returncode, r.stderr[-300:]))
check("no traceback", "Traceback" not in r.stderr, r.stderr[-300:])
tts = os.path.join(za, "tts")
check("the good segment is saved as an mp3", os.path.exists(os.path.join(tts, "seg_ok.mp3")) and open(os.path.join(tts, "seg_ok.mp3"), "rb").read().startswith(b"ID3"))
check("the error body is not saved as an mp3", not os.path.exists(os.path.join(tts, "seg_bad.mp3")))
try:
    man = json.load(open(os.path.join(tts, "tts-manifest.json")))
except Exception as e:
    man = e
check("the manifest lists only the good segment", isinstance(man, list) and [m["id"] for m in man] == ["seg_ok"], man)
check("the key went in the Authorization header", bool(seen) and all(a == "Bearer sk-test-secret" for _, a, _ in seen), seen[:1])
check("the empty-text segment (a silence beat) made no request", len(seen) == 2, len(seen))
check("no curl call (it would put the key on a command line)", not os.path.exists(log) or "curl" not in open(log).read(), open(log).read() if os.path.exists(log) else "")
n0 = len(seen)
r = run([seg("seg_00", "Hi."), seg("../evil", "Escape.")])
check("an id with ../ exits 1 before any request", r.returncode == 1 and "'../evil' must be letters" in r.stderr and len(seen) == n0, (r.returncode, r.stderr[-200:], len(seen) - n0))
check("an id with ../ writes nothing outside the tts dir", not os.path.exists(os.path.join(za, "evil.mp3")))
print("\n".join(results))
PYEND
mkdir -p "$TMP/tts-home"
printf '#!/bin/sh\necho "{\\"format\\": {\\"duration\\": \\"2.25\\"}}"\n' > "$TMP/tts-ffprobe"
mkdir -p "$TMP/tts-bin" && mv "$TMP/tts-ffprobe" "$TMP/tts-bin/ffprobe" && chmod +x "$TMP/tts-bin/ffprobe"
: > "$TMP/tts-curl-log"
res="$(python3 "$TMP/tts-harness.py" "$REC/generate-tts.py" "$TMP/tts-home" "$TMP/tts-bin:$TMP/stubs" "$TMP/tts-curl-log" 2>&1)" || true
n=0
while IFS= read -r line; do
  case "$line" in
    "PASS "*) ok "generate-tts.py: ${line#PASS }"; n=$((n + 1)) ;;
    "FAIL "*) bad "generate-tts.py: ${line#FAIL }"; n=$((n + 1)) ;;
  esac
done <<< "$res"
[[ "$n" -eq 10 ]] && ok "generate-tts.py: the harness ran all 10 checks" || bad "generate-tts.py: the harness ran all 10 checks" "ran $n; output: $(printf '%s' "$res" | tail -5)"

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

echo "preview-timeline.py (fake opencv)"
PV="$TMP/pv proj"
mkdir -p "$PV/tts"
printf 'FAKEVIDEO 30 40 20 30\n' > "$PV/raw.mp4"
printf 'junk\n' > "$PV/bad.mp4"
printf '{"trim": {"start": 0, "end": 1}, "events": []}' > "$PV/zoom.json"
printf '{"timeline": [{"type": "play", "source_start": 0, "source_end": 0.5, "duration": 0.5}, {"type": "hold_narrate", "source_time": 9.0, "hold_duration": 1.0, "segments": [], "description": "late"}], "tts_placement": []}' > "$PV/timeline.json"
run_in "$PV" env PYTHONPATH="$TMP/fakecv" "$REC/preview-timeline.py" bad.mp4 zoom.json timeline.json tts --no-serve
check "a video that does not open exits 1 with a message" 1 "" 'cannot open the video bad.mp4'
run_in "$PV" env PYTHONPATH="$TMP/fakecv" "$REC/preview-timeline.py" raw.mp4 zoom.json timeline.json tts --no-serve
check "a hold past the end of the video: exit 0 with a warning" 0 "" '1 of 2 preview frames could not be read'
run_in "$PV" env PYTHONPATH="$TMP/nocv" "$REC/preview-timeline.py" raw.mp4 zoom.json timeline.json tts --no-serve
check "without opencv: exit 1 and says what to install" 1 "" 'pip3 install opencv-python'

# The server, the HTML and the mp3 copy, driven through the module: a server on a free
# 127.0.0.1 port in a thread, and requests with chosen Host and Origin headers.
cat > "$TMP/pv-harness.py" <<'PYEND'
import http.client, importlib.util, json, os, sys, threading, time
spec = importlib.util.spec_from_file_location("pt", sys.argv[1])
pt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pt)
work = sys.argv[2]
out = os.path.join(work, "site")
tts = os.path.join(work, "tts")
os.makedirs(out, exist_ok=True)
os.makedirs(tts, exist_ok=True)
results = []
def check(name, cond, detail=""):
    results.append(("PASS " if cond else "FAIL ") + name + ("" if cond else " :: " + str(detail)))

try:
    server, token = pt.make_server(out, 0, "tok123")
except Exception as e:
    print("FAIL make_server exists and builds a server :: %r" % (e,))
    sys.exit(0)
host, port = server.server_address
check("the server listens on 127.0.0.1 only", host == "127.0.0.1", host)
open(os.path.join(out, "preview.html"), "w").write("<p>hi</p>")
threading.Thread(target=server.serve_forever, daemon=True).start()

def req(method, path, body=None, headers=None, host_header=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True)
    c.putheader("Host", host_header or ("127.0.0.1:%d" % port))
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    if body is not None:
        c.putheader("Content-Length", str(len(body)))
    c.endheaders()
    if body is not None:
        c.send(body)
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data

st, h, d = req("GET", "/tok123/preview.html")
check("GET with the token serves the page", st == 200 and d == b"<p>hi</p>", (st, d[:40]))
st, _, _ = req("GET", "/preview.html")
check("GET without the token is refused (403)", st == 403, st)
st, _, _ = req("GET", "/wrong1/preview.html")
check("GET with a wrong token is refused (403)", st == 403, st)
st, _, _ = req("GET", "/tok123/preview.html", host_header="evil.example:%d" % port)
check("GET with a foreign Host header is refused (403, DNS rebinding)", st == 403, st)
fb = os.path.join(out, "feedback.json")
good = json.dumps([{"section": 0, "label": "HOLD", "feedback": "too fast"}]).encode()
jh = {"Content-Type": "application/json"}
st, _, _ = req("POST", "/feedback", good, jh)
check("POST without the token is refused (403)", st == 403, st)
st, _, _ = req("POST", "/tok123/feedback", good, dict(jh, Origin="http://evil.example"))
check("POST from another origin is refused (403)", st == 403, st)
st, _, _ = req("POST", "/tok123/feedback", good, {"Content-Type": "text/plain"})
check("POST that is not application/json is refused (415)", st == 415, st)
st, _, _ = req("POST", "/tok123/feedback", b"not json", jh)
check("POST of invalid JSON is refused (400)", st == 400, st)
st, _, _ = req("POST", "/tok123/feedback", b'{"a": 1}', jh)
check("POST of JSON that is not a list of objects is refused (400)", st == 400, st)
c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
c.putrequest("POST", "/tok123/feedback", skip_host=True)
c.putheader("Host", "127.0.0.1:%d" % port)
c.putheader("Content-Type", "application/json")
c.putheader("Content-Length", str(pt.MAX_FEEDBACK_BYTES + 1))
c.endheaders()
st = c.getresponse().status
check("POST larger than the cap is refused (413) before reading it", st == 413, st)
check("no refused POST wrote feedback.json", not os.path.exists(fb))
st, h, _ = req("POST", "/tok123/feedback", good, dict(jh, Origin="http://127.0.0.1:%d" % port))
check("POST with the token, JSON and our Origin is saved (200)", st == 200, st)
check("the reply has no Access-Control-Allow-Origin header", not any(k.lower() == "access-control-allow-origin" for k in h), h)
saved = json.load(open(fb)) if os.path.exists(fb) else None
check("feedback.json holds the posted list", saved == json.loads(good), saved)
server.shutdown()

# HTML: text from the JSON files is escaped. A regenerated mp3 is copied again.
open(os.path.join(tts, "seg_00.mp3"), "w").write("old")
json.dump([{"file": os.path.join(tts, "seg_00.mp3"), "text": "</div><script>alert(1)</script>"}],
          open(os.path.join(tts, "tts-manifest.json"), "w"))
timeline = [{"type": "hold_narrate", "source_time": 1.0, "hold_duration": 2.0, "segments": ["seg_00"],
             "description": "<img src=x onerror=alert(2)>"}]
placement = [{"file": os.path.join(tts, "seg_00.mp3"), "output_time": 0.3, "duration": 1.0}]
page = open(pt.generate_html(timeline, placement, ["frames/hold_00.jpg"], tts, out)).read()
check("a description with markup is escaped in the page", "<img src=x" not in page and "&lt;img src=x" in page)
check("narration text with markup is escaped in the page", "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page)
check("the page posts feedback to a relative URL (under the token)", "fetch('feedback'" in page)
copy = os.path.join(out, "tts", "seg_00.mp3")
check("the mp3 is copied into the preview", open(copy).read() == "old")
time.sleep(0.05)
open(os.path.join(tts, "seg_00.mp3"), "w").write("new")
t = time.time() + 5
os.utime(os.path.join(tts, "seg_00.mp3"), (t, t))
pt.generate_html(timeline, placement, ["frames/hold_00.jpg"], tts, out)
check("a regenerated (newer) mp3 replaces the old copy", open(copy).read() == "new", open(copy).read())
print("\n".join(results))
PYEND
res="$(cd "$PV" && PYTHONPATH="$TMP/fakecv" python3 "$TMP/pv-harness.py" "$REC/preview-timeline.py" "$TMP/pv-work" 2>&1)" || true
n=0
while IFS= read -r line; do
  case "$line" in
    "PASS "*) ok "preview server: ${line#PASS }"; n=$((n + 1)) ;;
    "FAIL "*) bad "preview server: ${line#FAIL }"; n=$((n + 1)) ;;
  esac
done <<< "$res"
[[ "$n" -ge 20 ]] && ok "preview server: the harness ran all $n checks" || bad "preview server: the harness ran all checks" "ran $n; output: $(printf '%s' "$res" | tail -5)"

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
run_in "$PROJ" "$PRO/scaffold-project.sh" "$TMP/work/ctrl" --skip-install --name "$(printf 'a\tb\001c')"
check "a tab and a control character in --name: exits 0" 0
file_json_is "a tab and a control character in --name still give valid JSON, with the name intact" "$TMP/work/ctrl/package.json" 'd["name"] == "a\tb\x01c"'
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
# A rerun after a failed install finishes the install (the files exist from the first run).
rm -f "$TMP/npm-ok-log"
run_in "$PROJ" env PATH="$TMP/npm-ok:$PATH" "$PRO/scaffold-project.sh" "$TMP/work/npm-fails"
check "a rerun after a failed npm install exits 0" 0 'already exists'
[[ "$(cat "$TMP/npm-ok-log" 2>/dev/null)" == "$TMP/work/npm-fails: npm install" ]] && ok "a rerun after a failed npm install runs npm install in the project" || bad "a rerun after a failed npm install runs npm install in the project" "log: $(cat "$TMP/npm-ok-log" 2>/dev/null)"
rm -f "$TMP/npm-ok-log"
run_in "$PROJ" env PATH="$TMP/npm-ok:$PATH" "$PRO/scaffold-project.sh" "$TMP/work/npm-fails" --skip-install
check "a rerun with --skip-install exits 0" 0 'already exists'
[[ ! -e "$TMP/npm-ok-log" ]] && ok "a rerun with --skip-install runs no npm install" || bad "a rerun with --skip-install runs no npm install" "log: $(cat "$TMP/npm-ok-log")"
run_in "$PROJ" env PATH="$TMP/npm-fail:$PATH" "$PRO/scaffold-project.sh" "$TMP/work/npm-fails"
check "a rerun whose npm install fails again exits 1" 1 "" 'npm install failed'
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
run_in "$PROJ" "$PRO/generate-voiceover.sh" --speed 'fast' n.json out
check "a --speed that is not a number exits 2 with a message" 2 "" '--speed must be a number'

# The OpenAI path runs a JavaScript program that imports "openai". A fake openai package in
# the project's node_modules stands in for the real one: it logs each request and writes no
# network traffic. The program must find it from the project directory (an ESM file in /tmp
# could not), and every value must reach it as data, so quotes cannot break it.
echo "generate-voiceover.sh: the OpenAI program (fake openai package, needs node)"
if command -v node >/dev/null 2>&1; then
  GV="$TMP/gv proj"
  mkdir -p "$GV/node_modules/openai"
  printf '{"name":"openai","version":"0.0.0","main":"index.js"}\n' > "$GV/node_modules/openai/package.json"
  cat > "$GV/node_modules/openai/index.js" <<'JSEND'
const fs = require("fs");
class OpenAI {
  constructor() {
    this.audio = { speech: { create: async (req) => {
      fs.appendFileSync(process.env.FAKE_OPENAI_LOG, JSON.stringify(req) + "\n");
      if (process.env.FAKE_OPENAI_FAIL) throw new Error("fake API failure");
      return { arrayBuffer: async () => new TextEncoder().encode("fake mp3").buffer };
    } } };
  }
}
module.exports = OpenAI;
module.exports.default = OpenAI;
JSEND
  cat > "$GV/n.json" <<'JSEND'
[{"scene": "hook", "text": "It's \"here\"."},
 {"scene": "../up", "text": "Second.", "instructions": "Per-scene ${x} `y`"}]
JSEND
  INSTR='Say "hi" \ and $(touch pwned) '"'"'now'"'"
  run_in "$GV" env OPENAI_API_KEY=dummy FAKE_OPENAI_LOG="$TMP/openai-log" "$PRO/generate-voiceover.sh" \
    --provider openai --voice ash --speed 1.1 --instructions "$INSTR" n.json "out dir"
  check "openai: runs from the project dir and finds its openai package, exit 0" 0 'Generated 2 audio files'
  [[ -f "$GV/out dir/01-hook.mp3" ]] && ok "openai: wrote 01-hook.mp3" || bad "openai: wrote 01-hook.mp3" "missing; stderr: $(printf '%s' "$ERR" | head -3)"
  [[ -f "$GV/out dir/02----up.mp3" && ! -e "$GV/up.mp3" ]] && ok "openai: a scene name with ../ stays inside the output dir (02----up.mp3)" || bad "openai: a scene name with ../ stays inside the output dir" "$(ls "$GV/out dir" 2>&1)"
  [[ ! -e "$GV/pwned" ]] && ok "openai: \$(...) in --instructions is not run" || bad "openai: \$(...) in --instructions is not run" "pwned exists"
  if res="$(INSTR="$INSTR" python3 -c 'import json,os,sys
reqs = [json.loads(l) for l in open(sys.argv[1])]
want = os.environ["INSTR"]
ok = (len(reqs) == 2 and reqs[0]["instructions"] == want and reqs[1]["instructions"] == "Per-scene ${x} `y`"
      and reqs[0]["input"] == "It'"'"'s \"here\"." and reqs[0]["voice"] == "ash" and reqs[0]["speed"] == 1.1)
print("yes" if ok else reqs)' "$TMP/openai-log" 2>&1)" && [[ "$res" == yes ]]; then
    ok "openai: text, quotes, voice, speed and both kinds of instructions reach the API unchanged"
  else
    bad "openai: text, quotes, voice, speed and both kinds of instructions reach the API unchanged" "$res"
  fi
  run_in "$GV" env OPENAI_API_KEY=dummy FAKE_OPENAI_LOG="$TMP/openai-log" FAKE_OPENAI_FAIL=1 "$PRO/generate-voiceover.sh" \
    --provider openai n.json "out2"
  check "openai: an API failure exits 1 and names the scene" 1 "" '01-hook failed after 0 of 2'
  printf '{"scene": "hook", "text": "not a list"}' > "$GV/obj.json"
  run_in "$GV" env OPENAI_API_KEY=dummy FAKE_OPENAI_LOG="$TMP/openai-log" "$PRO/generate-voiceover.sh" --provider openai obj.json out3
  check "openai: a script file that is not a JSON array exits 1 with a message" 1 "" 'non-empty JSON array'
else
  skip "generate-voiceover.sh OpenAI program: node is not installed"
fi

# The macOS path runs `say` and `ffmpeg`. Stubs stand in for both: `say -v ?` lists two
# voices, and a call that makes audio copies the text file it was given.
echo "generate-voiceover.sh: the macOS path (stub say and ffmpeg, needs node)"
if command -v node >/dev/null 2>&1; then
  mkdir -p "$TMP/macos-stubs"
  cat > "$TMP/macos-stubs/say" <<'SHEND'
#!/bin/sh
if [ "$1" = "-v" ] && [ "$2" = "?" ]; then
  printf 'Samantha            en_US    # Hello! My name is Samantha.\n'
  printf 'Eddy (English (US)) en_US    # Hello! My name is Eddy.\n'
  exit 0
fi
out=""; in=""; text=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -f) in="$2"; shift 2 ;;
    -v) shift 2 ;;
    *) text="$1"; shift ;;
  esac
done
if [ -n "$in" ]; then cat "$in" >> "$SAY_LOG"; cp "$in" "$out"; else printf '%s' "$text" >> "$SAY_LOG"; printf '%s' "$text" > "$out"; fi
echo >> "$SAY_LOG"
SHEND
  cat > "$TMP/macos-stubs/ffmpeg" <<'SHEND'
#!/bin/sh
in=""; last=""
for a in "$@"; do last="$a"; done
while [ $# -gt 0 ]; do if [ "$1" = "-i" ]; then in="$2"; fi; shift; done
cp "$in" "$last"
SHEND
  chmod +x "$TMP/macos-stubs/say" "$TMP/macos-stubs/ffmpeg"
  MAC="$TMP/mac proj"
  mkdir -p "$MAC"
  printf '[{"scene":"hook","text":"-n starts with a dash"},{"scene":"cta","text":"Try it."}]' > "$MAC/n.json"
  : > "$TMP/say-log"
  run_in "$MAC" env PATH="$TMP/macos-stubs:$TMP/stubs:$PATH" SAY_LOG="$TMP/say-log" "$PRO/generate-voiceover.sh" \
    --provider macos --voice 'Eddy (English (US))' n.json audio
  check "macos: a voice name with spaces and parentheses works, exit 0" 0 'Generated 2 audio files'
  [[ "$(cat "$MAC/audio/01-hook.mp3" 2>/dev/null)" == "-n starts with a dash" && -f "$MAC/audio/02-cta.mp3" ]] \
    && ok "macos: each scene's text is spoken as text, even when it starts with -" || bad "macos: each scene's text is spoken as text" "$(ls "$MAC/audio" 2>&1)"
  : > "$TMP/say-log"
  run_in "$MAC" env PATH="$TMP/macos-stubs:$TMP/stubs:$PATH" SAY_LOG="$TMP/say-log" "$PRO/generate-voiceover.sh" \
    --provider macos --voice Nobody n.json audio
  check "macos: an unknown --voice exits 2 with a message" 2 "" 'unknown macOS voice: Nobody'
  [[ ! -s "$TMP/say-log" ]] && ok "macos: an unknown voice makes no audio" || bad "macos: an unknown voice makes no audio" "$(cat "$TMP/say-log")"
  printf '[{"scene":"hook","text":"Hi."},{"scene":"cta"}]' > "$MAC/notext.json"
  run_in "$MAC" env PATH="$TMP/macos-stubs:$TMP/stubs:$PATH" SAY_LOG="$TMP/say-log" "$PRO/generate-voiceover.sh" \
    --provider macos notext.json audio2
  check "macos: a scene with no text exits 1 with a message" 1 "" 'scene 2 has no "text"'
  if grep -q undefined "$TMP/say-log" || [[ -s "$TMP/say-log" ]]; then
    bad "macos: a scene with no text speaks nothing (not \"undefined\")" "$(cat "$TMP/say-log")"
  else
    ok "macos: a scene with no text speaks nothing (not \"undefined\")"
  fi
  printf '{"not": "a list"}' > "$MAC/obj.json"
  run_in "$MAC" env PATH="$TMP/macos-stubs:$TMP/stubs:$PATH" SAY_LOG="$TMP/say-log" "$PRO/generate-voiceover.sh" \
    --provider macos obj.json audio3
  check "macos: a script file that is not a JSON array exits 1 (no success line)" 1 "" 'non-empty JSON array'
  case "$OUT" in *Generated*) bad "macos: a bad script file prints no success line" "$OUT" ;; *) ok "macos: a bad script file prints no success line" ;; esac
else
  skip "generate-voiceover.sh macOS path: node is not installed"
fi

echo "capture-screenshots.sh (produce)"
run_in "$PROJ" "$PRO/capture-screenshots.sh"
check "no output directory exits 2 with a message" 2 "" 'output directory is required'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --url
check "--url with no value exits 2 with a message" 2 "" 'Option --url needs a value'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --bogus out
check "an unknown option exits 2" 2 "" 'Unknown option: --bogus'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --flow-script x.mjs out
check "--flow-script is gone (it was never used): exit 2" 2 "" 'Unknown option: --flow-script'
run_in "$PROJ" "$PRO/capture-screenshots.sh" --viewport big out
check "a --viewport that is not WxH exits 2 with a message" 2 "" '--viewport must be WIDTHxHEIGHT'
skip "capture-screenshots.sh capture: needs Playwright, a browser and a running app"

# A fake playwright package in the project's node_modules stands in for the real one. Its
# browser logs each call and "screenshots" by writing the path. FAKE_PW_FAIL makes goto throw.
echo "capture-screenshots.sh: the capture program (fake playwright package, needs node)"
if command -v node >/dev/null 2>&1; then
  CS="$TMP/cs proj"
  mkdir -p "$CS/node_modules/playwright"
  printf '{"name":"playwright","version":"0.0.0","main":"index.js"}\n' > "$CS/node_modules/playwright/package.json"
  cat > "$CS/node_modules/playwright/index.js" <<'JSEND'
const fs = require("fs");
const log = (s) => fs.appendFileSync(process.env.FAKE_PW_LOG, s + "\n");
const page = {
  goto: async (url) => { log("goto " + url); if (process.env.FAKE_PW_FAIL) throw new Error("fake goto failure"); },
  waitForTimeout: async () => {},
  evaluate: async (fn, arg) => { if (arg !== undefined) log("hide " + arg); return { scrollHeight: 1, clientHeight: 1 }; },
  screenshot: async (o) => { fs.writeFileSync(o.path, "png"); log("shot " + o.path); },
};
exports.chromium = { launch: async () => ({
  newContext: async (o) => { log("ctx " + JSON.stringify(o)); return { newPage: async () => page }; },
  close: async () => log("close"),
}) };
JSEND
  : > "$TMP/pw-log"
  run_in "$CS" env FAKE_PW_LOG="$TMP/pw-log" "$PRO/capture-screenshots.sh" "shots dir" \
    --url 'http://localhost:5173/?q="x"&y=$(touch pwned)' --hide-selectors '.a,[data-x="1"]' --viewport 400x800 --dpr 3
  check "capture: runs from the project dir and finds its playwright package, exit 0" 0 'Done! Screenshots saved'
  [[ -f "$CS/shots dir/hero.png" ]] && ok "capture: wrote hero.png" || bad "capture: wrote hero.png" "stderr: $(printf '%s' "$ERR" | head -3)"
  grep -Fxq 'goto http://localhost:5173/?q="x"&y=$(touch pwned)' "$TMP/pw-log" && ok "capture: a URL with quotes and \$(...) reaches the browser unchanged" || bad "capture: a URL with quotes reaches the browser unchanged" "$(cat "$TMP/pw-log")"
  grep -Fxq 'hide .a,[data-x="1"]' "$TMP/pw-log" && ok "capture: selectors with quotes reach the page unchanged" || bad "capture: selectors with quotes reach the page unchanged" "$(cat "$TMP/pw-log")"
  grep -Fq '"viewport":{"width":400,"height":800},"deviceScaleFactor":3' "$TMP/pw-log" && ok "capture: --viewport and --dpr set the browser context" || bad "capture: --viewport and --dpr set the browser context" "$(grep ctx "$TMP/pw-log")"
  [[ ! -e "$CS/pwned" ]] && ok "capture: \$(...) in --url is not run" || bad "capture: \$(...) in --url is not run" "pwned exists"
  : > "$TMP/pw-log"
  run_in "$CS" env FAKE_PW_LOG="$TMP/pw-log" FAKE_PW_FAIL=1 "$PRO/capture-screenshots.sh" "shots2"
  check "capture: a failure in the browser exits 1 with a message" 1 "" 'screenshot capture failed: fake goto failure'
  [[ "$(tail -1 "$TMP/pw-log")" == close ]] && ok "capture: the browser is closed after a failure" || bad "capture: the browser is closed after a failure" "$(cat "$TMP/pw-log")"
else
  skip "capture-screenshots.sh capture program: node is not installed"
fi

echo "render-and-preview.sh (produce)"
run_in "$PROJ" "$PRO/render-and-preview.sh" --output
check "--output with no value exits 2 with a message" 2 "" 'Option --output needs a value'
run_in "$PROJ" "$PRO/render-and-preview.sh" --bogus
check "an unknown option exits 2" 2 "" 'Unknown option: --bogus'
run_in "$PROJ" "$PRO/render-and-preview.sh" --no-open
check "no src/Root.tsx and no composition id exits 1 with a message, before lint" 1 "" 'Could not auto-detect composition ID'
skip "render-and-preview.sh render: needs a Remotion project, npm install and ffmpeg"

# A fake Remotion project: Root.tsx, and node_modules/.bin/eslint and tsc that exit with
# $FAKE_ESLINT_RC and $FAKE_TSC_RC. Fake npx (remotion render writes the output), ffprobe
# (prints nothing) and ffmpeg (exits $FAKE_FFMPEG_RC) come first on PATH.
RP="$TMP/rp proj"
mkdir -p "$RP/src" "$RP/node_modules/.bin" "$TMP/rp-bin"
printf '#!/bin/sh\necho "eslint ran"\nexit "${FAKE_ESLINT_RC:-0}"\n' > "$RP/node_modules/.bin/eslint"
printf '#!/bin/sh\nexit "${FAKE_TSC_RC:-0}"\n' > "$RP/node_modules/.bin/tsc"
printf '#!/bin/sh\necho "npx $*" >> "$RP_LOG"\n[ "$1" = remotion ] && [ "$2" = render ] && : > "$4"\nexit 0\n' > "$TMP/rp-bin/npx"
printf '#!/bin/sh\nexit 0\n' > "$TMP/rp-bin/ffprobe"
printf '#!/bin/sh\necho "ffmpeg: boom" >&2\nexit "${FAKE_FFMPEG_RC:-0}"\n' > "$TMP/rp-bin/ffmpeg"
chmod +x "$RP/node_modules/.bin/eslint" "$RP/node_modules/.bin/tsc" "$TMP/rp-bin/npx" "$TMP/rp-bin/ffprobe" "$TMP/rp-bin/ffmpeg"
RPENV="PATH=$TMP/rp-bin:$TMP/stubs:$PATH"
printf '<Composition id="Main" />\n<Composition id="Teaser" />\n' > "$RP/src/Root.tsx"
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" "$PRO/render-and-preview.sh" --no-open
check "two compositions and no id exits 1 and names both" 1 "" 'has 2 compositions: Main Teaser'
printf '<Composition id="Main" />\n' > "$RP/src/Root.tsx"
: > "$TMP/rp-log"
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" "$PRO/render-and-preview.sh" --no-open
check "one composition is auto-detected and rendered, exit 0" 0 'Auto-detected composition: Main'
grep -Fq 'npx remotion render Main out/video.mp4' "$TMP/rp-log" && ok "the render runs for the detected id" || bad "the render runs for the detected id" "$(cat "$TMP/rp-log")"
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" FAKE_ESLINT_RC=1 "$PRO/render-and-preview.sh" --no-open
check "eslint exit 1 is reported as lint errors" 1 "" 'ESLint errors found'
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" FAKE_ESLINT_RC=2 "$PRO/render-and-preview.sh" --no-open
check "eslint exit 2 is reported as eslint not able to run" 1 "" 'ESLint could not run \(exit 2\)'
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" FAKE_TSC_RC=2 "$PRO/render-and-preview.sh" --no-open
check "tsc errors are reported as TypeScript errors" 1 "" 'TypeScript errors found'
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" FAKE_FFMPEG_RC=1 "$PRO/render-and-preview.sh" --no-open --contact-sheet
check "a failed contact sheet exits 1 with a message and the ffmpeg output" 1 "" 'contact sheet failed'
case "$ERR" in *"ffmpeg: boom"*) ok "a failed contact sheet shows the ffmpeg output" ;; *) bad "a failed contact sheet shows the ffmpeg output" "$ERR" ;; esac
mv "$RP/node_modules" "$RP/node_modules.off"
run_in "$RP" env "$RPENV" RP_LOG="$TMP/rp-log" "$PRO/render-and-preview.sh" --no-open
check "no eslint in the project is reported as not installed, not as lint errors" 1 "" 'eslint is not installed in this project'
mv "$RP/node_modules.off" "$RP/node_modules"

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
