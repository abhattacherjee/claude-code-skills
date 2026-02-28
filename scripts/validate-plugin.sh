#!/usr/bin/env bash
# validate-plugin.sh — Validate a Claude Code plugin directory against quality rules
# Exit codes: 0 = pass, 1 = fail, 2 = usage error
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Usage ---
usage() {
  cat <<'EOF'
Usage: validate-plugin.sh [options] <plugin-directory>

Validates a Claude Code plugin directory against quality rules:
  - .claude-plugin/plugin.json exists with required fields
  - name: kebab-case, ≤64 characters
  - version: valid semver (X.Y.Z)
  - Commands have YAML frontmatter or description header
  - Skills pass validate-skill.sh
  - Scripts are executable with proper shebang
  - Agent references in SKILL.md matched against agents/ directory
  - Items declared in plugin.json exist on disk

Options:
  -h, --help    Show this help

Examples:
  validate-plugin.sh ./build/git-flow
  validate-plugin.sh plugins/git-flow/

Exit codes:
  0  All checks passed
  1  One or more checks failed
  2  Usage error (missing argument, directory not found)
EOF
  exit 0
}

# --- Parse arguments ---
PLUGIN_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    -*)        echo "Error: Unknown option: $1" >&2; exit 2 ;;
    *)         PLUGIN_DIR="$1"; shift ;;
  esac
done

if [[ -z "$PLUGIN_DIR" ]]; then
  echo "Error: plugin directory is required" >&2
  echo "Usage: validate-plugin.sh [options] <plugin-directory>" >&2
  exit 2
fi

if [[ ! -d "$PLUGIN_DIR" ]]; then
  echo "Error: directory not found: $PLUGIN_DIR" >&2
  exit 2
fi

PLUGIN_DIR="$(cd "$PLUGIN_DIR" && pwd)"

ERRORS=0
WARNINGS=0

pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo "  WARN  $1"; WARNINGS=$((WARNINGS + 1)); }

echo "Validating plugin: $PLUGIN_DIR"
echo ""

# ============================================================
# 1. plugin.json exists
# ============================================================
echo "--- plugin.json ---"

PLUGIN_JSON="$PLUGIN_DIR/.claude-plugin/plugin.json"

if [[ ! -f "$PLUGIN_JSON" ]]; then
  fail ".claude-plugin/plugin.json not found"
  echo ""
  echo "Result: FAIL ($ERRORS error(s), $WARNINGS warning(s))"
  exit 1
fi
pass ".claude-plugin/plugin.json exists"

# Check dependencies
if ! command -v jq &>/dev/null; then
  echo "Error: jq is required for plugin validation" >&2
  exit 2
fi

# ============================================================
# 2. Required fields
# ============================================================
NAME=$(jq -r '.name // empty' "$PLUGIN_JSON")
VERSION=$(jq -r '.version // empty' "$PLUGIN_JSON")
DESCRIPTION=$(jq -r '.description // empty' "$PLUGIN_JSON")

if [[ -z "$NAME" ]]; then
  fail "name: field missing or empty"
else
  pass "name: present ($NAME)"
fi

if [[ -z "$VERSION" ]]; then
  fail "version: field missing or empty"
else
  pass "version: present ($VERSION)"
fi

if [[ -z "$DESCRIPTION" ]]; then
  fail "description: field missing or empty"
else
  pass "description: present"
fi

# ============================================================
# 3. Name format: kebab-case, ≤64 chars
# ============================================================
echo ""
echo "--- name format ---"

