#!/usr/bin/env bash
set -euo pipefail

# test-ci-skill-detect.sh — tests for the changed-skill and changed-plugin steps
# of the validate-skills and validate-plugins jobs (#167).
#
# The steps are `run:` blocks inside a workflow file. This test pulls each step
# out of the YAML text, with its `env:` mapping, and runs it in a fixture git
# repo. `${{ steps.changed.outputs.X }}` is resolved from the GITHUB_OUTPUT file
# the detect step wrote, the way Actions does it, so a validate step that loses
# its `env:` binding sees an empty variable here too. It checks both workflows:
#   .github/workflows/validate-skill.yml   this repo; plugin skills only
#   plugins/skill-kit/.../workflow-monorepo.yml
#                                          the template skill-kit:publish installs
#                                          into other monorepos; plugin skills AND
#                                          top-level <name>/ skills

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PYTHONDONTWRITEBYTECODE=1

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$(printf '%s' "$2" | tail -n 12)"; return 0; }
check() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "expected [$2] got [$3]"; fi; }

# render_step <workflow> <step name> <GITHUB_OUTPUT file or ""> <out script>
# Writes a bash script: `export` lines for the step's env: mapping, then its
# `run: |` body, with ${{ steps.changed.outputs.X }} replaced by the value in the
# output file (empty when absent, as in Actions). Exits 2 with a message when the
# step, or its `run: |` block, is not found.
render_step() {
  python3 - "$@" <<'PY'
import re, sys, shlex
wf, name, ghout, out = sys.argv[1:5]
lines = open(wf).read().split("\n")
def die(msg):
    sys.stderr.write("render_step: %s: %s\n" % (wf, msg)); sys.exit(2)
starts = [n for n, l in enumerate(lines) if l.strip() == "- name: " + name]
if len(starts) != 1:
    die("expected one step named %r, found %d" % (name, len(starts)))
i = starts[0]
ind = len(lines[i]) - len(lines[i].lstrip())
end = len(lines)
for n in range(i + 1, len(lines)):
    l = lines[n]
    if l.strip() and len(l) - len(l.lstrip()) <= ind:
        end = n; break
block = lines[i:end]
outputs = {}
if ghout:
    g = open(ghout).read().split("\n"); k = 0
    while k < len(g):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)<<(.+)$", g[k])
        if m:
            key, delim, vals = m.group(1), m.group(2), []
            k += 1
            while k < len(g) and g[k] != delim:
                vals.append(g[k]); k += 1
            outputs[key] = "\n".join(vals)
        elif "=" in g[k]:
            key, v = g[k].split("=", 1); outputs[key] = v
        k += 1
def resolve(text):
    def sub(m):
        return outputs.get(m.group(1), "")
    text = re.sub(r"\$\{\{\s*steps\.changed\.outputs\.([A-Za-z0-9_-]+)\s*\}\}", sub, text)
    if "${{" in text:
        die("unresolved expression in step %r: %s" % (name, text))
    return text
env = []
run_at = None
for n, l in enumerate(block):
    s = l.strip()
    if s == "env:":
        base = len(l) - len(l.lstrip())
        for e in block[n + 1:]:
            if e.strip() and len(e) - len(e.lstrip()) <= base:
                break
            if e.strip():
                k, v = e.strip().split(":", 1)
                env.append((k.strip(), v.strip()))
    if s.startswith("run:"):
        if s != "run: |":
            die("step %r has %r; only a literal `run: |` block is supported" % (name, s))
        run_at = n
if run_at is None:
    die("step %r has no `run: |` block" % name)
base = len(block[run_at]) - len(block[run_at].lstrip()) + 2
body = []
for l in block[run_at + 1:]:
    if l.strip() and len(l) - len(l.lstrip()) < base:
        break
    body.append(l[base:])
with open(out, "w") as f:
    for k, v in env:
        f.write("export %s=%s\n" % (k, shlex.quote(resolve(v))))
    f.write(resolve("\n".join(body)) + "\n")
PY
}

# step_env <workflow> <step name> <var>: the raw YAML value of that env entry.
step_env() {
  python3 - "$@" <<'PY'
import sys
wf, name, var = sys.argv[1:4]
lines = open(wf).read().split("\n")
i = next((n for n, l in enumerate(lines) if l.strip() == "- name: " + name), None)
if i is None:
    sys.exit(0)
ind = len(lines[i]) - len(lines[i].lstrip())
for l in lines[i + 1:]:
    if l.strip() and len(l) - len(l.lstrip()) <= ind:
        break
    if l.strip().startswith(var + ":"):
        print(l.strip().split(":", 1)[1].strip()); break
PY
}

