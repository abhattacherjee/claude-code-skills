#!/usr/bin/env bash
# prepare-plugin.sh — Assemble a Claude Code plugin from a build manifest
# Reads a plugin-manifest.json and creates an installable plugin directory.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load shared library
source "$SCRIPT_DIR/_lib.sh"

# Defaults
DRY_RUN=false
OUTPUT_DIR=""
GITHUB_USER=""
AUTHOR="Abhishek"
YEAR=$(date +%Y)
TODAY=$(date +%Y-%m-%d)

usage() {
  cat <<'EOF'
Usage: prepare-plugin.sh [options] <manifest-file>

Assembles a Claude Code plugin from a build manifest (plugin-manifest.json).
Creates an installable plugin directory with .claude-plugin/plugin.json,
skills, commands, and scaffolding files.

Options:
  --dry-run              Preview what would be created without writing files
  --output-dir DIR       Output directory (default: ./build/<plugin-name>/)
  --github-user NAME     GitHub username for README URLs (default: auto-detect)
  --author NAME          Name for LICENSE copyright (default: Abhishek)
  -h, --help             Show this help

Manifest format (plugin-manifest.json):
  {
    "name": "my-plugin",
    "version": "1.0.0",
    "description": "Short description",
    "skills": [{ "name": "skill-name", "source": "~/.claude/skills/skill-name" }],
    "commands": [{ "name": "cmd-name", "source": "~/.claude/commands/cmd-name.md" }]
  }

Examples:
  prepare-plugin.sh ~/.claude/skills/git-flow/plugin-manifest.json
  prepare-plugin.sh --dry-run ~/.claude/skills/git-flow/plugin-manifest.json
  prepare-plugin.sh --output-dir /tmp/git-flow-plugin manifest.json
EOF
  exit 0
}

# --- Parse arguments ---
MANIFEST_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true; shift ;;
    --output-dir)   OUTPUT_DIR="$2"; shift 2 ;;
    --github-user)  GITHUB_USER="$2"; shift 2 ;;
    --author)       AUTHOR="$2"; shift 2 ;;
    -h|--help)      usage ;;
    -*)             echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)              MANIFEST_FILE="$1"; shift ;;
  esac
done

if [[ -z "$MANIFEST_FILE" ]]; then
  echo "Error: manifest file is required" >&2
  echo "Usage: prepare-plugin.sh [options] <manifest-file>" >&2
  exit 1
fi

# --- Check dependencies ---
if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not installed" >&2
  echo "Install: brew install jq (macOS) or apt install jq (Linux)" >&2
  exit 1
fi

# --- Read manifest ---
MANIFEST_FILE="$(resolve_tilde "$MANIFEST_FILE")"
if [[ ! -f "$MANIFEST_FILE" ]]; then
  echo "Error: manifest file not found: $MANIFEST_FILE" >&2
  exit 1
fi

PLUGIN_NAME=$(jq -r '.name // empty' "$MANIFEST_FILE")
PLUGIN_VERSION=$(jq -r '.version // empty' "$MANIFEST_FILE")
PLUGIN_DESC=$(jq -r '.description // empty' "$MANIFEST_FILE")
PLUGIN_AUTHOR=$(jq -r '.author // empty' "$MANIFEST_FILE")
PLUGIN_LICENSE=$(jq -r '.license // "MIT"' "$MANIFEST_FILE")

if [[ -z "$PLUGIN_NAME" ]]; then
  echo "Error: manifest missing required field 'name'" >&2
  exit 1
fi
if [[ -z "$PLUGIN_VERSION" ]]; then
  echo "Error: manifest missing required field 'version'" >&2
  exit 1
fi
if [[ -z "$PLUGIN_DESC" ]]; then
  echo "Error: manifest missing required field 'description'" >&2
  exit 1
fi

# Use manifest author if present, fall back to --author flag
if [[ -n "$PLUGIN_AUTHOR" ]]; then
  AUTHOR="$PLUGIN_AUTHOR"
fi

# Resolve GitHub user
if [[ -z "$GITHUB_USER" ]]; then
  GITHUB_USER=$(gh api user --jq '.login' 2>/dev/null || echo "USERNAME")
fi

# Set output directory
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="./build/$PLUGIN_NAME"
fi

SKILL_COUNT=$(jq '.skills | length' "$MANIFEST_FILE")
CMD_COUNT=$(jq '.commands | length' "$MANIFEST_FILE")
AGENT_COUNT=$(jq '.agents // [] | length' "$MANIFEST_FILE")
HOOK_COUNT=$(jq 'if .hooks then 1 else 0 end' "$MANIFEST_FILE")

