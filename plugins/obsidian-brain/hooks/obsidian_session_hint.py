#!/usr/bin/env python3
"""
obsidian_session_hint.py -- SessionStart hook for obsidian-brain plugin.

Finds the latest session note for the current project and injects
a context hint via additionalContext. No summarization at SessionStart
(deferred to /recall skill). Always exits 0.
"""

import datetime
import json
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Import shared utilities
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obsidian_utils import (  # noqa: E402
    _bootstrap_prefix,
    _ensure_secure_dir,
    find_latest_session,
    get_project_name,
    load_config,
)


# ---------------------------------------------------------------------------
# Bootstrap-file + audit-log helpers
# ---------------------------------------------------------------------------

_HOOK_LOG_NAME = "obsidian-brain-hook.log"
_HOOK_LOG_MAX_BYTES = 100 * 1024  # 100 KB


def _write_bootstrap_atomic(project: str, session_id: str) -> bool:
    """Write session_id to the project's bootstrap file. Returns True on success."""
    # Force absolute path so os.path.dirname() always returns a real
    # directory.  With _bootstrap_prefix() fixed to the secure directory,
    # dirname() always returns a real directory — but keep abspath() as
    # belt-and-suspenders.
    # Making the target absolute keeps the temp file and target on the
    # same filesystem, so os.replace() is always safe.
    path = os.path.abspath(f"{_bootstrap_prefix()}{project}")
    tmp = None
    try:
        _ensure_secure_dir()
        dir_name = os.path.dirname(path)
        if not dir_name:
            # Defensive fallback — should be unreachable after abspath().
            dir_name = "/tmp"
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".ob-sid-", suffix=".tmp", dir=dir_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(session_id)
        os.replace(tmp, path)
        tmp = None  # consumed by replace
        return True
    except OSError as exc:
        print(f"[obsidian-brain] bootstrap write failed: {exc}", file=sys.stderr)
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _append_hook_log(project: str, session_id: str, bootstrap_updated: bool) -> None:
    """Append a one-line audit record; rotate the log when it exceeds the cap."""
    log_dir = os.path.join(os.path.expanduser("~"), ".claude")
    log_path = os.path.join(log_dir, _HOOK_LOG_NAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
        try:
            if os.path.getsize(log_path) > _HOOK_LOG_MAX_BYTES:
                os.replace(log_path, log_path + ".1")
        except OSError:
            pass  # no existing log; nothing to rotate
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        short_sid = (session_id or "unknown")[:8]
        line = (
            f"{timestamp} SessionStart project={project} sid={short_sid} "
            f"bootstrap_updated={'true' if bootstrap_updated else 'false'}\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        print(f"[obsidian-brain] hook log append failed: {exc}", file=sys.stderr)


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
        raw = sys.stdin.read(1_000_000)
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # 2. Derive project name (needed for bootstrap before vault config).
    project = get_project_name(cwd)

    # 2a. Refresh the bootstrap file with the authoritative session_id from stdin.
    # This runs regardless of vault configuration so the bootstrap stays current
    # even when obsidian-brain is not fully configured.
    session_id = hook_input.get("session_id", "")
    bootstrap_updated = False
    if session_id:
        bootstrap_updated = _write_bootstrap_atomic(project, session_id)
    _append_hook_log(project, session_id, bootstrap_updated)

    # 3. Load config
    config = load_config()
    vault_path = config.get("vault_path", "")
    if not vault_path:
        return

    sessions_folder = config.get("sessions_folder", "claude-sessions")

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