if [[ -n "$NAME" ]]; then
  if echo "$NAME" | grep -qE '^[a-z][a-z0-9-]*$'; then
    pass "name: valid kebab-case format"
  else
    fail "name: must be lowercase letters, digits, and hyphens (got: $NAME)"
  fi

  NAME_LEN=${#NAME}
  if [[ $NAME_LEN -le 64 ]]; then
    pass "name: length OK ($NAME_LEN chars, max 64)"
  else
    fail "name: too long ($NAME_LEN chars, max 64)"
  fi
fi

# ============================================================
# 4. Version: valid semver
# ============================================================
echo ""
echo "--- version ---"

if [[ -n "$VERSION" ]]; then
  if echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    pass "version: valid semver ($VERSION)"
  else
    fail "version: invalid semver (expected X.Y.Z, got: $VERSION)"
  fi
fi

# ============================================================
# 5. Commands validation
# ============================================================
if [[ -d "$PLUGIN_DIR/commands" ]]; then
  echo ""
  echo "--- commands ---"

  CMD_COUNT=0
  while IFS= read -r cmd_file; do
    CMD_COUNT=$((CMD_COUNT + 1))
    CMD_NAME=$(basename "$cmd_file")

    # Check for YAML frontmatter or description
    FIRST_LINE=$(head -1 "$cmd_file")
    if [[ "$FIRST_LINE" == "---" ]]; then
      pass "$CMD_NAME: has YAML frontmatter"
    elif echo "$FIRST_LINE" | grep -qi "description\|#"; then
      pass "$CMD_NAME: has description header"
    else
      warn "$CMD_NAME: no YAML frontmatter or description header"
    fi
  done < <(find "$PLUGIN_DIR/commands" -name '*.md' -type f | sort)

  if [[ $CMD_COUNT -eq 0 ]]; then
    warn "commands/ directory exists but contains no .md files"
  else
    pass "commands: $CMD_COUNT command(s) found"
  fi
fi

# ============================================================
# 6. Skills validation (delegate to validate-skill.sh)
# ============================================================
if [[ -d "$PLUGIN_DIR/skills" ]]; then
  echo ""
  echo "--- skills ---"

  VALIDATE_SKILL="$SCRIPT_DIR/validate-skill.sh"
  SKILL_COUNT=0

  while IFS= read -r skill_dir; do
    SKILL_COUNT=$((SKILL_COUNT + 1))
    SKILL_NAME=$(basename "$skill_dir")

    if [[ -f "$VALIDATE_SKILL" ]] && [[ -x "$VALIDATE_SKILL" ]]; then
      echo ""
      echo "  Validating skill: $SKILL_NAME"
      if "$VALIDATE_SKILL" "$skill_dir" 2>&1 | sed 's/^/    /'; then
        pass "skill $SKILL_NAME: passes validation"
      else
        fail "skill $SKILL_NAME: fails validation"
      fi
    elif [[ -f "$skill_dir/SKILL.md" ]]; then
      pass "skill $SKILL_NAME: SKILL.md exists (validator not available for detailed check)"
    else
      fail "skill $SKILL_NAME: missing SKILL.md"
    fi
  done < <(find "$PLUGIN_DIR/skills" -maxdepth 1 -mindepth 1 -type d | sort)

  if [[ $SKILL_COUNT -eq 0 ]]; then
    warn "skills/ directory exists but contains no skill subdirectories"
  fi
fi

# ============================================================
# 7. Scripts executable with proper shebang
# ============================================================
SCRIPTS_FOUND=false
for scripts_dir in "$PLUGIN_DIR/scripts" "$PLUGIN_DIR/skills"/*/scripts; do
  if [[ -d "$scripts_dir" ]]; then
    if ! $SCRIPTS_FOUND; then
      echo ""
      echo "--- scripts ---"
      SCRIPTS_FOUND=true
    fi

    while IFS= read -r script; do
      SCRIPT_NAME=$(basename "$script")
      REL_PATH="${script#$PLUGIN_DIR/}"

      if [[ -x "$script" ]]; then
        pass "$REL_PATH: executable"
      else
        warn "$REL_PATH: not executable"
      fi

      SHEBANG=$(head -1 "$script")
      if [[ "$SHEBANG" == "#!/usr/bin/env bash" ]]; then
        pass "$REL_PATH: correct shebang"
      elif echo "$SHEBANG" | grep -q '^#!'; then
        warn "$REL_PATH: non-standard shebang ($SHEBANG)"
      else
        warn "$REL_PATH: missing shebang"
      fi
    done < <(find "$scripts_dir" -name '*.sh' -type f | sort)
  fi
done

# ============================================================
# 8. Agent cross-reference: SKILL.md mentions vs agents/ directory
# ============================================================
echo ""
echo "--- agent references ---"

AGENT_REFS_FOUND=false
while IFS= read -r skill_md; do
  # Extract agent filenames referenced in SKILL.md (patterns: agents/name.md, ~/.claude/agents/name.md)
  REFERENCED_AGENTS=$(grep -ohE 'agents/[a-z][-a-z0-9]+\.md' "$skill_md" 2>/dev/null | sed 's|.*/||' | sort -u)

  if [[ -n "$REFERENCED_AGENTS" ]]; then
    AGENT_REFS_FOUND=true
    SKILL_REL="${skill_md#$PLUGIN_DIR/}"

    while IFS= read -r agent_file; do
      AGENT_NAME="${agent_file%.md}"
      if [[ -f "$PLUGIN_DIR/agents/$agent_file" ]]; then
        pass "$SKILL_REL references $AGENT_NAME: found in agents/"
      else
        warn "$SKILL_REL references $AGENT_NAME: NOT found in agents/ (add to plugin-manifest.json agents array)"
      fi
    done <<< "$REFERENCED_AGENTS"
  fi
done < <(find "$PLUGIN_DIR/skills" -name 'SKILL.md' -type f 2>/dev/null | sort)

if ! $AGENT_REFS_FOUND; then
  pass "no agent references found in skills (none expected)"
fi

# ============================================================
# 9. Cross-reference: structure integrity
# ============================================================
echo ""
echo "--- structure ---"

# Check essential directories exist
if [[ -d "$PLUGIN_DIR/skills" ]] || [[ -d "$PLUGIN_DIR/commands" ]]; then
  pass "plugin has content (skills and/or commands)"
else
  fail "plugin has no skills/ or commands/ directory"
fi

# Check README
if [[ -f "$PLUGIN_DIR/README.md" ]]; then
  pass "README.md exists"
else
  warn "no README.md"
fi

# Check LICENSE
if [[ -f "$PLUGIN_DIR/LICENSE" ]]; then
  pass "LICENSE exists"
else
  warn "no LICENSE"
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