echo "Plugin:     $PLUGIN_NAME v$PLUGIN_VERSION"
echo "Skills:     $SKILL_COUNT"
echo "Commands:   $CMD_COUNT"
echo "Output:     $OUTPUT_DIR"
echo "Dry run:    $DRY_RUN"
echo ""

# --- Create output directory ---
if ! $DRY_RUN; then
  rm -rf "$OUTPUT_DIR"
  mkdir -p "$OUTPUT_DIR"
fi

# --- 1. Generate .claude-plugin/plugin.json ---
echo "--- Plugin manifest ---"

PLUGIN_JSON=$(jq -n \
  --arg name "$PLUGIN_NAME" \
  --arg version "$PLUGIN_VERSION" \
  --arg description "$PLUGIN_DESC" \
  '{name: $name, version: $version, description: $description}')

if $DRY_RUN; then
  echo "  WOULD CREATE  .claude-plugin/plugin.json"
else
  mkdir -p "$OUTPUT_DIR/.claude-plugin"
  echo "$PLUGIN_JSON" > "$OUTPUT_DIR/.claude-plugin/plugin.json"
  echo "  CREATED  .claude-plugin/plugin.json"
fi

# --- 2. Copy skills ---
if [[ $SKILL_COUNT -gt 0 ]]; then
  echo ""
  echo "--- Skills ---"
  for i in $(seq 0 $((SKILL_COUNT - 1))); do
    SKILL_NAME_I=$(jq -r ".skills[$i].name" "$MANIFEST_FILE")
    SKILL_SRC=$(jq -r ".skills[$i].source" "$MANIFEST_FILE")
    SKILL_SRC=$(resolve_tilde "$SKILL_SRC")

    if [[ ! -d "$SKILL_SRC" ]]; then
      echo "  ERROR: skill source not found: $SKILL_SRC" >&2
      exit 1
    fi

    SKILL_DST="$OUTPUT_DIR/skills/$SKILL_NAME_I"

    if $DRY_RUN; then
      local_count=$(find "$SKILL_SRC" -type f ! -path '*/.git/*' ! -path '*/.claude/*' ! -name '.DS_Store' | wc -l | tr -d ' ')
      echo "  WOULD COPY  skills/$SKILL_NAME_I/ ($local_count files)"
    else
      mkdir -p "$SKILL_DST"
      rsync -a \
        --exclude='.git' --exclude='.claude' --exclude='.DS_Store' \
        --exclude='.github' --exclude='README.md' --exclude='CONTRIBUTING.md' \
        --exclude='LICENSE' --exclude='.gitignore' \
        --exclude='plugin-manifest.json' \
        "$SKILL_SRC/" "$SKILL_DST/"
      # Preserve execute permissions on scripts
      find "$SKILL_DST" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
      echo "  COPIED  skills/$SKILL_NAME_I/"
    fi
  done
fi

# --- 3. Copy commands ---
if [[ $CMD_COUNT -gt 0 ]]; then
  echo ""
  echo "--- Commands ---"
  for i in $(seq 0 $((CMD_COUNT - 1))); do
    CMD_NAME=$(jq -r ".commands[$i].name" "$MANIFEST_FILE")
    CMD_SRC=$(jq -r ".commands[$i].source" "$MANIFEST_FILE")
    CMD_SRC=$(resolve_tilde "$CMD_SRC")

    if [[ ! -f "$CMD_SRC" ]]; then
      echo "  ERROR: command source not found: $CMD_SRC" >&2
      exit 1
    fi

    if $DRY_RUN; then
      echo "  WOULD COPY  commands/$CMD_NAME.md"
    else
      mkdir -p "$OUTPUT_DIR/commands"
      cp "$CMD_SRC" "$OUTPUT_DIR/commands/$CMD_NAME.md"
      echo "  COPIED  commands/$CMD_NAME.md"
    fi
  done
fi

