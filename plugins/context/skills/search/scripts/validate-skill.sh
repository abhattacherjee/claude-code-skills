#!/usr/bin/env bash
# validate-skill.sh — Validate a Claude Code skill directory against quality rules
# NOTE: Copies of this validator ship in the monorepo root scripts/ and in the scripts/
# of these plugin skills: context:search, dev-flow:changelog, dev-flow:worktree,
# skill-kit:author, skill-kit:extract and skill-kit:publish. Keep those copies
# byte-identical when editing.
# Exit codes: 0 = pass, 1 = fail, 2 = usage error
set -eu

# --- Usage ---
usage() {
  cat <<'EOF'
Usage: validate-skill.sh [options] <skill-directory>

Validates a Claude Code skill directory against quality rules:
  - SKILL.md exists with valid YAML frontmatter
  - name: lowercase + hyphens, ≤64 characters, no "anthropic" or "claude"
  - description: ≤1024 characters, third person, "Use when:" present
  - metadata.version: present and valid semver
  - No non-standard frontmatter fields (author, date, tags are disallowed)
  - Version matches CHANGELOG.md (if present)
  - Body: under 500 lines
  - Reference .md files: named in SKILL.md (or read by a script); over 100 lines,
    a ## Contents heading in the first 30 lines
  - Scripts: executable, #!/usr/bin/env bash shebang, --help support

Options:
  -h, --help    Show this help

Examples:
  validate-skill.sh ~/.claude/skills/my-skill    # Individual skill
  validate-skill.sh .                            # Current directory as skill
  validate-skill.sh plugins/dev-flow/skills/changelog/   # Skill inside a plugin

Exit codes:
  0  All checks passed
  1  One or more checks failed
  2  Usage error (missing argument, directory not found)
EOF
  exit 0
}

# --- Parse arguments ---
SKILL_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    -*)        echo "Error: Unknown option: $1" >&2; exit 2 ;;
    *)         SKILL_DIR="$1"; shift ;;
  esac
done

if [[ -z "$SKILL_DIR" ]]; then
  echo "Error: skill directory is required" >&2
  echo "Usage: validate-skill.sh [options] <skill-directory>" >&2
  exit 2
fi

# Resolve to absolute path
if [[ -d "$SKILL_DIR" ]]; then
  SKILL_DIR="$(cd "$SKILL_DIR" && pwd)"
else
  echo "Error: directory not found: $SKILL_DIR" >&2
  exit 2
fi

SKILL_MD="$SKILL_DIR/SKILL.md"
ERRORS=0
WARNINGS=0

pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo "  WARN  $1"; WARNINGS=$((WARNINGS + 1)); }

echo "Validating: $SKILL_DIR"
echo ""

# ============================================================
# 1. SKILL.md exists
# ============================================================
echo "--- SKILL.md ---"

if [[ ! -f "$SKILL_MD" ]]; then
  fail "SKILL.md not found"
  echo ""
  echo "Result: FAIL ($ERRORS error(s), $WARNINGS warning(s))"
  exit 1
fi
pass "SKILL.md exists"

# ============================================================
# 2. Frontmatter extraction helpers
# ============================================================
# Extract ONLY the first frontmatter block (between first pair of --- delimiters)
# This avoids matching example frontmatter in the body of skills like skill-kit:author
get_frontmatter() {
  awk '/^---$/{n++; if(n==2) exit; next} n==1{print}' "$SKILL_MD"
}

