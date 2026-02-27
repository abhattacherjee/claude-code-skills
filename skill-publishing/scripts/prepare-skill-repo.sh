#!/usr/bin/env bash
# prepare-skill-repo.sh — Prepare a Claude Code skill directory for GitHub sharing
# Creates .gitignore, LICENSE, CHANGELOG.md, and README.md from SKILL.md metadata.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")/references"
YEAR=$(date +%Y)
TODAY=$(date +%Y-%m-%d)

# Load shared library
source "$SCRIPT_DIR/_lib.sh"

# Defaults
DRY_RUN=false
GITHUB_USER="USERNAME"
AUTHOR="Abhishek"

usage() {
  cat <<'EOF'
Usage: prepare-skill-repo.sh [options] <skill-directory>

Prepares a Claude Code skill directory for GitHub sharing by creating:
  .gitignore, LICENSE (MIT), CHANGELOG.md, README.md

Options:
  --dry-run           Show what would be created without writing files
  --github-user NAME  GitHub username for README URLs (default: USERNAME placeholder)
  --author NAME       Name for LICENSE copyright (default: Abhishek)
  -h, --help          Show this help

Examples:
  prepare-skill-repo.sh ~/.claude/skills/my-skill
  prepare-skill-repo.sh --dry-run ~/.claude/skills/my-skill
  prepare-skill-repo.sh --github-user abhattacherjee ~/.claude/skills/my-skill
EOF
  exit 0
}

# --- Parse arguments ---
SKILL_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=true; shift ;;
    --github-user) GITHUB_USER="$2"; shift 2 ;;
    --author)     AUTHOR="$2"; shift 2 ;;
    -h|--help)    usage ;;
    -*)           echo "Unknown option: $1" >&2; exit 1 ;;
    *)            SKILL_DIR="$1"; shift ;;
  esac
done

if [[ -z "$SKILL_DIR" ]]; then
  echo "Error: skill directory is required" >&2
  echo "Usage: prepare-skill-repo.sh [options] <skill-directory>" >&2
  exit 1
fi

SKILL_DIR="$(cd "$SKILL_DIR" && pwd)"

# --- Validate SKILL.md exists ---
SKILL_MD="$SKILL_DIR/SKILL.md"
if [[ ! -f "$SKILL_MD" ]]; then
  echo "Error: $SKILL_MD not found" >&2
  exit 1
fi

# --- Extract frontmatter fields (via shared _lib.sh) ---
SKILL_NAME=$(extract_field "$SKILL_MD" "name")
DESCRIPTION=$(extract_field "$SKILL_MD" "description")
VERSION=$(extract_version "$SKILL_MD")

if [[ -z "$SKILL_NAME" ]]; then
  echo "Error: could not extract 'name' from SKILL.md frontmatter" >&2
  exit 1
fi

if [[ -z "$VERSION" ]]; then
  VERSION="1.0.0"
  echo "Warning: no version found in frontmatter, defaulting to 1.0.0"
fi

# Short description: first sentence (before "Use when:")
SHORT_DESC=$(short_desc "$DESCRIPTION")

echo "Skill:   $SKILL_NAME"
echo "Version: $VERSION"
echo "Desc:    $SHORT_DESC"
echo ""

# --- Build directory tree ---
DIRECTORY_TREE=$(cd "$SKILL_DIR" && find . -not -path './.git/*' -not -path './.git' -not -path './.claude/*' -not -path './.claude' -not -name '.DS_Store' | sort | sed 's|^./||' | while IFS= read -r path; do
  if [[ "$path" == "." ]]; then
    echo "${SKILL_NAME}/"
  else
    depth=$(echo "$path" | tr -cd '/' | wc -c | tr -d ' ')
    indent=""
    for ((i=0; i<depth; i++)); do indent="${indent}    "; done
    basename=$(basename "$path")
    if [[ -d "$SKILL_DIR/$path" ]]; then
      echo "${indent}├── ${basename}/"
    else
      echo "${indent}├── ${basename}"
    fi
  fi
done)

# --- Extract "What It Does" from SKILL.md body ---
# Use the first heading's content (after frontmatter title) as the description
WHAT_IT_DOES="$SHORT_DESC"

# write_file from _lib.sh (uses SKIP/WOULD CREATE/CREATED labels)

echo "Files:"

# --- 1. .gitignore ---
GITIGNORE_CONTENT=".DS_Store
*.swp
*~
.claude/"

write_file "$SKILL_DIR/.gitignore" "$GITIGNORE_CONTENT" ".gitignore"

# --- 2. LICENSE (MIT) ---
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

write_file "$SKILL_DIR/LICENSE" "$LICENSE_CONTENT" "LICENSE"

# --- 3. CHANGELOG.md ---
CHANGELOG_CONTENT="# Changelog

All notable changes to this project will be documented in this file.

## [$VERSION] - $TODAY

Initial public release.

### Included

- **SKILL.md** — $SHORT_DESC"

# Add scripts/ and references/ to changelog if they exist
if [[ -d "$SKILL_DIR/scripts" ]]; then
  SCRIPT_LIST=$(ls "$SKILL_DIR/scripts/" 2>/dev/null | head -5)
  if [[ -n "$SCRIPT_LIST" ]]; then
    CHANGELOG_CONTENT="$CHANGELOG_CONTENT
