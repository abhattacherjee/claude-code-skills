#!/usr/bin/env bash
set -euo pipefail

# test-check-skill-commands.sh — tests for scripts/check-skill-commands.py.
#
# Each case builds a small fixture plugin in a temp dir, runs the checker on it
# and asserts the exit code and, for failures, the `file:line: message` text.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKER="${CHECKER:-$REPO_ROOT/scripts/check-skill-commands.py}"
export PYTHONDONTWRITEBYTECODE=1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [[ -n "${2:-}" ]] && printf '        %s\n' "$2"; return 0; }

# new_plugin <name>: a clean plugin with one skill "s", one script and one reference.
# Prints the plugin dir. Callers then overwrite SKILL.md or add files.
new_plugin() {
  local d="$TMP/$1"
  mkdir -p "$d/skills/s/scripts" "$d/skills/s/references"
  printf '#!/usr/bin/env bash\necho hi\n' > "$d/skills/s/scripts/run.sh"
  chmod +x "$d/skills/s/scripts/run.sh"
  printf '# ref\n' > "$d/skills/s/references/r.md"
  cat > "$d/skills/s/SKILL.md" <<'EOF'
---
name: s
description: "x"
---

# S

```bash
"${CLAUDE_SKILL_DIR}/scripts/run.sh" --flag
```
EOF
  printf '%s' "$d"
}

# expect <label> <want-exit> <want-output-regex-or-empty> <args...>
expect() {
  local label="$1" want="$2" re="$3"
  shift 3
  local out rc=0
  out="$(python3 "$CHECKER" "$@" 2>&1)" || rc=$?
  if [[ "$rc" != "$want" ]]; then
    bad "$label" "exit $rc, want $want. Output: $(printf '%s' "$out" | head -3)"
    return 0
  fi
  if [[ -n "$re" ]] && ! printf '%s' "$out" | grep -Eq -- "$re"; then
    bad "$label" "exit ok but output lacks /$re/. Output: $(printf '%s' "$out" | head -3)"
    return 0
  fi
  ok "$label"
}

echo "check-skill-commands.py"

# --- clean ---
P="$(new_plugin clean)"
expect "clean plugin exits 0" 0 '^OK: ' "$P"

# --- bare relative script ---
P="$(new_plugin relative)"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

```bash
./scripts/run.sh --flag
```
EOF
expect "relative ./scripts command exits 1 with file:line" 1 'relative/skills/s/SKILL.md:4: script `\./scripts/run\.sh`' "$P"

# --- cross-block variable ---
P="$(new_plugin crossvar)"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

```bash
SPEC_FILE=docs/a.md
```

```bash
"${CLAUDE_SKILL_DIR}/scripts/run.sh" "$SPEC_FILE"
```
EOF
expect "variable set in an earlier block exits 1" 1 'SKILL.md:8: reads \$SPEC_FILE' "$P"

# --- missing SKILL_DIR target ---
P="$(new_plugin missing)"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

```bash
"${CLAUDE_SKILL_DIR}/scripts/nope.sh"
```
EOF
expect "missing \${CLAUDE_SKILL_DIR} target exits 1" 1 'SKILL.md:4: \$\{CLAUDE_SKILL_DIR\}/scripts/nope\.sh does not exist' "$P"

# --- missing PLUGIN_ROOT target, and resolving against the plugin dir ---
P="$(new_plugin pluginroot)"
mkdir -p "$P/skills/other/scripts"
printf '#!/usr/bin/env bash\n' > "$P/skills/other/scripts/o.sh"
chmod +x "$P/skills/other/scripts/o.sh"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/other/scripts/o.sh"
```
EOF
cp "$P/skills/s/SKILL.md" "$P/skills/other/SKILL.md"
expect "\${CLAUDE_PLUGIN_ROOT} path that exists exits 0" 0 '^OK: ' "$P"
rm "$P/skills/other/scripts/o.sh"
expect "missing \${CLAUDE_PLUGIN_ROOT} target exits 1" 1 'does not exist' "$P"

# --- non-executable command target ---
P="$(new_plugin noexec)"
chmod -x "$P/skills/s/scripts/run.sh"
expect "non-executable first-word target exits 1" 1 'SKILL.md:9: .*not executable' "$P"

# A target that is only an argument (bash x.sh) needs no exec bit.
P="$(new_plugin bashargs)"
chmod -x "$P/skills/s/scripts/run.sh"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run.sh"
```
EOF
expect "non-executable target run through bash exits 0" 0 '^OK: ' "$P"