extract_field() {
  local field="$1"
  local fm first val
  fm="$(get_frontmatter)"
  first="$(printf '%s\n' "$fm" | grep "^${field}:" | head -1)"
  [[ -z "$first" ]] && return 0
  val="$(printf '%s' "$first" | sed "s/^${field}:[[:space:]]*//")"
  # YAML block scalar (>, >-, |, |-, etc.): fold the indented continuation lines into one
  # space-joined string. Both > (fold) and | (literal) indicators are treated the same —
  # only the text is needed for the length / "Use when:" / third-person checks, not exact
  # newline semantics. Continuation lines are assumed uniformly indented: a non-indented
  # line ends the block (per YAML), so a mis-indented line legitimately stops folding.
  #
  # The header grammar is kept in step with _lib.sh's extract_field DELIBERATELY: this
  # validator is the CI gate for the same frontmatter that _lib.sh renders into published
  # artifacts, so a header one reader accepts and the other does not is a file that passes
  # validation and publishes corrupt (or the reverse). The two indicators may appear in
  # EITHER order — YAML permits chomping before indentation — so `>-2` and `>2-` are both
  # legal. The earlier `[0-9]*[+-]?` accepted only the second and read `>-2` as a plain
  # scalar whose text is the literal ">-2".
  #
  # Not in step, and deliberately so: _lib.sh EXITS 3 on a `|`/`>` that matches no legal
  # header (`>10`, `>--`), because there it would otherwise become the description of a
  # published README. Here the same value falls through to the plain-scalar branch and is
  # checked as ordinary text, where the length and "Use when:" rules reject it anyway.
  if printf '%s' "$val" | grep -qE '^[|>]([0-9][+-]?|[+-][0-9]?)?[[:space:]]*(#.*)?$'; then
    printf '%s\n' "$fm" | awk -v f="^${field}:" '
      $0 ~ f { grab = 1; next }
      grab {
        if ($0 ~ /^[^[:space:]]/) exit        # non-indented line ends the block scalar
        if ($0 ~ /^[[:space:]]*$/) next       # skip blank lines (avoid double spaces)
        sub(/^[[:space:]]+/, "")
        out = out (out == "" ? "" : " ") $0
      }
      END { print out }
    '
  else
    printf '%s' "$val" | sed "s/^[\"']//; s/[\"']$//"
  fi
}

extract_version() {
  get_frontmatter | grep "version:" | head -1 | sed 's/.*version:[[:space:]]*//; s/^[\"'"'"']//; s/[\"'"'"']$//'
}

# Check frontmatter delimiters exist
FRONTMATTER_START=$(grep -n '^---$' "$SKILL_MD" | head -1 | cut -d: -f1)
FRONTMATTER_END=$(grep -n '^---$' "$SKILL_MD" | sed -n '2p' | cut -d: -f1)

if [[ -z "$FRONTMATTER_START" ]] || [[ -z "$FRONTMATTER_END" ]]; then
  fail "YAML frontmatter not found (missing --- delimiters)"
  echo ""
  echo "Result: FAIL ($ERRORS error(s), $WARNINGS warning(s))"
  exit 1
fi
pass "YAML frontmatter delimiters present"

# ============================================================
# 3. name field
# ============================================================
echo ""
echo "--- name ---"

NAME=$(extract_field "name")

if [[ -z "$NAME" ]]; then
  fail "name: field missing or empty"
else
  pass "name: present ($NAME)"

  # Lowercase + hyphens only
  if echo "$NAME" | grep -qE '^[a-z][a-z0-9-]*$'; then
    pass "name: valid format (lowercase + hyphens)"
  else
    fail "name: must be lowercase letters, digits, and hyphens only (got: $NAME)"
  fi

  # ≤64 characters
  NAME_LEN=${#NAME}
  if [[ $NAME_LEN -le 64 ]]; then
    pass "name: length OK ($NAME_LEN chars, max 64)"
  else
    fail "name: too long ($NAME_LEN chars, max 64)"
  fi

  # Reserved words: Anthropic's guide forbids "anthropic" and "claude" anywhere in a name
  NAME_LC="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]')"
  RESERVED=""
  for word in anthropic claude; do
    case "$NAME_LC" in
      *"$word"*) RESERVED="$word"; fail "name: must not contain the reserved word \"$word\" (got: $NAME)" ;;
    esac
  done
  [[ -z "$RESERVED" ]] && pass "name: no reserved words (anthropic, claude)"
fi

# ============================================================
# 4. description field
# ============================================================
echo ""
echo "--- description ---"

DESCRIPTION=$(extract_field "description")

if [[ -z "$DESCRIPTION" ]]; then
  fail "description: field missing or empty"
