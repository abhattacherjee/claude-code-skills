#!/usr/bin/env python3
"""
obsidian_session_hint.py -- SessionStart hook for obsidian-brain plugin.

Finds the latest session note for the current project and injects
a context hint via additionalContext. No summarization at SessionStart
(deferred to /recall skill). Always exits 0.
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Import shared utilities
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obsidian_utils import (  # noqa: E402
    find_latest_session,
    get_project_name,
    load_config,
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        _run()
    except Exception as exc:
        print(f"[obsidian-brain] session-hint unexpected error: {exc}", file=sys.stderr)
    sys.exit(0)


def _run() -> None:
    # 1. Read hook input from stdin
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # 2. Load config
    config = load_config()
    vault_path = config.get("vault_path", "")
    if not vault_path:
        return

    sessions_folder = config.get("sessions_folder", "claude-sessions")

    # 3. Derive project name
    project = get_project_name(cwd)

    # 4. Find latest session note for this project
    latest = find_latest_session(vault_path, sessions_folder, project)
    if not latest:
        print(f"[obsidian-brain] no previous sessions found for {project}", file=sys.stderr)
        return

    # 5. Output JSON with additionalContext hint
    hint = (
        f"Obsidian context: Last session for {project} ({latest['date']}): "
        f"{latest['summary']} Next steps: {latest['next_steps']}"
    )
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": hint}}

    try:
        print(json.dumps(output))
        sys.stdout.flush()
    except BrokenPipeError:
        pass  # CC may close the pipe before we write

    print(f"[obsidian-brain] injected context hint for {project}", file=sys.stderr)


if __name__ == "__main__":
    main()