# --- inline spans ---
P="$(new_plugin span)"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

Run `./scripts/run.sh --flag` first.
EOF
expect "bad inline command span exits 1" 1 'SKILL.md:3: `\./scripts/run\.sh --flag`' "$P"

P="$(new_plugin spanexec)"
chmod -x "$P/skills/s/scripts/run.sh"
cat > "$P/skills/s/SKILL.md" <<'EOF'
# S

Run `"${CLAUDE_SKILL_DIR}/scripts/run.sh" --flag` first.
EOF
expect "non-executable target in an inline span exits 1" 1 'SKILL.md:3: .*not executable' "$P"

# --- unlabeled fence: a diagram is fine, a relative script command is not ---
P="$(new_plugin plainfence)"
printf '# S\n\n```\ndetect-mode.sh\n  |-- r1.json\n```\n' > "$P/skills/s/SKILL.md"
expect "unlabeled fence holding a diagram exits 0" 0 '^OK: ' "$P"
printf '# S\n\n```\n./scripts/run.sh --flag\n```\n' > "$P/skills/s/SKILL.md"
expect "unlabeled fence starting with a relative script exits 1" 1 'SKILL.md:4: script `\./scripts/run\.sh` has no .* \(in a unlabeled fence\)' "$P"

# --- an unreadable file is a reported problem (exit 1), not a traceback ---
P="$(new_plugin badbytes)"
printf '# S\n\xff\xfe not utf-8\n' > "$P/skills/s/SKILL.md"
expect "non-UTF-8 SKILL.md exits 1 with a cannot-read line" 1 'SKILL.md:1: cannot read file' "$P"
P="$(new_plugin badref)"
printf '\xff\xfe\n' > "$P/skills/s/references/r.md"
expect "non-UTF-8 reference exits 1 with a cannot-read line" 1 'references/r.md:1: cannot read file' "$P"
out="$(python3 "$CHECKER" "$P" 2>&1 || true)"
if printf '%s' "$out" | grep -q Traceback; then bad "no traceback on unreadable file" "$out"; else ok "no traceback on unreadable file"; fi

# --- new rules (PR #173 fix wave 1) ---
# A reference holds no ${CLAUDE_...} at all.
P="$(new_plugin refenv)"
printf '# ref\n\n```bash\n"${CLAUDE_SKILL_DIR}/scripts/run.sh"\n```\n' > "$P/skills/s/references/r.md"
expect "any \${CLAUDE_ in a references file exits 1" 1 'references/r.md:4: \$\{CLAUDE_\.\.\.\} in a references file is never substituted' "$P"

# <SCRIPTS_DIR>: defined only by a definition line, and the name must exist there.
P="$(new_plugin sdname)"
printf '# ref\n\n```bash\n<SCRIPTS_DIR>/nope.sh\n```\n' > "$P/skills/s/references/r.md"
printf '\nIn the references, <SCRIPTS_DIR> means "${CLAUDE_SKILL_DIR}/scripts".\n' >> "$P/skills/s/SKILL.md"
expect "<SCRIPTS_DIR>/name that is not in the defined dir exits 1" 1 'references/r.md:4: <SCRIPTS_DIR>/nope\.sh does not exist' "$P"
P="$(new_plugin sdself)"
printf '# ref\n\n```bash\n<SCRIPTS_DIR>/run.sh\n```\n' > "$P/skills/s/references/r.md"
printf '\nRun `<SCRIPTS_DIR>/run.sh` to start (the scripts live in ${CLAUDE_SKILL_DIR}/scripts).\n' >> "$P/skills/s/SKILL.md"
expect "<SCRIPTS_DIR> used in SKILL.md but never defined exits 1" 1 'no definition line for <SCRIPTS_DIR>' "$P"

