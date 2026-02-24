#!/usr/bin/env bash
# sync-individual-repos.sh — Sync skills from local source into their individual GitHub repos
# Updates README.md with monorepo install option, copies files, and optionally commits/pushes.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/references"
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"
TODAY=$(date +%Y-%m-%d)

# Defaults
DRY_RUN=false
SYNC_ALL=false
GITHUB_USER=""
PUSH=false

usage() {
  cat <<'EOF'
Usage: sync-individual-repos.sh [options] [skill-name...]

Syncs skills from ~/.claude/skills/ into their individual GitHub repos.
Updates README.md with monorepo install option alongside individual clone.

Options:
  --dry-run              Preview changes without writing
  --all                  Sync all skills that have .git directories
  --github-user NAME     GitHub username (default: auto-detect via gh api)
  --push                 Commit and push changes (default: stage only)
  -h, --help             Show this help

Examples:
  sync-individual-repos.sh conversation-search
  sync-individual-repos.sh --all --dry-run
  sync-individual-repos.sh --all --push
EOF
  exit 0
}

# --- Parse arguments ---
SKILL_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true; shift ;;
    --all)          SYNC_ALL=true; shift ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    --push)         PUSH=true; shift ;;
    -h|--help)      usage ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)              SKILL_ARGS+=("$1"); shift ;;
  esac
done

# --- Resolve GitHub user ---
if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
  if [[ -z "$GITHUB_USER" ]]; then
    echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
    exit 1
  fi
fi

echo "GitHub user: $GITHUB_USER"
echo "Source:      $SKILLS_HOME"
echo ""

# --- Extract frontmatter field from a SKILL.md ---
extract_field() {
  local skill_md="$1"
  local field="$2"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "^${field}:" | head -1 | sed "s/^${field}:[[:space:]]*//; s/^[\"']//; s/[\"']$//"
}

extract_version() {
  local skill_md="$1"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "version:" | head -1 | sed 's/.*version:[[:space:]]*//; s/^[\"'"'"']//; s/[\"'"'"']$//'
}

short_desc() {
  echo "$1" | sed 's/\. Use when:.*/\./'
}

# --- Determine skills to sync ---
SKILLS=()
if $SYNC_ALL; then
  while IFS= read -r dir; do
    name=$(basename "$dir")
    if [[ -d "$dir/.git" ]] && [[ -f "$dir/SKILL.md" ]]; then
      SKILLS+=("$name")
    fi
  done < <(find "$SKILLS_HOME" -maxdepth 1 -mindepth 1 -type d | sort)
