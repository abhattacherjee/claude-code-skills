#!/usr/bin/env bash
# test-dev-skill.sh — Swap installed plugin cache with dev version for testing.
#
# Usage:
#   ./scripts/test-dev-skill.sh install   # backup cache, install dev version
#   ./scripts/test-dev-skill.sh restore   # restore original cached version
#   ./scripts/test-dev-skill.sh status    # show which version is active
#
# After "install", start a NEW Claude Code session to pick up the changes.
# After testing, run "restore" to put the original version back.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_NAME="obsidian-brain"

# Discover the latest installed cache version (highest semver directory)
CACHE_BASE="${HOME}/.claude/plugins/cache/claude-code-skills/${PLUGIN_NAME}"
PLUGIN_VERSION=$(ls -1 "$CACHE_BASE" 2>/dev/null | grep -v '\.bak$' | sort -V | tail -1)
if [[ -z "$PLUGIN_VERSION" ]]; then
    echo "ERROR: No cached version found at $CACHE_BASE"
    exit 1
fi

CACHE_DIR="${CACHE_BASE}/${PLUGIN_VERSION}"
BACKUP_DIR="${CACHE_BASE}/${PLUGIN_VERSION}.bak"

cmd="${1:-status}"

case "$cmd" in
    install)
        if [[ ! -d "$CACHE_DIR" ]]; then
            echo "ERROR: Cache directory not found: $CACHE_DIR"
            echo "Available versions:"
            ls "$CACHE_BASE" 2>/dev/null || echo "  (none)"
            exit 1
        fi

        if [[ -d "$BACKUP_DIR" ]]; then
            echo "WARNING: Backup already exists at $BACKUP_DIR"
            echo "Run 'restore' first, or remove the backup manually."
            exit 1
        fi

        echo "Backing up: $CACHE_DIR -> $BACKUP_DIR"
        cp -R "$CACHE_DIR" "$BACKUP_DIR"

        # On failure, warn user to restore manually
        trap 'echo "ERROR: Install failed partway. Run \"$0 restore\" to recover." >&2' ERR

        echo "Installing dev versions..."

        # Copy hooks (Python files)
        cp "$REPO_ROOT/hooks/"*.py "$CACHE_DIR/hooks/"
        echo "  hooks/*.py -> cache"

        # Copy skills
        for skill_dir in "$REPO_ROOT/skills/"*/; do
            skill_name=$(basename "$skill_dir")
            mkdir -p "$CACHE_DIR/skills/$skill_name"
            if compgen -G "$skill_dir"* > /dev/null 2>&1; then
                cp "$skill_dir"* "$CACHE_DIR/skills/$skill_name/"
            fi
            echo "  skills/$skill_name/ -> cache"
        done

        # Copy runtime scripts (whitelist — scripts/ is heterogeneous;
        # see feedback_plugin_sync_scripts_heterogeneous.md memory).
        # These are dispatched by skills at runtime and must reflect the
        # repo state, not the released cache.
        if [[ -f "$REPO_ROOT/scripts/vault_doctor.py" ]]; then
            cp "$REPO_ROOT/scripts/vault_doctor.py" "$CACHE_DIR/scripts/"
            echo "  scripts/vault_doctor.py -> cache"
        fi
        if [[ -d "$REPO_ROOT/scripts/vault_doctor_checks" ]]; then
            mkdir -p "$CACHE_DIR/scripts/vault_doctor_checks"
            cp "$REPO_ROOT/scripts/vault_doctor_checks/"*.py "$CACHE_DIR/scripts/vault_doctor_checks/"
            echo "  scripts/vault_doctor_checks/*.py -> cache"
        fi

        trap - ERR

        # Run security tests against installed cache
        echo ""
        echo "Running security tests..."
        SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
        if [ -f "$SCRIPT_DIR/test-security.sh" ]; then
            if ! bash "$SCRIPT_DIR/test-security.sh"; then
                echo "WARNING: Security tests failed. Fix before testing in a live session."
            fi
        fi

        echo ""
        echo "Dev version installed to cache (v${PLUGIN_VERSION})."
        echo "Start a NEW Claude Code session to pick up the changes."
        echo ""
        echo "When done testing, run:"
        echo "  ./scripts/test-dev-skill.sh restore"
        ;;

    restore)
        if [[ ! -d "$BACKUP_DIR" ]]; then
            echo "No backup found at $BACKUP_DIR — nothing to restore."
            echo "Current cache is the original version."
            exit 0
        fi

        # Sanity check: CACHE_DIR must be under CACHE_BASE
        if [[ "$CACHE_DIR" != "${CACHE_BASE}/"* ]]; then
            echo "ERROR: CACHE_DIR '$CACHE_DIR' is outside expected base. Aborting." >&2
            exit 1
        fi

        echo "Restoring: $BACKUP_DIR -> $CACHE_DIR"
        rm -rf "$CACHE_DIR"
        mv "$BACKUP_DIR" "$CACHE_DIR"

        echo ""
        echo "Original v${PLUGIN_VERSION} restored."
        echo "Start a NEW session to pick up the restored version."
        ;;

    status)
        echo "Plugin: $PLUGIN_NAME"
        echo "Installed cache version: $PLUGIN_VERSION"
        echo "Cache dir: $CACHE_DIR"
        echo ""

        if [[ -d "$BACKUP_DIR" ]]; then
            echo "Status: DEV VERSION ACTIVE (backup exists)"
            echo "Backup: $BACKUP_DIR"
            echo ""
            echo "Files changed from original:"
            diff -rq "$BACKUP_DIR" "$CACHE_DIR" 2>/dev/null | head -20 || echo "  (diff failed)"
        elif [[ -d "$CACHE_DIR" ]]; then
            echo "Status: ORIGINAL (no backup, cache is clean)"
        else
            echo "Status: NOT INSTALLED (cache dir missing)"
        fi
        ;;

    *)
        echo "Usage: $0 {install|restore|status}"
        exit 1
        ;;
esac
