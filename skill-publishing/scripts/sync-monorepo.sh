#!/usr/bin/env bash
# sync-monorepo.sh — Sync skills from ~/.claude/skills/ into a monorepo directory
# Generates root README with catalog table and per-skill READMEs.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/references"
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)

# Defaults
DRY_RUN=false
INIT_MODE=false
GITHUB_USER=""
SKILLS_LIST=""
ADD_SKILL=""
MONOREPO_DIR=""
AUTHOR="Abhishek"

usage() {
  cat <<'EOF'
Usage: sync-monorepo.sh [options] <monorepo-dir>

Syncs skills from ~/.claude/skills/ into a monorepo directory with a
generated root README containing a catalog table.

Options:
  --dry-run              Preview changes without writing
  --skills <list>        Comma-separated skill names (default: all in monorepo)
  --add <skill-name>     Add a new skill to the monorepo
  --github-user NAME     GitHub username (default: auto-detect via gh api)
  --author NAME          Name for LICENSE copyright (default: Abhishek)
  --init                 Initialize monorepo (create repo, first commit)
  -h, --help             Show this help

Examples:
  sync-monorepo.sh --init ~/dev/claude-code-skills
  sync-monorepo.sh ~/dev/claude-code-skills
  sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills
  sync-monorepo.sh --dry-run ~/dev/claude-code-skills
EOF
  exit 0
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true; shift ;;
    --init)         INIT_MODE=true; shift ;;
    --skills)       SKILLS_LIST="$2"; shift 2 ;;
    --add)          ADD_SKILL="$2"; shift 2 ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    --author)       AUTHOR="$2"; shift 2 ;;
    -h|--help)      usage ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)              MONOREPO_DIR="$1"; shift ;;
  esac
done

if [[ -z "$MONOREPO_DIR" ]]; then
  echo "Error: monorepo directory is required" >&2
  echo "Usage: sync-monorepo.sh [options] <monorepo-dir>" >&2
  exit 1
fi

# --- Resolve GitHub user ---
if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "")
  if [[ -z "$GITHUB_USER" ]]; then
    echo "Error: could not detect GitHub username. Use --github-user NAME" >&2
    exit 1
  fi
fi

echo "GitHub user: $GITHUB_USER"
echo "Monorepo:    $MONOREPO_DIR"
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

# Short description: first sentence (before "Use when:"), no char truncation
short_desc() {
  echo "$1" | sed 's/\. Use when:.*/\./'
}

# --- Init mode: create monorepo directory and git repo ---
if $INIT_MODE; then
  if [[ -d "$MONOREPO_DIR/.git" ]]; then
    echo "Warning: $MONOREPO_DIR already has a .git directory. Skipping init."
    INIT_MODE=false
  else
    echo "Initializing monorepo at $MONOREPO_DIR..."
    if ! $DRY_RUN; then
      mkdir -p "$MONOREPO_DIR"
    fi
  fi
fi

# --- Determine which skills to sync ---
discover_skills() {
  # If --add specified, add it to existing skills
  if [[ -n "$ADD_SKILL" ]]; then
    # Get existing skill dirs in monorepo
    local existing=""
    if [[ -d "$MONOREPO_DIR" ]]; then
      existing=$(find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
        ! -name '.git' ! -name '.github' ! -name '.*' \
        -exec basename {} \; 2>/dev/null | sort | tr '\n' ',')
    fi
    echo "${existing}${ADD_SKILL}" | tr ',' '\n' | sort -u | grep -v '^$'
    return
  fi

  # If --skills specified, use that list
  if [[ -n "$SKILLS_LIST" ]]; then
    echo "$SKILLS_LIST" | tr ',' '\n' | sort
    return
  fi

  # For --init with no --skills, default to the initial set
  # (Must check INIT_MODE before directory existence — init creates the dir first)
  if $INIT_MODE; then
    echo "conversation-search"
    echo "skill-authoring"
    echo "skill-publishing"
    return
  fi

  # If monorepo exists, sync skills already in it
  if [[ -d "$MONOREPO_DIR" ]]; then
    find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
      ! -name '.git' ! -name '.github' ! -name '.*' \
      -exec basename {} \; 2>/dev/null | sort
    return
  fi

  # Fallback: default set
  echo "conversation-search"
  echo "skill-authoring"
  echo "skill-publishing"
}