elif [[ ${#SKILL_ARGS[@]} -gt 0 ]]; then
  SKILLS=("${SKILL_ARGS[@]}")
else
  echo "Error: specify skill names or use --all" >&2
  exit 1
fi

echo "Skills to sync (${#SKILLS[@]}):"
for s in "${SKILLS[@]}"; do echo "  - $s"; done
echo ""

# --- Build directory tree for a skill ---
build_tree() {
  local skill_dir="$1"
  local skill_name="$2"
  (cd "$skill_dir" && find . -not -path './.git/*' -not -path './.git' -not -path './.claude/*' -not -path './.claude' -not -name '.DS_Store' | sort | sed 's|^./||' | while IFS= read -r path; do
    if [[ "$path" == "." ]]; then
      echo "${skill_name}/"
    else
      depth=$(echo "$path" | tr -cd '/' | wc -c | tr -d ' ')
      indent=""
      for ((i=0; i<depth; i++)); do indent="${indent}    "; done
      bname=$(basename "$path")
      if [[ -d "$skill_dir/$path" ]]; then
        echo "${indent}├── ${bname}/"
      else
        echo "${indent}├── ${bname}"
      fi
    fi
  done)
}

# --- Generate README with monorepo option ---
generate_readme() {
  local skill_name="$1"
  local short="$2"
  local what_it_does="$3"
  local tree="$4"

  cat <<EOF
# $skill_name

$short

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

\`\`\`bash
# macOS / Linux
git clone https://github.com/$GITHUB_USER/$skill_name.git ~/.claude/skills/$skill_name

# Windows
git clone https://github.com/$GITHUB_USER/$skill_name.git %USERPROFILE%\\.claude\\skills\\$skill_name
\`\`\`

**Project-level** (available only in one project):

\`\`\`bash
git clone https://github.com/$GITHUB_USER/$skill_name.git .claude/skills/$skill_name
\`\`\`

### Via monorepo (all skills)

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/$skill_name ~/.claude/skills/$skill_name
rm -rf /tmp/claude-code-skills
\`\`\`

## Updating

\`\`\`bash
git -C ~/.claude/skills/$skill_name pull
\`\`\`

## Uninstall

\`\`\`bash
rm -rf ~/.claude/skills/$skill_name
\`\`\`

## What It Does

$what_it_does

## Compatibility

This skill follows the **Agent Skills** standard — a \`SKILL.md\` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

\`\`\`
$tree
\`\`\`

## License

[MIT](LICENSE)
EOF
}

# --- Sync each skill ---
SYNCED=0
SKIPPED=0
ERRORS=0

for SKILL_NAME in "${SKILLS[@]}"; do
  SKILL_DIR="$SKILLS_HOME/$SKILL_NAME"
  SKILL_MD="$SKILL_DIR/SKILL.md"

  echo "--- $SKILL_NAME ---"

  # Validate
  if [[ ! -d "$SKILL_DIR" ]]; then
    echo "  ERROR: $SKILL_DIR not found"
    ((ERRORS++))
    echo ""
    continue
  fi

  if [[ ! -f "$SKILL_MD" ]]; then
    echo "  ERROR: $SKILL_MD not found"
    ((ERRORS++))
    echo ""
    continue
  fi

  if [[ ! -d "$SKILL_DIR/.git" ]]; then
    echo "  SKIP: no .git directory (not a published repo)"
    ((SKIPPED++))
    echo ""
    continue
  fi

  # Extract metadata
  NAME=$(extract_field "$SKILL_MD" "name")
  DESCRIPTION=$(extract_field "$SKILL_MD" "description")
  VERSION=$(extract_version "$SKILL_MD")
  SHORT=$(short_desc "$DESCRIPTION")

  if [[ -z "$VERSION" ]]; then
    VERSION="1.0.0"
  fi

  echo "  Version: $VERSION"

  # Generate updated README with monorepo option
  TREE=$(build_tree "$SKILL_DIR" "$SKILL_NAME")
  # Use the existing README's "What It Does" section if present, otherwise use short desc
  WHAT_IT_DOES="$SHORT"
  if [[ -f "$SKILL_DIR/README.md" ]]; then
    # Try to extract existing "What It Does" content
    existing_what=$(sed -n '/^## What It Does$/,/^## /{ /^## What It Does$/d; /^## /d; p; }' "$SKILL_DIR/README.md" | sed '/^$/d')
    if [[ -n "$existing_what" ]]; then
      WHAT_IT_DOES="$existing_what"
    fi
  fi

  NEW_README=$(generate_readme "$SKILL_NAME" "$SHORT" "$WHAT_IT_DOES" "$TREE")

  if $DRY_RUN; then
    echo "  WOULD UPDATE  README.md (with monorepo install option)"
  else
    echo "$NEW_README" > "$SKILL_DIR/README.md"
    echo "  UPDATED  README.md"
  fi

  # --- CONTRIBUTING.md (individual repo variant from template) ---
  if [[ -f "$TEMPLATE_DIR/CONTRIBUTING-template.md" ]]; then
    SCOPE_TMP=$(mktemp)
    cat > "$SCOPE_TMP" <<'SCOPE_EOF'
### Improving this skill

- Edit `SKILL.md` to improve the skill's instructions or metadata
- Add or improve scripts in `scripts/`
- Add or update reference material in `references/`
- Fix bugs or improve documentation
SCOPE_EOF

    CONTRIBUTING_TMP=$(mktemp)
    sed "s|{{REPO_NAME}}|$SKILL_NAME|g; s|{{GITHUB_USER}}|$GITHUB_USER|g; s|{{VALIDATE_COMMAND}}|scripts/validate-skill.sh .|g" \
      "$TEMPLATE_DIR/CONTRIBUTING-template.md" > "$CONTRIBUTING_TMP"
    awk -v scopefile="$SCOPE_TMP" '{
      if ($0 ~ /\{\{CONTRIBUTING_SCOPE\}\}/) {
        while ((getline line < scopefile) > 0) print line
        close(scopefile)
      } else print
    }' "$CONTRIBUTING_TMP" > "$CONTRIBUTING_TMP.out"
    mv "$CONTRIBUTING_TMP.out" "$CONTRIBUTING_TMP"
    CONTRIBUTING_CONTENT=$(cat "$CONTRIBUTING_TMP")
    rm -f "$SCOPE_TMP" "$CONTRIBUTING_TMP"

    if $DRY_RUN; then
      echo "  WOULD UPDATE  CONTRIBUTING.md"
    else
      echo "$CONTRIBUTING_CONTENT" > "$SKILL_DIR/CONTRIBUTING.md"
      echo "  UPDATED  CONTRIBUTING.md"
    fi
  fi

  # --- .github/PULL_REQUEST_TEMPLATE.md ---
  if [[ -f "$TEMPLATE_DIR/PR_TEMPLATE-template.md" ]]; then
    if $DRY_RUN; then
      echo "  WOULD UPDATE  .github/PULL_REQUEST_TEMPLATE.md"
    else
      mkdir -p "$SKILL_DIR/.github"
      cp "$TEMPLATE_DIR/PR_TEMPLATE-template.md" "$SKILL_DIR/.github/PULL_REQUEST_TEMPLATE.md"
      echo "  UPDATED  .github/PULL_REQUEST_TEMPLATE.md"
    fi
  fi

  # --- .github/workflows/validate-skill.yml (individual variant) ---
  if [[ -f "$TEMPLATE_DIR/workflow-individual.yml" ]]; then
    if $DRY_RUN; then
      echo "  WOULD UPDATE  .github/workflows/validate-skill.yml"
    else
      mkdir -p "$SKILL_DIR/.github/workflows"
      cp "$TEMPLATE_DIR/workflow-individual.yml" "$SKILL_DIR/.github/workflows/validate-skill.yml"
      echo "  UPDATED  .github/workflows/validate-skill.yml"
    fi
  fi

  # --- scripts/validate-skill.sh (copy from skill-publishing) ---
  VALIDATE_SRC="$SCRIPT_DIR/validate-skill.sh"
  if [[ -f "$VALIDATE_SRC" ]]; then
    if $DRY_RUN; then
      echo "  WOULD UPDATE  scripts/validate-skill.sh"
    else
      mkdir -p "$SKILL_DIR/scripts"
      cp "$VALIDATE_SRC" "$SKILL_DIR/scripts/validate-skill.sh"
      chmod +x "$SKILL_DIR/scripts/validate-skill.sh"
      echo "  UPDATED  scripts/validate-skill.sh"
    fi
  fi

  # Check if there are changes to commit
  if ! $DRY_RUN && $PUSH; then
    cd "$SKILL_DIR"
    if git diff --quiet HEAD 2>/dev/null && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
      echo "  No changes to push"
    else
      git add README.md CONTRIBUTING.md .github/ scripts/validate-skill.sh 2>/dev/null || true
      git commit -m "chore: sync contribution workflow files

Adds CONTRIBUTING.md, PR template, CI workflow, and validate-skill.sh.
Sync from local source ($TODAY).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
      git push
      echo "  PUSHED to origin"
    fi
    cd - >/dev/null
  fi

  ((SYNCED++))
  echo ""
done

# --- Summary ---
echo "Summary: $SYNCED synced, $SKIPPED skipped, $ERRORS errors"

if $DRY_RUN; then
  echo "Dry run complete. No files were written."
fi