# Fences that are not bash: ~~~, console with a $ prompt, unlabeled, text.
fence_case() { # <label> <want-exit> <regex> <fence-open> <line...>
  local label="$1" want="$2" re="$3" open="$4" close; shift 4
  local d; d="$(new_plugin "fc-$RANDOM$RANDOM")"
  close="${open%%[a-z]*}"
  { printf '# S\n\n%s\n' "$open"; printf '%s\n' "$@"; printf '%s\n' "$close"; } > "$d/skills/s/SKILL.md"
  expect "$label" "$want" "$re" "$d"
}
fence_case "~~~ fence: a relative script exits 1" 1 'script `\./scripts/run\.sh`' '~~~' './scripts/run.sh --flag'
fence_case "~~~bash fence: a relative script exits 1" 1 'script `\./scripts/run\.sh`' '~~~bash' './scripts/run.sh --flag'
fence_case "console fence: a '\$ ' command with a relative script exits 1" 1 'script `\./scripts/run\.sh`' '```console' '$ ./scripts/run.sh --flag'
fence_case "console fence: a '\$ ' command that reads an unset variable exits 1" 1 'reads \$X' '```console' '$ echo "$X"'
fence_case "unlabeled fence: bash ./x.sh exits 1" 1 'script `\./x\.sh`' '```' 'bash ./x.sh'
fence_case "unlabeled fence: scripts/x.sh exits 1" 1 'script `scripts/x\.sh`' '```' 'scripts/x.sh --a'
fence_case "unlabeled fence: python3 scripts/y.py exits 1" 1 'script `scripts/y\.py`' '```' 'python3 scripts/y.py'
fence_case "unlabeled fence: python3 y.py (interpreter, no path) exits 1" 1 'script `y\.py`' '```' 'python3 y.py'
fence_case "text fence: a \$VAR read exits 1" 1 'a .text. fence reads a shell variable' '```text' 'run $RUN_DIR/x'
fence_case "unlabeled fence: a \$VAR read exits 1" 1 'unlabeled fence reads a shell variable' '```' 'echo "$X"'
fence_case "a bare script name in a diagram exits 0" 0 '^OK: ' '```' 'detect-mode.sh' '  |-- r1.json'
fence_case "a path in a json fence exits 0" 0 '^OK: ' '```json' '{"file": "src/a.py"}'
fence_case "\${CLAUDE_SKILL_DIR} in an unlabeled fence is not a variable read" 0 '^OK: ' '```' 'see ${CLAUDE_SKILL_DIR}/scripts/run.sh'

# `cd` into the skill or plugin dir moves the user's shell there.
fence_case "cd \${CLAUDE_SKILL_DIR} in a bash fence exits 1" 1 'moves your shell into the skill directory' '```bash' 'cd "${CLAUDE_SKILL_DIR}/scripts" && ./run.sh'
fence_case "cd \${CLAUDE_PLUGIN_ROOT} in a bash fence exits 1" 1 'moves your shell into the skill directory' '```bash' 'cd "${CLAUDE_PLUGIN_ROOT}"'
fence_case "a (cd ...) subshell into the skill dir exits 0" 0 '^OK: ' '```bash' '(cd "${CLAUDE_SKILL_DIR}/scripts" && pwd)'
P="$(new_plugin cdspan)"
printf '# S\n\nFirst `cd "${CLAUDE_SKILL_DIR}"` then go.\n' > "$P/skills/s/SKILL.md"
expect "cd \${CLAUDE_SKILL_DIR} in an inline span exits 1" 1 'SKILL.md:3: .*moves your shell' "$P"

# Sentence punctuation after a path is not part of the path; a missing path is reported without it.
P="$(new_plugin punct)"
printf '# S\n\nSee ${CLAUDE_SKILL_DIR}/scripts/run.sh.\nAlso (${CLAUDE_SKILL_DIR}/references/r.md), and ${CLAUDE_SKILL_DIR}/scripts/run.sh; done:\n' > "$P/skills/s/SKILL.md"
expect "a path followed by . , ; : or ) still resolves" 0 '^OK: ' "$P"
printf '# S\n\nSee ${CLAUDE_SKILL_DIR}/scripts/gone.sh.\n' > "$P/skills/s/SKILL.md"
expect "a missing path is reported without the trailing period" 1 'scripts/gone\.sh does not exist' "$P"
# A path to a document in a span is not a command, so it needs no exec bit.
printf '# S\n\nRead `${CLAUDE_SKILL_DIR}/references/r.md` first.\n' > "$P/skills/s/SKILL.md"
expect "a document path that starts a span exits 0" 0 '^OK: ' "$P"

