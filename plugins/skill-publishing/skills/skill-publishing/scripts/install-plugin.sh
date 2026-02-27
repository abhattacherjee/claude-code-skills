#!/usr/bin/env bash
# install-plugin.sh — Install a Claude Code plugin from an assembled plugin directory
# Copies skills, commands, agents, and hooks to ~/.claude/ or ./.claude/
set -eu

# Defaults
DRY_RUN=false
INSTALL_LEVEL="user"  # user or project
UNINSTALL=false

usage() {
  cat <<'EOF'
Usage: install-plugin.sh [options] <plugin-dir>

Installs a Claude Code plugin by copying its components to the target directory.

Options:
  --dry-run            Preview what would be installed without writing files
  --user-level         Install to ~/.claude/ (default)
  --project-level      Install to ./.claude/ (current project only)
  --uninstall          Remove the plugin's installed files
  -h, --help           Show this help

Examples:
  install-plugin.sh ./plugins/git-flow                # Install to ~/.claude/
  install-plugin.sh --dry-run ./plugins/git-flow      # Preview installation
  install-plugin.sh --project-level ./plugins/git-flow # Install to ./.claude/
  install-plugin.sh --uninstall ./plugins/git-flow    # Remove installed files
EOF
  exit 0
}

# --- Parse arguments ---
PLUGIN_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)        DRY_RUN=true; shift ;;
    --user-level)     INSTALL_LEVEL="user"; shift ;;
    --project-level)  INSTALL_LEVEL="project"; shift ;;
    --uninstall)      UNINSTALL=true; shift ;;
    -h|--help)        usage ;;
    -*)               echo "Error: Unknown option: $1" >&2; exit 1 ;;
    *)                PLUGIN_DIR="$1"; shift ;;
  esac
done

if [[ -z "$PLUGIN_DIR" ]]; then
  echo "Error: plugin directory is required" >&2
  echo "Usage: install-plugin.sh [options] <plugin-dir>" >&2
  exit 1
fi

# --- Check dependencies ---
if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not installed" >&2
  echo "Install: brew install jq (macOS) or apt install jq (Linux)" >&2
  exit 1
fi

# --- Resolve plugin directory ---
if [[ ! -d "$PLUGIN_DIR" ]]; then
  echo "Error: plugin directory not found: $PLUGIN_DIR" >&2
  exit 1
fi

PLUGIN_DIR="$(cd "$PLUGIN_DIR" && pwd)"

# --- Read plugin.json ---
PLUGIN_JSON="$PLUGIN_DIR/.claude-plugin/plugin.json"
if [[ ! -f "$PLUGIN_JSON" ]]; then
  echo "Error: not a valid plugin directory (missing .claude-plugin/plugin.json)" >&2
  exit 1
fi

PLUGIN_NAME=$(jq -r '.name' "$PLUGIN_JSON")
PLUGIN_VERSION=$(jq -r '.version' "$PLUGIN_JSON")
PLUGIN_DESC=$(jq -r '.description' "$PLUGIN_JSON")

# --- Determine target directory ---
if [[ "$INSTALL_LEVEL" == "project" ]]; then
  TARGET_DIR="./.claude"
else
  TARGET_DIR="$HOME/.claude"
fi

ACTION="Install"
if $UNINSTALL; then
  ACTION="Uninstall"
fi

echo "$ACTION: $PLUGIN_NAME v$PLUGIN_VERSION"
echo "Target:  $TARGET_DIR"
echo "Dry run: $DRY_RUN"
echo ""

INSTALLED=0
SKIPPED=0
WARNINGS=0

# --- Install/uninstall skills ---
if [[ -d "$PLUGIN_DIR/skills" ]]; then
  echo "--- Skills ---"
  while IFS= read -r skill_dir; do
    SKILL_NAME=$(basename "$skill_dir")
    SKILL_DST="$TARGET_DIR/skills/$SKILL_NAME"

    if $UNINSTALL; then
      if [[ -d "$SKILL_DST" ]]; then
        if $DRY_RUN; then
          echo "  WOULD REMOVE  skills/$SKILL_NAME/"
        else
          rm -rf "$SKILL_DST"
          echo "  REMOVED  skills/$SKILL_NAME/"
        fi
        INSTALLED=$((INSTALLED + 1))
      else
        echo "  SKIP  skills/$SKILL_NAME/ (not installed)"
        SKIPPED=$((SKIPPED + 1))
      fi
    else
      if [[ -d "$SKILL_DST" ]]; then
        echo "  WARN  skills/$SKILL_NAME/ already exists (overwriting)"
        WARNINGS=$((WARNINGS + 1))
      fi
      if $DRY_RUN; then
        echo "  WOULD INSTALL  skills/$SKILL_NAME/"
      else
        mkdir -p "$SKILL_DST"
        rsync -a --delete --exclude='.DS_Store' "$skill_dir/" "$SKILL_DST/"
        # Preserve execute permissions on scripts
        find "$SKILL_DST" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
        echo "  INSTALLED  skills/$SKILL_NAME/"
      fi
      INSTALLED=$((INSTALLED + 1))
    fi
  done < <(find "$PLUGIN_DIR/skills" -maxdepth 1 -mindepth 1 -type d | sort)