else
  DESC_LEN=${#DESCRIPTION}

  # ≤1024 characters
  if [[ $DESC_LEN -le 1024 ]]; then
    pass "description: length OK ($DESC_LEN chars, max 1024)"
  else
    fail "description: too long ($DESC_LEN chars, max 1024)"
  fi

  # Third person (should NOT start with "I ", "You ", etc.)
  if echo "$DESCRIPTION" | grep -qiE '^(I |You |We )'; then
    fail "description: should be third person (starts with I/You/We)"
  else
    pass "description: third person"
  fi

  # "Use when:" present
  if echo "$DESCRIPTION" | grep -q "Use when:"; then
    pass "description: contains 'Use when:'"
  else
    fail "description: must contain 'Use when:' trigger list"
  fi
fi

# ============================================================
# 5. metadata.version
# ============================================================
echo ""
echo "--- metadata.version ---"

VERSION=$(extract_version)

if [[ -z "$VERSION" ]]; then
  fail "metadata.version: missing"
else
  pass "metadata.version: present ($VERSION)"

  # Valid semver (major.minor.patch)
  if echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    pass "metadata.version: valid semver"
  else
    fail "metadata.version: invalid semver (expected X.Y.Z, got: $VERSION)"
  fi
fi

# ============================================================
# 5b. Version matches CHANGELOG.md (if it exists)
# ============================================================
CHANGELOG_FILE="$SKILL_DIR/CHANGELOG.md"
if [[ -n "$VERSION" ]] && [[ -f "$CHANGELOG_FILE" ]]; then
  CHANGELOG_VERSION=$(grep -oE '\[[0-9]+\.[0-9]+\.[0-9]+\]' "$CHANGELOG_FILE" | head -1 | tr -d '[]')
  if [[ -z "$CHANGELOG_VERSION" ]]; then
    warn "CHANGELOG.md exists but has no versioned entry"
  elif [[ "$VERSION" == "$CHANGELOG_VERSION" ]]; then
    pass "version matches CHANGELOG.md ($VERSION)"
  else
    fail "version mismatch: SKILL.md=$VERSION, CHANGELOG.md=$CHANGELOG_VERSION"
  fi
elif [[ -n "$VERSION" ]] && [[ ! -f "$CHANGELOG_FILE" ]]; then
  warn "no CHANGELOG.md found (recommended for published skills)"
fi

# ============================================================
# 6. No non-standard frontmatter fields
# ============================================================
echo ""
echo "--- frontmatter fields ---"

# Extract all top-level keys from first frontmatter block only
# Standard fields: name, description, metadata (and nested version)
FRONTMATTER_KEYS=$(get_frontmatter | grep -E '^[a-zA-Z]' | sed 's/:.*//' | sort -u)
NON_STANDARD=""

for key in $FRONTMATTER_KEYS; do
  case "$key" in
    name|description|metadata|model|disable-model-invocation) ;; # allowed (model: sub-agent skills; disable-model-invocation: slash-command-only skills)
    *) NON_STANDARD="$NON_STANDARD $key" ;;
  esac
done

if [[ -z "$NON_STANDARD" ]]; then
  pass "no non-standard frontmatter fields"
else
  fail "non-standard frontmatter fields:$NON_STANDARD (allowed: name, description, metadata, model, disable-model-invocation)"
fi

# ============================================================
# 7. Body length (under 500 lines)
# ============================================================
# Counted as scripts/check-skill-structure.py counts it (S1): the lines after the
# closing --- of a frontmatter that opens on line 1, else every line. awk counts a
# last line with no newline, which wc -l does not.
echo ""
echo "--- body ---"