# Python scripts get the same checks as shell scripts.
P="$(new_plugin py)"
printf '#!/usr/bin/env python3\n' > "$P/skills/s/scripts/t.py"
chmod +x "$P/skills/s/scripts/t.py"
printf '# S\n\n```bash\npython3 "${CLAUDE_SKILL_DIR}/scripts/t.py" --x\n```\n' > "$P/skills/s/SKILL.md"
expect "an existing .py script with a full path exits 0" 0 '^OK: ' "$P"
printf '# S\n\n```bash\npython3 "${CLAUDE_SKILL_DIR}/scripts/missing.py" --x\n```\n' > "$P/skills/s/SKILL.md"
expect "a missing .py script exits 1" 1 'scripts/missing\.py does not exist' "$P"
printf '# S\n\n```bash\npython3 scripts/t.py --x\n```\n' > "$P/skills/s/SKILL.md"
expect "python3 scripts/t.py in a bash fence exits 1" 1 'script `scripts/t\.py`' "$P"
chmod -x "$P/skills/s/scripts/t.py"
mkdir -p "$P/skills/s/tools"
printf '#!/usr/bin/env python3\n' > "$P/skills/s/tools/u.py"
printf '# S\n\n```bash\n"${CLAUDE_SKILL_DIR}/tools/u.py" --x\n```\n' > "$P/skills/s/SKILL.md"
expect "a non-executable .py outside scripts/ started directly exits 1" 1 'tools/u\.py starts a command but is not executable' "$P"
printf '# S\n\n```bash\n"${CLAUDE_SKILL_DIR}/scripts/t.py" --x\n```\n' > "$P/skills/s/SKILL.md"
expect "a non-executable .py script started directly exits 1" 1 'not executable' "$P"

# --- survivors from the cross-model pass (PR #173) ---
# Data and code fences are never read as commands.
fence_case "json fence with \"\$schema\" exits 0" 0 '^OK: ' '```json' '{"$schema": "https://example.com/x.json", "a": "$HOME"}'
fence_case "ts fence with a \${price} template literal exits 0" 0 '^OK: ' '```ts' 'const s = `cost ${price} for ${n}`;'
fence_case "python fence with an f-string and \$ exits 0" 0 '^OK: ' '```python' 'print(f"cost: ${price} {n}")'
fence_case "yaml fence with \$GITHUB_OUTPUT exits 0" 0 '^OK: ' '```yaml' '  run: echo "x=1" >> $GITHUB_OUTPUT'
fence_case "markdown fence with \$HOME exits 0" 0 '^OK: ' '```markdown' 'Your home is $HOME.'
fence_case "~~~yaml fence with \$GITHUB_OUTPUT exits 0" 0 '^OK: ' '~~~yaml' '  run: echo "x=1" >> $GITHUB_OUTPUT'
fence_case "unlabeled fence reading \$RUN_DIR still exits 1" 1 'unlabeled fence reads a shell variable' '```' 'cat $RUN_DIR/x.json'
fence_case "~~~console fence reading \$RUN_DIR still exits 1" 1 'reads a shell variable' '~~~console' 'cat $RUN_DIR/x.json'

# A wrapper does not hide a non-executable script.
wrap_case() { # <label> <want> <regex> <command line>
  local d; d="$(new_plugin "wr-$RANDOM$RANDOM")"
  [[ "$2" == 1 ]] && chmod -x "$d/skills/s/scripts/run.sh"
  printf '# S\n\n```bash\n%s\n```\n' "$4" > "$d/skills/s/SKILL.md"
  expect "$1" "$2" "$3" "$d"
}
S='"${CLAUDE_SKILL_DIR}/scripts/run.sh"'
wrap_case "timeout wrapper, non-executable script, exits 1" 1 'not executable' "timeout 60 $S --x"
wrap_case "timeout with options, non-executable script, exits 1" 1 'not executable' "timeout -s KILL -k 5 60 $S"
wrap_case "env with NAME=value, non-executable script, exits 1" 1 'not executable' "env FOO=1 BAR=2 $S"
wrap_case "env -u NAME, non-executable script, exits 1" 1 'not executable' "env -u FOO $S"
wrap_case "nice -n, non-executable script, exits 1" 1 'not executable' "nice -n 5 $S"
wrap_case "command, non-executable script, exits 1" 1 'not executable' "command $S"
wrap_case "exec, non-executable script, exits 1" 1 'not executable' "exec $S"
wrap_case "chained wrappers, non-executable script, exits 1" 1 'not executable' "env FOO=1 timeout 5 nice $S"
wrap_case "a wrapper after && still checks the script" 1 'not executable' "true && timeout 5 $S"
wrap_case "timeout wrapper, executable script, exits 0" 0 '^OK: ' "timeout 60 $S --x"
wrap_case "env wrapper, executable script, exits 0" 0 '^OK: ' "env FOO=1 $S"
wrap_case "nice wrapper, executable script, exits 0" 0 '^OK: ' "nice -n 5 $S"
P="$(new_plugin wrapspan)"
chmod -x "$P/skills/s/scripts/run.sh"
printf '# S\n\nRun `timeout 60 "${CLAUDE_SKILL_DIR}/scripts/run.sh"` first.\n' > "$P/skills/s/SKILL.md"
expect "timeout wrapper in an inline span, non-executable script, exits 1" 1 'SKILL.md:3: .*not executable' "$P"