SKILLS_TO_SYNC=$(discover_skills)
SKILL_COUNT=$(echo "$SKILLS_TO_SYNC" | wc -l | tr -d ' ')

echo "Skills to sync ($SKILL_COUNT):"
echo "$SKILLS_TO_SYNC" | sed 's/^/  - /'
echo ""

# --- Helper: write or report ---
write_file() {
  local filepath="$1"
  local content="$2"
  local label="$3"
  local overwrite="${4:-false}"

  if [[ -f "$filepath" ]] && [[ "$overwrite" != "true" ]]; then
    echo "  SKIP    $label (already exists)"
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$filepath" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD CREATE  $label"
    fi
  else
    mkdir -p "$(dirname "$filepath")"
    echo "$content" > "$filepath"
    if [[ -f "$filepath" ]]; then
      echo "  SYNCED  $label"
    else
      echo "  CREATED $label"
    fi
  fi
}

copy_file() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -f "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    if [[ -f "$dst" ]]; then
      echo "  WOULD UPDATE  $label"
    else
      echo "  WOULD COPY    $label"
    fi
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  SYNCED  $label"
  fi
}

copy_dir() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -d "$src" ]]; then
    return
  fi

  if $DRY_RUN; then
    local count
    count=$(find "$src" -type f | wc -l | tr -d ' ')
    echo "  WOULD COPY    $label ($count files)"
  else
    mkdir -p "$dst"
    # Copy contents, excluding .git and .claude
    rsync -a --delete --exclude='.git' --exclude='.claude' --exclude='.DS_Store' "$src/" "$dst/"
    echo "  SYNCED  $label"
  fi
}

# --- Sync each skill ---
CATALOG_ROWS=""

for SKILL_NAME in $SKILLS_TO_SYNC; do
  SKILL_SRC="$SKILLS_HOME/$SKILL_NAME"
  SKILL_DST="$MONOREPO_DIR/$SKILL_NAME"
  SKILL_MD="$SKILL_SRC/SKILL.md"

  echo "--- $SKILL_NAME ---"

  if [[ ! -f "$SKILL_MD" ]]; then
    echo "  ERROR: $SKILL_MD not found, skipping"
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

  # Check if individual repo exists
  INDIVIDUAL_REPO_URL=""
  if gh repo view "$GITHUB_USER/$SKILL_NAME" --json url --jq '.url' >/dev/null 2>&1; then
    INDIVIDUAL_REPO_URL="https://github.com/$GITHUB_USER/$SKILL_NAME"
  fi

  # Build catalog row
  REPO_LINK=""
  if [[ -n "$INDIVIDUAL_REPO_URL" ]]; then
    REPO_LINK="[repo]($INDIVIDUAL_REPO_URL)"
  else
    REPO_LINK="—"
  fi
  CATALOG_ROWS="${CATALOG_ROWS}| [$SKILL_NAME](./$SKILL_NAME/) | $VERSION | $SHORT | $REPO_LINK |
"

  # Copy SKILL.md
  copy_file "$SKILL_MD" "$SKILL_DST/SKILL.md" "$SKILL_NAME/SKILL.md"

  # Copy scripts/
  if [[ -d "$SKILL_SRC/scripts" ]]; then
    copy_dir "$SKILL_SRC/scripts" "$SKILL_DST/scripts" "$SKILL_NAME/scripts/"
    # Preserve execute permissions
    if ! $DRY_RUN; then
      find "$SKILL_DST/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
    fi
  fi

  # Copy references/
  if [[ -d "$SKILL_SRC/references" ]]; then
    copy_dir "$SKILL_SRC/references" "$SKILL_DST/references" "$SKILL_NAME/references/"
  fi

  # Copy CHANGELOG.md if it exists
  copy_file "$SKILL_SRC/CHANGELOG.md" "$SKILL_DST/CHANGELOG.md" "$SKILL_NAME/CHANGELOG.md"

  # Copy LICENSE if it exists
  copy_file "$SKILL_SRC/LICENSE" "$SKILL_DST/LICENSE" "$SKILL_NAME/LICENSE"

  # Generate per-skill README.md (always overwrite — it's auto-generated)
  SKILL_README="# $NAME