- **scripts/** — automation scripts:$(echo "$SCRIPT_LIST" | while read -r f; do echo "  - \`$f\`"; done)"
  fi
fi

if [[ -d "$SKILL_DIR/references" ]]; then
  REF_LIST=$(ls "$SKILL_DIR/references/" 2>/dev/null | head -5)
  if [[ -n "$REF_LIST" ]]; then
    CHANGELOG_CONTENT="$CHANGELOG_CONTENT
- **references/** — reference material:$(echo "$REF_LIST" | while read -r f; do echo "  - \`$f\`"; done)"
  fi
fi

write_file "$SKILL_DIR/CHANGELOG.md" "$CHANGELOG_CONTENT" "CHANGELOG.md"

# --- 4. README.md ---
README_CONTENT="# $SKILL_NAME

$SHORT_DESC

## Installation

### Individual repo (recommended)

Clone into your Claude Code skills directory:

**User-level** (available in all projects):

\`\`\`bash
# macOS / Linux
git clone https://github.com/$GITHUB_USER/$SKILL_NAME.git ~/.claude/skills/$SKILL_NAME

# Windows
git clone https://github.com/$GITHUB_USER/$SKILL_NAME.git %USERPROFILE%\\.claude\\skills\\$SKILL_NAME
\`\`\`

**Project-level** (available only in one project):

\`\`\`bash
git clone https://github.com/$GITHUB_USER/$SKILL_NAME.git .claude/skills/$SKILL_NAME
\`\`\`

### Via monorepo (all skills)

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/claude-code-skills
cp -r /tmp/claude-code-skills/$SKILL_NAME ~/.claude/skills/$SKILL_NAME
rm -rf /tmp/claude-code-skills
\`\`\`

## Updating

\`\`\`bash
git -C ~/.claude/skills/$SKILL_NAME pull
\`\`\`

## Uninstall

\`\`\`bash
rm -rf ~/.claude/skills/$SKILL_NAME
\`\`\`

## What It Does

$WHAT_IT_DOES

## Compatibility

This skill follows the **Agent Skills** standard — a \`SKILL.md\` file at the repo root with YAML frontmatter. This format is recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## Directory Structure

\`\`\`
$DIRECTORY_TREE
\`\`\`

## License

[MIT](LICENSE)"

write_file "$SKILL_DIR/README.md" "$README_CONTENT" "README.md"

# --- 5. CONTRIBUTING.md (from template) ---
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
  write_file "$SKILL_DIR/CONTRIBUTING.md" "$CONTRIBUTING_CONTENT" "CONTRIBUTING.md"
fi

# --- 6. .github/PULL_REQUEST_TEMPLATE.md (from template) ---
if [[ -f "$TEMPLATE_DIR/PR_TEMPLATE-template.md" ]]; then
  PR_TEMPLATE_CONTENT=$(cat "$TEMPLATE_DIR/PR_TEMPLATE-template.md")
  if $DRY_RUN; then
    echo "  WOULD CREATE  .github/PULL_REQUEST_TEMPLATE.md"
  elif [[ -f "$SKILL_DIR/.github/PULL_REQUEST_TEMPLATE.md" ]]; then
    echo "  SKIP  .github/PULL_REQUEST_TEMPLATE.md (already exists)"
  else
    mkdir -p "$SKILL_DIR/.github"
    echo "$PR_TEMPLATE_CONTENT" > "$SKILL_DIR/.github/PULL_REQUEST_TEMPLATE.md"
    echo "  CREATED  .github/PULL_REQUEST_TEMPLATE.md"
  fi
fi

# --- 7. .github/workflows/validate-skill.yml (individual repo variant) ---
if [[ -f "$TEMPLATE_DIR/workflow-individual.yml" ]]; then
  if $DRY_RUN; then
    echo "  WOULD CREATE  .github/workflows/validate-skill.yml"
  elif [[ -f "$SKILL_DIR/.github/workflows/validate-skill.yml" ]]; then
    echo "  SKIP  .github/workflows/validate-skill.yml (already exists)"
  else
    mkdir -p "$SKILL_DIR/.github/workflows"
    cp "$TEMPLATE_DIR/workflow-individual.yml" "$SKILL_DIR/.github/workflows/validate-skill.yml"
    echo "  CREATED  .github/workflows/validate-skill.yml"
  fi
fi

# --- 8. scripts/validate-skill.sh (copy from skill-publishing) ---
VALIDATE_SRC="$SCRIPT_DIR/validate-skill.sh"
if [[ -f "$VALIDATE_SRC" ]]; then
  if [[ -f "$SKILL_DIR/scripts/validate-skill.sh" ]]; then
    echo "  SKIP  scripts/validate-skill.sh (already exists)"
  elif $DRY_RUN; then
    echo "  WOULD CREATE  scripts/validate-skill.sh"
  else
    mkdir -p "$SKILL_DIR/scripts"
    cp "$VALIDATE_SRC" "$SKILL_DIR/scripts/validate-skill.sh"
    chmod +x "$SKILL_DIR/scripts/validate-skill.sh"
    echo "  CREATED  scripts/validate-skill.sh"
  fi
fi

echo ""
if $DRY_RUN; then
  echo "Dry run complete. No files were written."
else
  echo "Done. Next steps:"
  echo "  1. Review and customize the generated files"
  echo "  2. Add a 'See Also' section to SKILL.md with the GitHub URL"
  echo "  3. git init && git add . && git commit"
  echo "  4. gh repo create $SKILL_NAME --public --source . --push"
  echo "  5. git tag v$VERSION && git push origin v$VERSION"
fi