fi

# --- Install/uninstall commands ---
if [[ -d "$PLUGIN_DIR/commands" ]]; then
  echo ""
  echo "--- Commands ---"
  while IFS= read -r cmd_file; do
    CMD_NAME=$(basename "$cmd_file")
    CMD_DST="$TARGET_DIR/commands/$CMD_NAME"

    if $UNINSTALL; then
      if [[ -f "$CMD_DST" ]]; then
        if $DRY_RUN; then
          echo "  WOULD REMOVE  commands/$CMD_NAME"
        else
          rm -f "$CMD_DST"
          echo "  REMOVED  commands/$CMD_NAME"
        fi
        INSTALLED=$((INSTALLED + 1))
      else
        echo "  SKIP  commands/$CMD_NAME (not installed)"
        SKIPPED=$((SKIPPED + 1))
      fi
    else
      if [[ -f "$CMD_DST" ]]; then
        echo "  WARN  commands/$CMD_NAME already exists (overwriting)"
        WARNINGS=$((WARNINGS + 1))
      fi
      if $DRY_RUN; then
        echo "  WOULD INSTALL  commands/$CMD_NAME"
      else
        mkdir -p "$TARGET_DIR/commands"
        cp "$cmd_file" "$CMD_DST"
        echo "  INSTALLED  commands/$CMD_NAME"
      fi
      INSTALLED=$((INSTALLED + 1))
    fi
  done < <(find "$PLUGIN_DIR/commands" -name '*.md' -type f | sort)
fi

# --- Install/uninstall agents ---
if [[ -d "$PLUGIN_DIR/agents" ]]; then
  echo ""
  echo "--- Agents ---"
  while IFS= read -r agent_file; do
    AGENT_NAME=$(basename "$agent_file")
    AGENT_DST="$TARGET_DIR/agents/$AGENT_NAME"

    if $UNINSTALL; then
      if [[ -f "$AGENT_DST" ]]; then
        if $DRY_RUN; then
          echo "  WOULD REMOVE  agents/$AGENT_NAME"
        else
          rm -f "$AGENT_DST"
          echo "  REMOVED  agents/$AGENT_NAME"
        fi
        INSTALLED=$((INSTALLED + 1))
      fi
    else
      if [[ -f "$AGENT_DST" ]]; then
        echo "  WARN  agents/$AGENT_NAME already exists (overwriting)"
        WARNINGS=$((WARNINGS + 1))
      fi
      if $DRY_RUN; then
        echo "  WOULD INSTALL  agents/$AGENT_NAME"
      else
        mkdir -p "$TARGET_DIR/agents"
        cp "$agent_file" "$AGENT_DST"
        echo "  INSTALLED  agents/$AGENT_NAME"
      fi
      INSTALLED=$((INSTALLED + 1))
    fi
  done < <(find "$PLUGIN_DIR/agents" -name '*.md' -type f | sort)
fi

# --- Install/uninstall hooks ---
if [[ -d "$PLUGIN_DIR/hooks" ]]; then
  echo ""
  echo "--- Hooks ---"
  echo "  WARN  Hook installation requires manual review"
  echo "  Source: $PLUGIN_DIR/hooks/"
  echo "  Target: $TARGET_DIR/hooks/"
  WARNINGS=$((WARNINGS + 1))

  if ! $UNINSTALL && ! $DRY_RUN; then
    echo "  Hooks must be merged manually to avoid overwriting existing hooks."
    echo "  Review: ls $PLUGIN_DIR/hooks/"
  fi
fi

# --- Summary ---
echo ""
if $UNINSTALL; then
  echo "Uninstall summary: $INSTALLED removed, $SKIPPED not found"
else
  echo "Install summary: $INSTALLED installed, $WARNINGS warning(s)"
fi

if $DRY_RUN; then
  echo "Dry run complete. No files were written."
fi