# new_repo <dir>: a git repo whose origin/main has
#   old/            top-level skill, changed in HEAD
#   oldgone/        top-level skill, removed in HEAD
#   docs/           a top-level directory that is not a skill, changed in HEAD
#   plugins/pg/     plugin with skills gone (removed), kept (changed twice), and
#                   nomd (gains a file but has no SKILL.md); its README and a file
#                   directly under skills/ change too, and neither is a skill dir
#   plugins/oldplug/  a plugin removed in HEAD
new_repo() {
  local r="$1"
  mkdir -p "$r"
  (
    cd "$r"
    git init -q . && git config user.email t@t && git config user.name t && git config commit.gpgsign false
    mkdir -p old oldgone docs plugins/pg/skills/gone plugins/pg/skills/kept plugins/pg/skills/nomd plugins/oldplug scripts
    echo x > old/SKILL.md; echo x > oldgone/SKILL.md; echo x > docs/notes.md
    echo x > plugins/pg/skills/gone/SKILL.md; echo x > plugins/pg/skills/kept/SKILL.md
    echo x > plugins/pg/README.md; echo x > plugins/pg/skills/README.md; echo x > plugins/oldplug/README.md
    printf '#!/usr/bin/env bash\necho "validated $1"\n' > scripts/validate-skill.sh
    printf '#!/usr/bin/env bash\necho "validated plugin $1"\n' > scripts/validate-plugin.sh
    chmod +x scripts/*.sh
    git add -A && git commit -q -m base
    git update-ref refs/remotes/origin/main HEAD
    git checkout -q -b change
    echo y >> old/SKILL.md
    git rm -q -r oldgone
    echo y >> docs/notes.md
    echo y >> plugins/pg/README.md
    echo y >> plugins/pg/skills/README.md
    echo y >> plugins/pg/skills/kept/SKILL.md
    mkdir -p plugins/pg/skills/kept/scripts && echo y > plugins/pg/skills/kept/scripts/run.sh
    git rm -q -r plugins/pg/skills/gone
    echo y > plugins/pg/skills/nomd/notes.txt
    git rm -q -r plugins/oldplug
    git add -A && git commit -q -m change
  )
}

# run_in <repo> <script> <GITHUB_OUTPUT file>: sets OUT and RC. bash -e, as Actions runs `run:`.
run_in() { OUT="$(cd "$1" && GITHUB_OUTPUT="$3" bash -e "$2" 2>&1)" && RC=0 || RC=$?; }

PLUGIN_SKILLS="$(printf '%s\n' plugins/pg/skills/gone plugins/pg/skills/kept plugins/pg/skills/nomd)"

for WF in "$REPO_ROOT/.github/workflows/validate-skill.yml" "$REPO_ROOT/plugins/skill-kit/skills/publish/references/workflow-monorepo.yml"; do
  LABEL="${WF#"$REPO_ROOT"/}"
  echo "$LABEL"
  case "$LABEL" in
    .github/*) TOP=false; EXPECT="$PLUGIN_SKILLS" ;;
    *)         TOP=true;  EXPECT="$(printf '%s\n%s\n%s\n' old oldgone "$PLUGIN_SKILLS")" ;;
  esac
  W="$TMP/$(printf '%s' "$LABEL" | tr '/.' '__')"; mkdir -p "$W"
  new_repo "$W/repo"

  # --- env bindings, read from the YAML (a validate step without one sees nothing) ---
  check "the validate-skills step binds DIRS to the detect step's output" \
    '${{ steps.changed.outputs.dirs }}' "$(step_env "$WF" "Validate changed skills" DIRS)"
  check "the validate-plugins step binds PLUGINS to the detect step's output" \
    '${{ steps.changed.outputs.plugins }}' "$(step_env "$WF" "Validate changed plugins" PLUGINS)"

  # --- skills: detect ---
  render_step "$WF" "Detect changed skill directories" "" "$W/detect.sh"
  : > "$W/gh_out"
  run_in "$W/repo" "$W/detect.sh" "$W/gh_out"
  check "detect step exits 0" 0 "$RC"
  DIRS="$(sed -n '/^dirs<<EOF$/,/^EOF$/p' "$W/gh_out" | sed '1d;$d')"
  if $TOP; then
    check "detect lists the plugin skill dirs and the top-level skill dirs (old, removed oldgone), each once" "$EXPECT" "$DIRS"
  else
    check "detect lists the three changed plugin skill dirs once each, and no top-level dir" "$EXPECT" "$DIRS"
  fi
  [[ "$DIRS" != *docs* ]] && ok "a top-level dir with no SKILL.md (docs/) is not a skill dir" || bad "a top-level dir with no SKILL.md (docs/) is not a skill dir" "$DIRS"
  [[ "$DIRS" != *README* ]] && ok "plugins/pg/README.md and plugins/pg/skills/README.md are not skill dirs" || bad "plugins/pg/README.md and plugins/pg/skills/README.md are not skill dirs" "$DIRS"

  # --- skills: validate, with DIRS coming from the env binding ---
  render_step "$WF" "Validate changed skills" "$W/gh_out" "$W/validate.sh"
  run_in "$W/repo" "$W/validate.sh" /dev/null
  check "validate step fails when a changed skill dir has no SKILL.md" 1 "$RC"
  [[ "$OUT" == *"plugins/pg/skills/nomd"*"no SKILL.md"* ]] && ok "the error names the dir" || bad "the error names the dir" "$OUT"
  [[ "$OUT" == *"validated plugins/pg/skills/kept"* ]] && ok "an existing plugin skill is validated" || bad "an existing plugin skill is validated" "$OUT"
  [[ "$OUT" == *"Skipping plugins/pg/skills/gone: removed"* ]] && ok "a removed plugin skill dir is skipped with a note" || bad "a removed plugin skill dir is skipped with a note" "$OUT"
  if $TOP; then
    [[ "$OUT" == *"validated old"* ]] && ok "a top-level skill is validated" || bad "a top-level skill is validated" "$OUT"
    [[ "$OUT" == *"Skipping oldgone: removed"* ]] && ok "a removed top-level skill is skipped with a note" || bad "a removed top-level skill is skipped with a note" "$OUT"
  fi

  # Removed plus valid only: passes.
  printf 'dirs<<EOF\nplugins/pg/skills/gone\nplugins/pg/skills/kept\nEOF\n' > "$W/gh_out_ok"
  render_step "$WF" "Validate changed skills" "$W/gh_out_ok" "$W/validate_ok.sh"
  run_in "$W/repo" "$W/validate_ok.sh" /dev/null
  check "removed plus valid skills: validate step passes" 0 "$RC"

  # --- skills: only a top-level skill changed ---
  new_repo "$W/repo2"
  (cd "$W/repo2" && git reset -q --hard origin/main && echo z >> old/SKILL.md && git commit -q -am top)
  : > "$W/gh_out2"
  run_in "$W/repo2" "$W/detect.sh" "$W/gh_out2"
  if $TOP; then
    check "the template: a change to a top-level skill is a skill change" "$(printf 'dirs<<EOF\nold\nEOF')" "$(cat "$W/gh_out2")"
  else
    check "this repo: a change to a top-level dir is not a skill change" "dirs=" "$(cat "$W/gh_out2")"
  fi

  # --- skills: no origin/main → the step fails, it does not report "no changes" ---
  new_repo "$W/repo3"
  git -C "$W/repo3" update-ref -d refs/remotes/origin/main
  : > "$W/gh_out3"
  run_in "$W/repo3" "$W/detect.sh" "$W/gh_out3"
  [[ $RC -ne 0 ]] && ok "detect skills fails when git diff fails (no origin/main)" || bad "detect skills fails when git diff fails (no origin/main)" "rc=$RC $OUT"
  [[ "$OUT" == *"git diff origin/main...HEAD failed"* ]] && ok "…and says the diff failed" || bad "…and says the diff failed" "$OUT"
  [[ "$OUT" != *"No skill directories changed"* ]] && ok "…and does not say no skill changed" || bad "…and does not say no skill changed" "$OUT"
  check "…and writes no output" "" "$(cat "$W/gh_out3")"

  # --- plugins: detect and validate ---
  render_step "$WF" "Detect changed plugin directories" "" "$W/pdetect.sh"
  : > "$W/pgh_out"
  run_in "$W/repo" "$W/pdetect.sh" "$W/pgh_out"
  check "detect plugins exits 0" 0 "$RC"
  check "detect plugins lists oldplug and pg once each" "$(printf 'oldplug\npg')" \
    "$(sed -n '/^plugins<<EOF$/,/^EOF$/p' "$W/pgh_out" | sed '1d;$d')"
  render_step "$WF" "Validate changed plugins" "$W/pgh_out" "$W/pvalidate.sh"
  run_in "$W/repo" "$W/pvalidate.sh" /dev/null
  check "validate plugins passes" 0 "$RC"
  [[ "$OUT" == *"validated plugin plugins/pg"* ]] && ok "an existing plugin is validated" || bad "an existing plugin is validated" "$OUT"
  [[ "$OUT" == *"Skipping plugins/oldplug: removed in this PR"* ]] && ok "a removed plugin dir is skipped with a note" || bad "a removed plugin dir is skipped with a note" "$OUT"
  : > "$W/pgh_out3"
  run_in "$W/repo3" "$W/pdetect.sh" "$W/pgh_out3"
  [[ $RC -ne 0 && "$OUT" == *"git diff origin/main...HEAD failed"* ]] && ok "detect plugins fails when git diff fails (no origin/main)" || bad "detect plugins fails when git diff fails (no origin/main)" "rc=$RC $OUT"
done

# render_step must say what is missing, not print a traceback.
echo "render_step on a missing step"
render_step "$REPO_ROOT/.github/workflows/validate-skill.yml" "No such step" "" "$TMP/none.sh" 2>"$TMP/none.err" && RC=0 || RC=$?
check "a missing step exits 2" 2 "$RC"
grep -q "expected one step named 'No such step', found 0" "$TMP/none.err" && ok "…with a message" || bad "…with a message" "$(cat "$TMP/none.err")"
grep -q Traceback "$TMP/none.err" && bad "…and no traceback" "$(cat "$TMP/none.err")" || ok "…and no traceback"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
