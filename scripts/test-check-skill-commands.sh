#!/usr/bin/env bash
set -euo pipefail

# test-check-skill-commands.sh — tests for scripts/check-skill-commands.py.
#
# Each case builds a small fixture plugin in a temp dir, runs the checker on it
# and asserts the exit code and, for failures, the `file:line: message` text.
# Every guard below was proven load-bearing by removing it in a scratch copy of
# the checker and watching its case go red.

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
expect "unlabeled fence starting with a relative script exits 1" 1 'SKILL.md:4: script `\./scripts/run\.sh` is a relative path in an unlabeled block' "$P"

# --- an unreadable file is a reported problem (exit 1), not a traceback ---
P="$(new_plugin badbytes)"
printf '# S\n\xff\xfe not utf-8\n' > "$P/skills/s/SKILL.md"
expect "non-UTF-8 SKILL.md exits 1 with a cannot-read line" 1 'SKILL.md:1: cannot read file' "$P"
P="$(new_plugin badref)"
printf '\xff\xfe\n' > "$P/skills/s/references/r.md"
expect "non-UTF-8 reference exits 1 with a cannot-read line" 1 'references/r.md:1: cannot read file' "$P"
out="$(python3 "$CHECKER" "$P" 2>&1 || true)"
if printf '%s' "$out" | grep -q Traceback; then bad "no traceback on unreadable file" "$out"; else ok "no traceback on unreadable file"; fi

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
expect "<SCRIPTS_DIR> in a reference with no definition exits 1" 1 'never defines it' "$P"
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