# <SCRIPTS_DIR>/x.sh that starts a command must be executable too.
P="$(new_plugin sdexec)"
printf '# S\n\nIn the references, <SCRIPTS_DIR> means "${CLAUDE_SKILL_DIR}/scripts".\n' > "$P/skills/s/SKILL.md"
printf '# ref\n\n```bash\n"<SCRIPTS_DIR>/run.sh" --x\n```\n' > "$P/skills/s/references/r.md"
expect "<SCRIPTS_DIR> script, executable, started directly exits 0" 0 '^OK: ' "$P"
chmod -x "$P/skills/s/scripts/run.sh"
expect "<SCRIPTS_DIR> script, non-executable, started directly exits 1" 1 'references/r.md:4: <SCRIPTS_DIR>/run\.sh starts a command but is not executable' "$P"
printf '# ref\n\n```bash\nbash "<SCRIPTS_DIR>/run.sh" --x\n```\n' > "$P/skills/s/references/r.md"
expect "<SCRIPTS_DIR> script run through bash needs no exec bit" 0 '^OK: ' "$P"
printf '# ref\n\n```bash\ntimeout 5 "<SCRIPTS_DIR>/run.sh"\n```\n' > "$P/skills/s/references/r.md"
expect "<SCRIPTS_DIR> script behind a wrapper, non-executable, exits 1" 1 'not executable' "$P"

# --- references are checked too ---
P="$(new_plugin ref)"
cat > "$P/skills/s/references/r.md" <<'EOF'
# ref

```bash
./scripts/run.sh
```
EOF
expect "bad command in a references file exits 1" 1 'references/r.md:4: script' "$P"

# --- <SCRIPTS_DIR> must be defined by SKILL.md ---
P="$(new_plugin scriptsdir)"
cat > "$P/skills/s/references/r.md" <<'EOF'
# ref

```bash
<SCRIPTS_DIR>/run.sh
```
EOF
expect "<SCRIPTS_DIR> in a reference with no definition exits 1" 1 'no definition line for <SCRIPTS_DIR>' "$P"
printf '\nIn the references, <SCRIPTS_DIR> means "${CLAUDE_SKILL_DIR}/scripts".\n' >> "$P/skills/s/SKILL.md"
expect "<SCRIPTS_DIR> defined in SKILL.md exits 0" 0 '^OK: ' "$P"

# --- a plugin with no SKILL.md must not pass ---
mkdir -p "$TMP/empty/skills"
expect "plugin with no SKILL.md exits 1, not a vacuous pass" 1 'nothing to check' "$TMP/empty"

# --- several plugins: one bad plugin fails the run ---
P1="$(new_plugin multi-good)"
P2="$(new_plugin multi-bad)"
printf '# S\n\n```bash\n./scripts/run.sh\n```\n' > "$P2/skills/s/SKILL.md"
expect "one bad plugin among several exits 1" 1 'multi-bad/skills/s/SKILL.md:4' "$P1" "$P2"

# --- usage errors ---
expect "no arguments exits 2" 2 'usage'
expect "--help exits 0 and prints usage" 0 '^usage: ' --help
expect "missing directory exits 2" 2 'not a directory' "$TMP/does-not-exist"
expect "a file instead of a directory exits 2" 2 'not a directory' "$TMP/clean/skills/s/SKILL.md"
expect "a missing directory after a good one still exits 2" 2 'not a directory' "$TMP/clean" "$TMP/does-not-exist"

# --- it checks the real analyzer, not a copy ---
if grep -q 'def block_problems' "$CHECKER"; then
  bad "checker must import the analyzer, not copy it"
else
  ok "checker imports the analyzer (no copy of block_problems)"
fi

echo
echo "passed: $PASS  failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