# --- 4. Copy agents (optional) ---
if [[ $AGENT_COUNT -gt 0 ]]; then
  echo ""
  echo "--- Agents ---"
  for i in $(seq 0 $((AGENT_COUNT - 1))); do
    AGENT_NAME=$(jq -r ".agents[$i].name" "$MANIFEST_FILE")
    AGENT_SRC=$(jq -r ".agents[$i].source" "$MANIFEST_FILE")
    AGENT_SRC=$(resolve_tilde "$AGENT_SRC")

    if [[ ! -f "$AGENT_SRC" ]]; then
      echo "  ERROR: agent source not found: $AGENT_SRC" >&2
      exit 1
    fi

    if $DRY_RUN; then
      echo "  WOULD COPY  agents/$AGENT_NAME.md"
    else
      mkdir -p "$OUTPUT_DIR/agents"
      cp "$AGENT_SRC" "$OUTPUT_DIR/agents/$AGENT_NAME.md"
      echo "  COPIED  agents/$AGENT_NAME.md"
    fi
  done
fi

# --- 5. Copy hooks (optional) ---
if [[ $HOOK_COUNT -gt 0 ]]; then
  echo ""
  echo "--- Hooks ---"
  HOOKS_SRC=$(jq -r '.hooks.source' "$MANIFEST_FILE")
  if [[ -n "$HOOKS_SRC" ]] && [[ "$HOOKS_SRC" != "null" ]]; then
    HOOKS_SRC=$(resolve_tilde "$HOOKS_SRC")
    if [[ -d "$HOOKS_SRC" ]]; then
      if $DRY_RUN; then
        echo "  WOULD COPY  hooks/"
      else
        mkdir -p "$OUTPUT_DIR/hooks"
        rsync -a --exclude='.DS_Store' "$HOOKS_SRC/" "$OUTPUT_DIR/hooks/"
        echo "  COPIED  hooks/"
      fi
    fi
  fi
fi

# --- 6. Generate scaffolding ---
echo ""
echo "--- Scaffolding ---"

# .gitignore
GITIGNORE_CONTENT=".DS_Store
*.swp
*~
.claude/"

write_file "$OUTPUT_DIR/.gitignore" "$GITIGNORE_CONTENT" ".gitignore"

# LICENSE
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

write_file "$OUTPUT_DIR/LICENSE" "$LICENSE_CONTENT" "LICENSE"

# CHANGELOG.md — copy from source skill if available, else generate template
# The first skill's directory is the canonical source for the plugin's changelog
FIRST_SKILL_SOURCE=$(jq -r '.skills[0].source' "$MANIFEST_FILE")
FIRST_SKILL_SOURCE=$(resolve_tilde "$FIRST_SKILL_SOURCE")
SOURCE_CHANGELOG="$FIRST_SKILL_SOURCE/CHANGELOG.md"

if [[ -f "$SOURCE_CHANGELOG" ]]; then
  copy_file "$SOURCE_CHANGELOG" "$OUTPUT_DIR/CHANGELOG.md" "CHANGELOG.md (from source skill)"
else
  CHANGELOG_CONTENT="# Changelog

## [$PLUGIN_VERSION] - $TODAY

Initial plugin release.

### Included

- **$SKILL_COUNT skill(s)**, **$CMD_COUNT command(s)**"

  # Add skill names
  for i in $(seq 0 $((SKILL_COUNT - 1))); do
    SNAME=$(jq -r ".skills[$i].name" "$MANIFEST_FILE")
    CHANGELOG_CONTENT="$CHANGELOG_CONTENT
