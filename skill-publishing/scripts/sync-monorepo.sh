#!/usr/bin/env bash
# sync-monorepo.sh — Sync skills and plugins from ~/.claude/skills/ into a monorepo directory
# Generates root README with catalog table, plugin section, and per-skill READMEs.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/references"
SKILLS_HOME="${SKILLS_HOME:-$HOME/.claude/skills}"
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)

# Load shared library
source "$SCRIPT_DIR/_lib.sh"

# Defaults
DRY_RUN=false
INIT_MODE=false
GITHUB_USER=""
SKILLS_LIST=""
ADD_SKILL=""
ADD_PLUGIN=""
MONOREPO_DIR=""
AUTHOR="Abhishek"

usage() {
  cat <<'EOF'
Usage: sync-monorepo.sh [options] <monorepo-dir>

Syncs skills and plugins from ~/.claude/skills/ into a monorepo directory with a
generated root README containing a catalog table and plugin section.

Options:
  --dry-run              Preview changes without writing
  --skills <list>        Comma-separated skill names (default: all in monorepo)
  --add <skill-name>     Add a new skill to the monorepo
  --add-plugin <name>    Add a plugin from ./build/<name>/ to plugins/
  --github-user NAME     GitHub username (default: auto-detect via gh api)
  --author NAME          Name for LICENSE copyright (default: Abhishek)
  --init                 Initialize monorepo (create repo, first commit)
  -h, --help             Show this help

Examples:
  sync-monorepo.sh --init ~/dev/claude-code-skills
  sync-monorepo.sh ~/dev/claude-code-skills
  sync-monorepo.sh --add my-new-skill ~/dev/claude-code-skills
  sync-monorepo.sh --add-plugin git-flow ~/dev/claude-code-skills
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
    --add-plugin)   ADD_PLUGIN="$2"; shift 2 ;;
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

# --- Resolve GitHub user (via shared _lib.sh) ---
resolve_github_user

echo "GitHub user: $GITHUB_USER"
echo "Monorepo:    $MONOREPO_DIR"
echo "Source:      $SKILLS_HOME"
echo ""