$SHORT

## Installation

### From this monorepo

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/$SKILL_NAME ~/.claude/skills/$SKILL_NAME
rm -rf /tmp/claude-code-skills
\`\`\`

### Sparse checkout (minimal download)

\`\`\`bash
git clone --filter=blob:none --sparse https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
cd /tmp/ccs && git sparse-checkout set $SKILL_NAME
cp -r $SKILL_NAME ~/.claude/skills/$SKILL_NAME
rm -rf /tmp/ccs
\`\`\`"

  # Add individual repo install if it exists
  if [[ -n "$INDIVIDUAL_REPO_URL" ]]; then
    SKILL_README="$SKILL_README

### From individual repo

\`\`\`bash
git clone $INDIVIDUAL_REPO_URL.git ~/.claude/skills/$SKILL_NAME
\`\`\`"
  fi

  SKILL_README="$SKILL_README

## Updating

\`\`\`bash
# If installed from monorepo, re-copy after pulling
cd /path/to/claude-code-skills && git pull
cp -r $SKILL_NAME ~/.claude/skills/$SKILL_NAME

# If installed from individual repo
git -C ~/.claude/skills/$SKILL_NAME pull
\`\`\`

## What It Does

$SHORT

## Compatibility

This skill follows the **Agent Skills** standard — a \`SKILL.md\` file with YAML frontmatter. Recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)"

  write_file "$SKILL_DST/README.md" "$SKILL_README" "$SKILL_NAME/README.md" "true"

  echo ""
done

# --- Generate root README ---
echo "--- Root files ---"

# Build catalog table
CATALOG_TABLE="| Skill | Version | Description | Individual Repo |
|-------|---------|-------------|-----------------|
$CATALOG_ROWS"

# Read template and replace placeholders
if [[ -f "$TEMPLATE_DIR/monorepo-readme-template.md" ]]; then
  # Extract everything after the --- separator (skip the template header)
  ROOT_README=$(sed '1,/^---$/d' "$TEMPLATE_DIR/monorepo-readme-template.md")
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{GITHUB_USER}}|$GITHUB_USER|g")
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{SKILL_COUNT}}|$SKILL_COUNT|g")
  ROOT_README=$(echo "$ROOT_README" | sed "s|{{LAST_UPDATED}}|$TODAY|g")
  # Replace catalog table placeholder (multi-line, use a temp file)
  TMPFILE=$(mktemp)
  echo "$ROOT_README" | while IFS= read -r line; do
    if [[ "$line" == *"{{SKILL_CATALOG_TABLE}}"* ]]; then
      echo "$CATALOG_TABLE"
    else
      echo "$line"
    fi
  done > "$TMPFILE"
  ROOT_README=$(cat "$TMPFILE")
  rm -f "$TMPFILE"
else
  echo "  Warning: monorepo-readme-template.md not found, generating minimal README"
  ROOT_README="# Claude Code Skills

A curated collection of $SKILL_COUNT reusable Agent Skills.

## Skills

$CATALOG_TABLE

## License

MIT

---
*Last synced: $TODAY*"
fi

write_file "$MONOREPO_DIR/README.md" "$ROOT_README" "README.md" "true"

# --- Generate root CHANGELOG.md ---
# Aggregates the latest version entry from each skill's CHANGELOG
CHANGELOG_HEADER="# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own CHANGELOG.md within its directory.
"

# Build per-skill changelog entries by extracting latest version block
CHANGELOG_SKILLS=""
for SKILL_NAME in $SKILLS_TO_SYNC; do
  SKILL_CL="$SKILLS_HOME/$SKILL_NAME/CHANGELOG.md"
  if [[ -f "$SKILL_CL" ]]; then
    # Extract the first version block: from "## [" to the next "## [" or EOF
    LATEST_ENTRY=$(awk '/^## \[/{if(found) exit; found=1} found{print}' "$SKILL_CL")
    if [[ -n "$LATEST_ENTRY" ]]; then
      CHANGELOG_SKILLS="${CHANGELOG_SKILLS}
### $SKILL_NAME

$LATEST_ENTRY
"
    fi
  fi
done

# Check for existing sync log entries and prepend new one
SYNC_ENTRY="## [$TODAY] — Monorepo sync

Synced $SKILL_COUNT skills from local source.
$CHANGELOG_SKILLS"

# If CHANGELOG.md exists, preserve previous entries (everything after first sync entry)
EXISTING_ENTRIES=""
if [[ -f "$MONOREPO_DIR/CHANGELOG.md" ]]; then
  # Extract everything after the header (skip lines until first "## [")
  EXISTING_ENTRIES=$(awk '/^## \[/{found=1} found{print}' "$MONOREPO_DIR/CHANGELOG.md")
  # Remove the latest sync entry if it's from today (avoid duplicates)
  if echo "$EXISTING_ENTRIES" | head -1 | grep -q "## \[$TODAY\]"; then
    EXISTING_ENTRIES=$(echo "$EXISTING_ENTRIES" | awk 'BEGIN{skip=1} /^## \[/{if(skip){skip=0; next}} !skip{print}')
    # Re-find the next entry start
    EXISTING_ENTRIES=$(echo "$EXISTING_ENTRIES" | awk '/^## \[/{found=1} found{print}')
  fi
fi

ROOT_CHANGELOG="${CHANGELOG_HEADER}${SYNC_ENTRY}"
if [[ -n "$EXISTING_ENTRIES" ]]; then
  ROOT_CHANGELOG="${ROOT_CHANGELOG}

${EXISTING_ENTRIES}"
fi

write_file "$MONOREPO_DIR/CHANGELOG.md" "$ROOT_CHANGELOG" "CHANGELOG.md" "true"

# --- .gitignore ---
GITIGNORE=".DS_Store
*.swp
*~
.claude/"

write_file "$MONOREPO_DIR/.gitignore" "$GITIGNORE" ".gitignore"

# --- LICENSE ---
LICENSE_CONTENT="MIT License

Copyright (c) $YEAR $AUTHOR

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."

write_file "$MONOREPO_DIR/LICENSE" "$LICENSE_CONTENT" "LICENSE"

echo ""

# --- Init mode: git init + create repo ---
if $INIT_MODE && ! $DRY_RUN; then
  echo "Initializing git repository..."
  cd "$MONOREPO_DIR"
  git init
  git add -A
  git commit -m "Initial commit: $SKILL_COUNT skills synced from local source"

  echo ""
  echo "Creating GitHub repository..."
  gh repo create claude-code-skills --public \
    --description "A curated collection of reusable Agent Skills for Claude Code, Cursor, Codex CLI, and Gemini CLI" \
    --source . --push

  echo ""
  echo "Monorepo initialized and pushed to GitHub."
  echo "URL: https://github.com/$GITHUB_USER/claude-code-skills"
elif $INIT_MODE && $DRY_RUN; then
  echo "WOULD: git init, commit, and create GitHub repo 'claude-code-skills'"
fi

# --- Summary ---
echo ""
if $DRY_RUN; then
  echo "Dry run complete. No files were written."
else
  echo "Sync complete. $SKILL_COUNT skills synced to $MONOREPO_DIR"
  if ! $INIT_MODE; then
    echo ""
    echo "Next steps:"
    echo "  cd $MONOREPO_DIR"
    echo "  git add -A && git diff --cached --stat"
    echo "  git commit -m \"Sync skills ($TODAY)\""
    echo "  git push"
  fi
fi