- Skill: \`$SNAME\`"
  done

  # Add command names
  for i in $(seq 0 $((CMD_COUNT - 1))); do
    CNAME=$(jq -r ".commands[$i].name" "$MANIFEST_FILE")
    CHANGELOG_CONTENT="$CHANGELOG_CONTENT
- Command: \`/$CNAME\`"
  done

  write_file "$OUTPUT_DIR/CHANGELOG.md" "$CHANGELOG_CONTENT" "CHANGELOG.md"
fi

# README.md — enriched extraction from SKILL.md, commands, agents
# Primary skill provides What It Does, Key Features, Usage, See Also
PRIMARY_SKILL_SRC=$(jq -r '.skills[0].source' "$MANIFEST_FILE")
PRIMARY_SKILL_SRC=$(resolve_tilde "$PRIMARY_SKILL_SRC")
PRIMARY_SKILL_MD="$PRIMARY_SKILL_SRC/SKILL.md"

# --- Extract data from primary skill ---
FULL_DESC=""
USE_WHEN=""
KEY_FEATURES=""
USAGE_SECTION=""
SEE_ALSO=""
PREREQUISITES=""

if [[ -f "$PRIMARY_SKILL_MD" ]]; then
  FULL_DESC=$(extract_field "$PRIMARY_SKILL_MD" "description")

  # Extract "Use when:" bullets from description
  USE_WHEN_RAW=$(echo "$FULL_DESC" | sed -n 's/.*Use when: *//p')
  if [[ -n "$USE_WHEN_RAW" ]]; then
    USE_WHEN=$(echo "$USE_WHEN_RAW" | sed 's/([0-9]*) */\n/g' | \
      sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//' | sed 's/,$//' | \
      sed 's/^/- /')
  fi

  # Key Features from ## headings (filter out generic sections)
  HEADINGS=$(extract_headings "$PRIMARY_SKILL_MD" 12)
  if [[ -n "$HEADINGS" ]]; then
    KEY_FEATURES=""
    while IFS= read -r heading; do
      case "$heading" in
        "See Also"|"Notes"|"Prerequisites"|"Key Decisions"|"Quick Check"|"Quick Reference"|"") continue ;;
        *) KEY_FEATURES="${KEY_FEATURES}
- **${heading}**" ;;
      esac
    done <<< "$HEADINGS"
    # Trim leading newline
    KEY_FEATURES=$(echo "$KEY_FEATURES" | sed '/./,$!d')
  fi

  # Usage from Quick Check or Quick Reference section
  USAGE_SECTION=$(extract_section "$PRIMARY_SKILL_MD" "Quick Check")
  if [[ -z "$USAGE_SECTION" ]]; then
    USAGE_SECTION=$(extract_section "$PRIMARY_SKILL_MD" "Quick Reference")
  fi

  # Optional sections
  SEE_ALSO=$(extract_section "$PRIMARY_SKILL_MD" "See Also")
  PREREQUISITES=$(extract_section "$PRIMARY_SKILL_MD" "Prerequisites")
fi

# --- Build Contents lists with descriptions ---
SKILL_LIST=""
for i in $(seq 0 $((SKILL_COUNT - 1))); do
  SNAME=$(jq -r ".skills[$i].name" "$MANIFEST_FILE")
  SSRC=$(jq -r ".skills[$i].source" "$MANIFEST_FILE")
  SSRC=$(resolve_tilde "$SSRC")
  SDESC=$(extract_field "$SSRC/SKILL.md" "description" 2>/dev/null || echo "")
  SDESC_SHORT=$(short_desc "$SDESC")
  if [[ -n "$SDESC_SHORT" && "$SDESC_SHORT" != "." ]]; then
    SKILL_LIST="${SKILL_LIST}
- \`$SNAME\` — $SDESC_SHORT"
  else
    SKILL_LIST="${SKILL_LIST}
- \`$SNAME\`"
  fi
done
SKILL_LIST=$(echo "$SKILL_LIST" | sed '/./,$!d')

CMD_LIST=""
MANUAL_CMD_STEP=""
if [[ $CMD_COUNT -gt 0 ]]; then
  for i in $(seq 0 $((CMD_COUNT - 1))); do
    CNAME=$(jq -r ".commands[$i].name" "$MANIFEST_FILE")
    CSRC=$(jq -r ".commands[$i].source" "$MANIFEST_FILE")
    CSRC=$(resolve_tilde "$CSRC")
    CDESC=$(extract_field "$CSRC" "description" 2>/dev/null || echo "")
    if [[ -n "$CDESC" ]]; then
      CMD_LIST="${CMD_LIST}
- \`/$CNAME\` — $CDESC"
    else
      CMD_LIST="${CMD_LIST}
- \`/$CNAME\`"
    fi
  done
  CMD_LIST=$(echo "$CMD_LIST" | sed '/./,$!d')
  MANUAL_CMD_STEP="
# Copy commands
cp plugins/$PLUGIN_NAME/commands/*.md ~/.claude/commands/"
fi

AGENT_LIST=""
if [[ $AGENT_COUNT -gt 0 ]]; then
  for i in $(seq 0 $((AGENT_COUNT - 1))); do
    ANAME=$(jq -r ".agents[$i].name" "$MANIFEST_FILE")
    ASRC=$(jq -r ".agents[$i].source" "$MANIFEST_FILE")
    ASRC=$(resolve_tilde "$ASRC")
    ADESC=$(extract_field "$ASRC" "description" 2>/dev/null || echo "")
    ADESC_SHORT=$(short_desc "$ADESC")
    if [[ -n "$ADESC_SHORT" && "$ADESC_SHORT" != "." ]]; then
      AGENT_LIST="${AGENT_LIST}
- \`$ANAME\` — $ADESC_SHORT"
    else
      AGENT_LIST="${AGENT_LIST}
- \`$ANAME\`"
    fi
  done
  AGENT_LIST=$(echo "$AGENT_LIST" | sed '/./,$!d')
fi

# --- Assemble README ---
README_CONTENT="# $PLUGIN_NAME

$PLUGIN_DESC"

# What It Does (from full description + use-when bullets)
if [[ -n "$FULL_DESC" ]]; then
  WHAT_IT_DOES_PARA=$(short_desc "$FULL_DESC")
  README_CONTENT="$README_CONTENT

## What It Does

$WHAT_IT_DOES_PARA"
  if [[ -n "$USE_WHEN" ]]; then
    README_CONTENT="$README_CONTENT

**Use when:**
$USE_WHEN"
  fi
fi

# Key Features
if [[ -n "$KEY_FEATURES" ]]; then
  README_CONTENT="$README_CONTENT

## Key Features

$KEY_FEATURES"
fi

# Usage
if [[ -n "$USAGE_SECTION" ]]; then
  README_CONTENT="$README_CONTENT

## Usage

$USAGE_SECTION"
fi

# Contents summary
CONTENTS_SUMMARY="- **$SKILL_COUNT** skill(s), **$CMD_COUNT** command(s)"
if [[ $AGENT_COUNT -gt 0 ]]; then
  CONTENTS_SUMMARY="$CONTENTS_SUMMARY, **$AGENT_COUNT** agent(s)"
fi

README_CONTENT="$README_CONTENT

## Contents

$CONTENTS_SUMMARY

### Skills

$SKILL_LIST"

# Commands subsection
if [[ $CMD_COUNT -gt 0 ]]; then
  README_CONTENT="$README_CONTENT

### Commands

$CMD_LIST"
fi

# Agents subsection
if [[ $AGENT_COUNT -gt 0 ]]; then
  README_CONTENT="$README_CONTENT

### Agents

$AGENT_LIST"
fi

# Prerequisites
if [[ -n "$PREREQUISITES" ]]; then
  README_CONTENT="$README_CONTENT

## Prerequisites

$PREREQUISITES"
fi

# Installation
README_CONTENT="$README_CONTENT

## Installation

### Via Claude Code (Recommended)

\`\`\`shell
# Add the marketplace (one-time setup)
/plugin marketplace add $GITHUB_USER/claude-code-skills

# Install this plugin
/plugin install $PLUGIN_NAME@claude-code-skills
\`\`\`

### Via Script

\`\`\`bash
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/$PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`