# extract_field, extract_version, short_desc from _lib.sh

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
    # Get existing skill dirs in monorepo (exclude plugins/, scripts/, .git, .github)
    local existing=""
    if [[ -d "$MONOREPO_DIR" ]]; then
      existing=$(find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
        ! -name '.git' ! -name '.github' ! -name '.*' \
        ! -name 'plugins' ! -name 'scripts' \
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

  # If monorepo exists, sync skills already in it (exclude plugins/, scripts/, .git, .github)
  if [[ -d "$MONOREPO_DIR" ]]; then
    find "$MONOREPO_DIR" -maxdepth 1 -mindepth 1 -type d \
      ! -name '.git' ! -name '.github' ! -name '.*' \
      ! -name 'plugins' ! -name 'scripts' \
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

# write_file, copy_file, copy_dir from _lib.sh

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

  # Per-skill README.md: copy local if it exists, otherwise generate
  if [[ -f "$SKILL_SRC/README.md" ]]; then
    # Use the skill's own README (preserves fork context, custom sections, etc.)
    copy_file "$SKILL_SRC/README.md" "$SKILL_DST/README.md" "$SKILL_NAME/README.md"
  else
    # Generate a default README with monorepo install instructions
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
  fi

  echo ""
done

# --- Discover and sync plugins ---
discover_plugins() {
  # Scan $MONOREPO_DIR/plugins/ for directories with .claude-plugin/plugin.json
  if [[ -d "$MONOREPO_DIR/plugins" ]]; then
    find "$MONOREPO_DIR/plugins" -maxdepth 1 -mindepth 1 -type d \
      -exec basename {} \; 2>/dev/null | sort
  fi
}

# Add new plugin from build directory if --add-plugin specified
if [[ -n "$ADD_PLUGIN" ]]; then
  PLUGIN_BUILD="./build/$ADD_PLUGIN"
  if [[ ! -d "$PLUGIN_BUILD" ]]; then
    echo "Error: plugin build directory not found: $PLUGIN_BUILD" >&2
    echo "Run: prepare-plugin.sh <manifest-file> first" >&2
    exit 1
  fi
  if [[ ! -f "$PLUGIN_BUILD/.claude-plugin/plugin.json" ]]; then
    echo "Error: $PLUGIN_BUILD is not a valid plugin (missing .claude-plugin/plugin.json)" >&2
    exit 1
  fi

  PLUGIN_DST="$MONOREPO_DIR/plugins/$ADD_PLUGIN"
  echo "--- Plugin: $ADD_PLUGIN ---"

  if $DRY_RUN; then
    echo "  WOULD COPY  plugins/$ADD_PLUGIN/"
  else
    # Preserve hand-written files that rsync --delete would overwrite with templates
    # Uses temp files instead of associative arrays (bash 3.2 compat)
    PRESERVE_TMP=$(mktemp -d)
    PRESERVED_LIST=""
    for pfile in README.md CHANGELOG.md; do
      if [[ -f "$PLUGIN_DST/$pfile" ]]; then
        cp "$PLUGIN_DST/$pfile" "$PRESERVE_TMP/$pfile"
      fi
    done

    mkdir -p "$PLUGIN_DST"
    rsync -a --delete --exclude='.DS_Store' "$PLUGIN_BUILD/" "$PLUGIN_DST/"

    # Restore preserved files (overwrite auto-generated templates)
    for pfile in README.md CHANGELOG.md; do
      if [[ -f "$PRESERVE_TMP/$pfile" ]]; then
        cp "$PRESERVE_TMP/$pfile" "$PLUGIN_DST/$pfile"
        PRESERVED_LIST="${PRESERVED_LIST:+$PRESERVED_LIST, }$pfile"
      fi
    done
    rm -rf "$PRESERVE_TMP"

    if [[ -n "$PRESERVED_LIST" ]]; then
      echo "  SYNCED  plugins/$ADD_PLUGIN/ ($PRESERVED_LIST preserved)"
    else
      echo "  SYNCED  plugins/$ADD_PLUGIN/"
    fi

    # Preserve execute permissions on scripts
    find "$PLUGIN_DST" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
  fi
  echo ""
fi

# Build plugin catalog rows for README
PLUGINS_TO_LIST=$(discover_plugins)
PLUGIN_COUNT=0
PLUGIN_CATALOG_ROWS=""

if [[ -n "$PLUGINS_TO_LIST" ]]; then
  for PLUGIN_NAME in $PLUGINS_TO_LIST; do
    PLUGIN_DIR="$MONOREPO_DIR/plugins/$PLUGIN_NAME"
    PLUGIN_JSON="$PLUGIN_DIR/.claude-plugin/plugin.json"
    if [[ -f "$PLUGIN_JSON" ]]; then
      P_VERSION=$(jq -r '.version // "?"' "$PLUGIN_JSON")
      P_DESC=$(jq -r '.description // ""' "$PLUGIN_JSON")
      # Count skills and commands in the plugin
      P_SKILLS=0
      P_CMDS=0
      if [[ -d "$PLUGIN_DIR/skills" ]]; then
        P_SKILLS=$(find "$PLUGIN_DIR/skills" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
      fi
      if [[ -d "$PLUGIN_DIR/commands" ]]; then
        P_CMDS=$(find "$PLUGIN_DIR/commands" -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
      fi
      PLUGIN_CATALOG_ROWS="${PLUGIN_CATALOG_ROWS}| [$PLUGIN_NAME](./plugins/$PLUGIN_NAME/) | $P_VERSION | $P_SKILLS | $P_CMDS | $P_DESC |
"
      PLUGIN_COUNT=$((PLUGIN_COUNT + 1))
    fi
  done
fi

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
  # Build install-all commands (one cp -r per skill)
  INSTALL_ALL_CMDS=""
  for SKILL_NAME in $SKILLS_TO_SYNC; do
    INSTALL_ALL_CMDS="${INSTALL_ALL_CMDS}cp -r /tmp/claude-code-skills/$SKILL_NAME ~/.claude/skills/$SKILL_NAME
"
  done

  # Build plugin section (only if plugins exist)
  PLUGIN_SECTION=""
  if [[ $PLUGIN_COUNT -gt 0 ]]; then
    PLUGIN_TABLE="| Plugin | Version | Skills | Commands | Description |
|--------|---------|--------|----------|-------------|
$PLUGIN_CATALOG_ROWS"

    PLUGIN_SECTION="## Plugins

Plugins bundle skills, commands, agents, and hooks into a single installable package.

$PLUGIN_TABLE

### Install via Claude Code (Recommended)

Add this repo as a plugin marketplace, then install individual plugins:

\`\`\`shell
# Add the marketplace (one-time setup)
/plugin marketplace add $GITHUB_USER/claude-code-skills

# Install a plugin
/plugin install PLUGIN_NAME@claude-code-skills
\`\`\`

To browse all available plugins interactively, run \`/plugin\` and go to the **Discover** tab.

### Install via Script

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`

### Uninstall a Plugin

\`\`\`bash
# Via Claude Code
/plugin uninstall PLUGIN_NAME@claude-code-skills

# Via script
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`"
  fi

  # Replace multi-line placeholders (catalog table, install-all commands, plugin section)
  TMPFILE=$(mktemp)
  echo "$ROOT_README" | while IFS= read -r line; do
    if [[ "$line" == *"{{SKILL_CATALOG_TABLE}}"* ]]; then
      echo "$CATALOG_TABLE"
    elif [[ "$line" == *"{{SKILL_INSTALL_ALL_COMMANDS}}"* ]]; then
      printf "%s" "$INSTALL_ALL_CMDS"
    elif [[ "$line" == *"{{PLUGIN_SECTION}}"* ]]; then
      if [[ -n "$PLUGIN_SECTION" ]]; then
        echo "$PLUGIN_SECTION"
      fi
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

# --- Update root CHANGELOG.md (audit log style) ---
# The root CHANGELOG tracks monorepo-level events only.
# Per-skill change details live in <skill>/CHANGELOG.md.
#
# Strategy: prepend a new sync entry to the existing file.
# If today already has a "Monorepo sync" entry, replace it (idempotent).

CHANGELOG_HEADER="# Changelog

All notable changes to the **claude-code-skills** monorepo are documented here.
Each skill also maintains its own \`CHANGELOG.md\` within its directory.

Format: Monorepo-level events only. For per-skill change details, see \`<skill>/CHANGELOG.md\`.
"

# Build a compact skill inventory: name + version
SKILL_INVENTORY=""
for SKILL_NAME in $SKILLS_TO_SYNC; do
  SKILL_MD="$SKILLS_HOME/$SKILL_NAME/SKILL.md"
  if [[ -f "$SKILL_MD" ]]; then
    VERSION=$(extract_version "$SKILL_MD")
    SHORT_DESC=$(extract_field "$SKILL_MD" "description" | sed 's/\. Use when:.*//')
    SKILL_INVENTORY="${SKILL_INVENTORY}
- \`$SKILL_NAME\` v${VERSION:-?.?.?} — $SHORT_DESC"
  fi
done

SYNC_ENTRY="## [$TODAY] — Monorepo sync

Synced $SKILL_COUNT skills from local source.
$SKILL_INVENTORY
"

# Preserve existing entries, replacing today's "Monorepo sync" if present.
# If the top entry is a versioned release (from release-monorepo.sh), keep it.
EXISTING_ENTRIES=""
SKIP_SYNC_ENTRY=false
if [[ -f "$MONOREPO_DIR/CHANGELOG.md" ]]; then
  # Extract all ## entries
  ALL_ENTRIES=$(awk '/^## \[/{found=1} found{print}' "$MONOREPO_DIR/CHANGELOG.md")
  FIRST_ENTRY=$(echo "$ALL_ENTRIES" | head -1)

  if echo "$FIRST_ENTRY" | grep -q "## \[$TODAY\] — Monorepo sync"; then
    # Today's sync entry exists — replace it with fresh one
    EXISTING_ENTRIES=$(echo "$ALL_ENTRIES" | awk '/^## \[/{count++} count>=2{print}')
  elif echo "$FIRST_ENTRY" | grep -qE "## \[[0-9]+\.[0-9]+\.[0-9]+\] - $TODAY"; then
    # Today's versioned release exists (from release-monorepo.sh) — don't clobber it
    EXISTING_ENTRIES="$ALL_ENTRIES"
    SKIP_SYNC_ENTRY=true
  else
    EXISTING_ENTRIES="$ALL_ENTRIES"
  fi
fi

if $SKIP_SYNC_ENTRY; then
  ROOT_CHANGELOG="${CHANGELOG_HEADER}
${EXISTING_ENTRIES}"
else
  ROOT_CHANGELOG="${CHANGELOG_HEADER}${SYNC_ENTRY}"
  if [[ -n "$EXISTING_ENTRIES" ]]; then
    ROOT_CHANGELOG="${ROOT_CHANGELOG}
${EXISTING_ENTRIES}"
  fi
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

# --- CONTRIBUTING.md (monorepo variant from template) ---
if [[ -f "$TEMPLATE_DIR/CONTRIBUTING-template.md" ]]; then
  # Write scope content to temp file for awk multiline replacement
  SCOPE_TMP=$(mktemp)
  cat > "$SCOPE_TMP" <<'SCOPE_EOF'
### Adding a new skill

1. Create a new directory at the repo root (e.g., `my-skill/`)
2. Add a `SKILL.md` with valid YAML frontmatter
3. Optionally add `scripts/` and `references/` directories

### Improving an existing skill

- Edit the skill's `SKILL.md` to improve instructions or metadata
- Add or improve scripts in the skill's `scripts/` directory
- Add or update reference material in the skill's `references/` directory
- Fix bugs or improve documentation
SCOPE_EOF

  # Single-line replacements with sed, multiline with awk
  CONTRIBUTING_TMP=$(mktemp)
  sed "s|{{REPO_NAME}}|claude-code-skills|g; s|{{GITHUB_USER}}|$GITHUB_USER|g; s|{{VALIDATE_COMMAND}}|scripts/validate-skill.sh <skill-directory>|g" \
    "$TEMPLATE_DIR/CONTRIBUTING-template.md" > "$CONTRIBUTING_TMP"
  # Replace {{CONTRIBUTING_SCOPE}} line with scope file contents
  awk -v scopefile="$SCOPE_TMP" '{
    if ($0 ~ /\{\{CONTRIBUTING_SCOPE\}\}/) {
      while ((getline line < scopefile) > 0) print line
      close(scopefile)
    } else print
  }' "$CONTRIBUTING_TMP" > "$CONTRIBUTING_TMP.out"
  mv "$CONTRIBUTING_TMP.out" "$CONTRIBUTING_TMP"

  CONTRIBUTING_CONTENT=$(cat "$CONTRIBUTING_TMP")
  rm -f "$SCOPE_TMP" "$CONTRIBUTING_TMP"
  write_file "$MONOREPO_DIR/CONTRIBUTING.md" "$CONTRIBUTING_CONTENT" "CONTRIBUTING.md" "true"
fi

# --- .github/PULL_REQUEST_TEMPLATE.md ---
if [[ -f "$TEMPLATE_DIR/PR_TEMPLATE-template.md" ]]; then
  PR_TEMPLATE_CONTENT=$(cat "$TEMPLATE_DIR/PR_TEMPLATE-template.md")
  if $DRY_RUN; then
    echo "  WOULD UPDATE  .github/PULL_REQUEST_TEMPLATE.md"
  else
    mkdir -p "$MONOREPO_DIR/.github"
    echo "$PR_TEMPLATE_CONTENT" > "$MONOREPO_DIR/.github/PULL_REQUEST_TEMPLATE.md"
    echo "  SYNCED  .github/PULL_REQUEST_TEMPLATE.md"
  fi
fi

# --- .github/workflows/validate-skill.yml (monorepo variant) ---
if [[ -f "$TEMPLATE_DIR/workflow-monorepo.yml" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  .github/workflows/validate-skill.yml"
  else
    mkdir -p "$MONOREPO_DIR/.github/workflows"
    cp "$TEMPLATE_DIR/workflow-monorepo.yml" "$MONOREPO_DIR/.github/workflows/validate-skill.yml"
    echo "  SYNCED  .github/workflows/validate-skill.yml"
  fi
fi

# --- scripts/validate-skill.sh (copy from skill-publishing) ---
VALIDATE_SRC="$SCRIPT_DIR/validate-skill.sh"
if [[ -f "$VALIDATE_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/validate-skill.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$VALIDATE_SRC" "$MONOREPO_DIR/scripts/validate-skill.sh"
    chmod +x "$MONOREPO_DIR/scripts/validate-skill.sh"
    echo "  SYNCED  scripts/validate-skill.sh"
  fi
fi

# --- scripts/validate-plugin.sh (copy from skill-publishing) ---
VALIDATE_PLUGIN_SRC="$SCRIPT_DIR/validate-plugin.sh"
if [[ -f "$VALIDATE_PLUGIN_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/validate-plugin.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$VALIDATE_PLUGIN_SRC" "$MONOREPO_DIR/scripts/validate-plugin.sh"
    chmod +x "$MONOREPO_DIR/scripts/validate-plugin.sh"
    echo "  SYNCED  scripts/validate-plugin.sh"
  fi
fi

# --- scripts/install-plugin.sh (copy from skill-publishing) ---
INSTALL_PLUGIN_SRC="$SCRIPT_DIR/install-plugin.sh"
if [[ -f "$INSTALL_PLUGIN_SRC" ]]; then
  if $DRY_RUN; then
    echo "  WOULD UPDATE  scripts/install-plugin.sh"
  else
    mkdir -p "$MONOREPO_DIR/scripts"
    cp "$INSTALL_PLUGIN_SRC" "$MONOREPO_DIR/scripts/install-plugin.sh"
    chmod +x "$MONOREPO_DIR/scripts/install-plugin.sh"
    echo "  SYNCED  scripts/install-plugin.sh"
  fi
fi

# --- .claude-plugin/marketplace.json (auto-generated) ---
# Build marketplace.json so the monorepo can be added as a plugin marketplace
# via: /plugin marketplace add GITHUB_USER/claude-code-skills
if [[ $PLUGIN_COUNT -gt 0 ]]; then
  MARKETPLACE_PLUGINS=""
  while IFS= read -r pjson; do
    pdir=$(dirname "$(dirname "$pjson")")
    pname=$(jq -r '.name // ""' "$pjson" 2>/dev/null)
    pdesc=$(jq -r '.description // ""' "$pjson" 2>/dev/null)
    pver=$(jq -r '.version // ""' "$pjson" 2>/dev/null)
    if [[ -n "$pname" ]]; then
      if [[ -n "$MARKETPLACE_PLUGINS" ]]; then
        MARKETPLACE_PLUGINS="$MARKETPLACE_PLUGINS,"
      fi
      # Use relative path from monorepo root
      rel_path="./plugins/$pname"
      MARKETPLACE_PLUGINS="$MARKETPLACE_PLUGINS
    {
      \"name\": \"$pname\",
      \"source\": \"$rel_path\",
      \"description\": \"$pdesc\",
      \"version\": \"$pver\"
    }"
    fi
  done < <(find "$MONOREPO_DIR/plugins" -maxdepth 3 -name "plugin.json" -path "*/.claude-plugin/*" 2>/dev/null | sort)

  MARKETPLACE_JSON="{
  \"name\": \"claude-code-skills\",
  \"owner\": {
    \"name\": \"$AUTHOR\"
  },
  \"metadata\": {
    \"description\": \"Reusable Agent Skills and Plugins for Claude Code\",
    \"version\": \"$(date +%Y.%m.%d)\"
  },
  \"plugins\": [$MARKETPLACE_PLUGINS
  ]
}"

  if $DRY_RUN; then
    echo "  WOULD UPDATE  .claude-plugin/marketplace.json"
  else
    mkdir -p "$MONOREPO_DIR/.claude-plugin"
    echo "$MARKETPLACE_JSON" > "$MONOREPO_DIR/.claude-plugin/marketplace.json"
    echo "  SYNCED  .claude-plugin/marketplace.json"
  fi
fi

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