MAX_BODY=500   # Anthropic's guide: keep the SKILL.md body under 500 lines
BODY_LINES=$(awk '
  /^[[:space:]]*---[[:space:]]*$/ { if (NR == 1) { open = 1; next } if (open && !shut) shut = NR }
  END { print (shut ? NR - shut : NR) }' "$SKILL_MD")

if [[ $BODY_LINES -lt $MAX_BODY ]]; then
  pass "body: $BODY_LINES lines (must be under $MAX_BODY)"
else
  fail "body: $BODY_LINES lines (must be under $MAX_BODY)"
fi

# ============================================================
# 7b. Reference files: named from SKILL.md, and a Contents list
# ============================================================
# The rules of scripts/check-skill-structure.py (S2, S3); a parity test in
# scripts/test-check-skill-structure.sh keeps the two in step. Checked: every .md
# file under the skill directory other than SKILL.md, README.md, CHANGELOG.md and
# CONTRIBUTING.md, and not under a dot-directory such as .github/.
#   S2  SKILL.md names its path relative to the skill directory (bare, ./ or
#       ${CLAUDE_SKILL_DIR}/ in front), or a file under scripts/ names its file name.
#   S3  a file over 100 lines has a ## Contents or ## Table of contents heading in
#       its first 30 lines, outside a fenced code block.
# Blind spots, as in the Python checker: any mention counts (a comment, a "do not
# read" line); non-.md files are not checked. Names are matched byte by byte, so a
# non-ASCII letter glued to a path does not stop it counting here (it does in Python).
echo ""
echo "--- references ---"

TOC_MIN_LINES=100  # Anthropic's guide: a reference file over 100 lines needs a contents list
TOC_WITHIN=30      # ...near the top, where a partial read (head) still shows it

# names <path|file> <target> <file>...: exit 0 when a file names target on its own.
# After target, the next char must not extend it: not a word char or -, and not a .
# followed by a word char (x.md. ends a sentence; x.md.bak is another file).
# path: the char before target (after an optional ./ or ${CLAUDE_SKILL_DIR}/) must not
#   be part of a path, so other/./references/x.md does not name references/x.md.
# file: the char before must not be a word char, . or -; a / is fine ("$DIR/x.md").
names() {
  local mode="$1" target="$2"
  shift 2
  LC_ALL=C awk -v mode="$mode" -v t="$target" '
    function w(c) { return c ~ /^[A-Za-z0-9_]$/ }
    BEGIN { pfx = "${CLAUDE_SKILL_DIR}/" }
    {
      s = $0; off = 0
      while ((i = index(substr(s, off + 1), t)) > 0) {
        p = off + i; off = p
        nx = substr(s, p + length(t), 1)
        if (w(nx) || nx == "-" || (nx == "." && w(substr(s, p + length(t) + 1, 1)))) continue
        pre = substr(s, 1, p - 1)
        if (mode == "path") {
          if (length(pre) >= 2 && substr(pre, length(pre) - 1) == "./") pre = substr(pre, 1, length(pre) - 2)
          else if (length(pre) >= length(pfx) && substr(pre, length(pre) - length(pfx) + 1) == pfx) pre = substr(pre, 1, length(pre) - length(pfx))
          c = substr(pre, length(pre), 1)
          if (c == "" || !(w(c) || index("./${}-", c))) { found = 1; exit }
        } else {
          c = substr(pre, length(pre), 1)
          if (c == "" || !(w(c) || c == "." || c == "-")) { found = 1; exit }
        }
      }
    }
    END { exit (found ? 0 : 1) }' "$@"
}

# has_toc <file>: exit 0 when a ## Contents heading sits in the first TOC_WITHIN lines,
# outside a fenced block. A fence is 3+ backticks or tildes after at most 3 spaces; a
# backtick fence line has no other backtick (so ```inline``` is not one). A fence closes
# on the same char, at least as long, with nothing but spaces after it.
has_toc() {
  LC_ALL=C awk -v within="$TOC_WITHIN" '
    NR > within { exit }
    {
      line = $0; ind = 0
      while (ind < 4 && substr(line, ind + 1, 1) == " ") ind++
      if (ind < 4) {
        rest = substr(line, ind + 1); c = substr(rest, 1, 1)
        if (c == "`" || c == "~") {
          n = 0
          while (substr(rest, n + 1, 1) == c) n++
          after = substr(rest, n + 1)
          if (n >= 3 && (c == "~" || index(after, "`") == 0)) {
            if (fc == "") { fc = c; fn = n }
            else if (c == fc && n >= fn && after ~ /^[[:space:]]*$/) fc = ""
            next
          }
        }
      }
      if (fc == "" && tolower(line) ~ /^##[[:space:]]+(contents|table of contents)[[:space:]]*$/) { found = 1; exit }
    }
    END { exit (found ? 0 : 1) }' "$1"
}

SCRIPT_FILES=()
if [[ -d "$SKILL_DIR/scripts" ]]; then
  while IFS= read -r f; do
    SCRIPT_FILES+=("$SKILL_DIR/scripts/${f#./}")
  done < <(cd "$SKILL_DIR/scripts" && find . -type f | LC_ALL=C sort)
fi

REF_COUNT=0
while IFS= read -r rel; do
  rel="${rel#./}"
  case "${rel##*/}" in SKILL.md|README.md|CHANGELOG.md|CONTRIBUTING.md) continue ;; esac
  case "/$rel" in */.*) continue ;; esac
  [[ -f "$SKILL_DIR/$rel" ]] || continue
  REF_COUNT=$((REF_COUNT + 1))

  if names path "$rel" "$SKILL_MD" \
     || { [[ ${#SCRIPT_FILES[@]} -gt 0 ]] && names file "${rel##*/}" "${SCRIPT_FILES[@]}"; }; then
    pass "$rel: named in SKILL.md or read by a script"
  else
    fail "$rel: not named in SKILL.md or read by a script in scripts/"
  fi

  REF_LINES=$(awk 'END { print NR }' "$SKILL_DIR/$rel")
  if [[ $REF_LINES -gt $TOC_MIN_LINES ]]; then
    if has_toc "$SKILL_DIR/$rel"; then
      pass "$rel: has a Contents heading ($REF_LINES lines)"
    else
      fail "$rel: $REF_LINES lines with no '## Contents' heading in the first $TOC_WITHIN lines"
    fi
  fi
done < <(cd "$SKILL_DIR" && find . -name '*.md' | LC_ALL=C sort)

if [[ $REF_COUNT -eq 0 ]]; then
  pass "no reference files besides SKILL.md, README.md and CHANGELOG.md"
fi

# ============================================================
# 8. Scripts validation (if scripts/ directory exists)
# ============================================================
if [[ -d "$SKILL_DIR/scripts" ]]; then
  echo ""
  echo "--- scripts ---"

  SCRIPT_COUNT=0
  while IFS= read -r script; do
    SCRIPT_COUNT=$((SCRIPT_COUNT + 1))  # safe with set -e (unlike ((var++)))
    SCRIPT_NAME=$(basename "$script")

    # Executable permission
    if [[ -x "$script" ]]; then
      pass "$SCRIPT_NAME: executable"
    else
      fail "$SCRIPT_NAME: not executable (chmod +x needed)"
    fi

    # Shebang
    FIRST_LINE=$(head -1 "$script")
    if [[ "$FIRST_LINE" == "#!/usr/bin/env bash" ]]; then
      pass "$SCRIPT_NAME: correct shebang"
    elif echo "$FIRST_LINE" | grep -q '^#!'; then
      warn "$SCRIPT_NAME: non-standard shebang ($FIRST_LINE), expected #!/usr/bin/env bash"
    else
      fail "$SCRIPT_NAME: missing shebang (first line: $FIRST_LINE)"
    fi

    # --help support
    if grep -q '\-\-help' "$script" 2>/dev/null; then
      pass "$SCRIPT_NAME: --help supported"
    else
      warn "$SCRIPT_NAME: no --help flag detected"
    fi
  done < <(find "$SKILL_DIR/scripts" -name '*.sh' -type f | sort)

  if [[ $SCRIPT_COUNT -eq 0 ]]; then
    warn "scripts/ directory exists but contains no .sh files"
  fi
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "============================================================"
if [[ $ERRORS -eq 0 ]]; then
  echo "Result: PASS ($WARNINGS warning(s))"
  exit 0
else
  echo "Result: FAIL ($ERRORS error(s), $WARNINGS warning(s))"
  exit 1
fi