### Manual

\`\`\`bash
# Copy skills
cp -r plugins/$PLUGIN_NAME/skills/* ~/.claude/skills/
$MANUAL_CMD_STEP
\`\`\`

## Uninstall

\`\`\`bash
# Via Claude Code
/plugin uninstall $PLUGIN_NAME@claude-code-skills

# Via script
git clone https://github.com/$GITHUB_USER/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/$PLUGIN_NAME
rm -rf /tmp/ccs
\`\`\`"

# See Also
if [[ -n "$SEE_ALSO" ]]; then
  README_CONTENT="$README_CONTENT

## See Also

$SEE_ALSO"
fi

# Compatibility + License
README_CONTENT="$README_CONTENT

## Compatibility

This plugin follows the **Claude Code Plugin** format. Skills use the **Agent Skills** standard recognized by:

- [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) (Anthropic)
- [Cursor](https://www.cursor.com/)
- [Codex CLI](https://github.com/openai/codex) (OpenAI)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Google)

## License

[MIT](LICENSE)"

write_file "$OUTPUT_DIR/README.md" "$README_CONTENT" "README.md"

# --- 7. Validate if possible ---
echo ""
VALIDATE_SCRIPT="$SCRIPT_DIR/validate-plugin.sh"
if [[ -x "$VALIDATE_SCRIPT" ]] && ! $DRY_RUN; then
  echo "--- Validation ---"
  "$VALIDATE_SCRIPT" "$OUTPUT_DIR" || true
fi

echo ""
if $DRY_RUN; then
  echo "Dry run complete. No files were written."
else
  echo "Plugin assembled at: $OUTPUT_DIR"
  echo ""
  echo "Next steps:"
  echo "  1. Review the output directory"
  echo "  2. Validate: $SCRIPT_DIR/validate-plugin.sh $OUTPUT_DIR"
  echo "  3. Sync to monorepo: $SCRIPT_DIR/sync-monorepo.sh --add-plugin $PLUGIN_NAME <monorepo-dir>"
fi
