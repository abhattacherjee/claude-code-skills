#!/usr/bin/env python3
"""
obsidian_session_log.py -- SessionEnd hook for obsidian-brain plugin.

Reads the session transcript and writes a raw note to the Obsidian vault.
AI summarization is deferred to /recall (SessionEnd hooks are fire-and-forget;
slow subprocess calls like `claude -p` get killed when the process tree exits).
Always exits 0.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import shared utilities
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obsidian_utils import (  # noqa: E402
    build_raw_fallback,
    extract_assistant_messages,
    extract_session_metadata,
    extract_tool_uses,
    extract_user_messages,
    find_snapshots_for_session,
    is_resumed_session,
    load_config,
    make_filename,
    read_transcript,
    should_skip_session,
    slugify,
    write_vault_note,
)


# ---------------------------------------------------------------------------
# Session cache cleanup
# ---------------------------------------------------------------------------


def _cleanup_session_cache(session_id: str) -> None:
    """Remove the per-session disk cache file for a finished session."""
    if not session_id:
        return
    try:
        import obsidian_utils
        cache_path = f"{obsidian_utils._CACHE_PREFIX}{session_id}.json"
        if os.path.exists(cache_path):
            os.unlink(cache_path)
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup, never fatal
        print(f"[obsidian-brain] session cache cleanup failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Note construction
# ---------------------------------------------------------------------------


def _build_note(
    session_id: str,
    metadata: dict,
    body: str,
    resumed: bool = False,
) -> str:
    """Construct full markdown note with YAML frontmatter."""
    date_str = datetime.date.today().isoformat()
    project = metadata.get("project", "unknown")

    tags = [
        "claude/session",
        f"claude/project/{slugify(project)}",
        "claude/auto",
    ]

    fm_lines = [
        "---",
        "type: claude-session",
        f"date: {date_str}",
        f"session_id: {session_id}",
        f"project: {project}",
        f"project_path: \"{metadata.get('project_path', '')}\"",
        f"git_branch: \"{metadata.get('git_branch', '')}\"",
        f"duration_minutes: {metadata.get('duration_minutes', 0)}",
    ]
    if resumed:
        fm_lines.append("resumed: true")
    # Snapshot back-reference: append only if the caller discovered siblings.
    snapshots = metadata.get("snapshots") or []
    if snapshots:
        fm_lines.append("snapshots:")
        for s in snapshots:
            fm_lines.append(f'  - "{s}"')
    fm_lines.extend([
        "tags:",
        *[f"  - {t}" for t in tags],
        "status: auto-logged",
        "---",
    ])

    title = f"# Session: {project}"
    if metadata.get("git_branch"):
        title += f" ({metadata['git_branch']})"

    return "\n".join(fm_lines) + "\n\n" + title + "\n\n" + body + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        _run()
    except Exception as exc:
        print(f"[obsidian-brain] session-log unexpected error: {exc}", file=sys.stderr)
    sys.exit(0)


def _run() -> None:
    # 1. Read hook input from stdin
    try:
        raw = sys.stdin.read(1_000_000)
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[obsidian-brain] invalid stdin JSON: {exc}", file=sys.stderr)
        hook_input = {}

    # Extract session_id up front so the finally block can always clean up,
    # regardless of which early-return path below we take.
    session_id = hook_input.get("session_id", "")

    try:
        if not hook_input:
            return

        cwd = hook_input.get("cwd", "")
        transcript_path = hook_input.get("transcript_path", "")

        # Validate transcript_path stays inside ~/.claude/projects/
        if transcript_path:
            allowed_root = os.path.realpath(os.path.expanduser("~/.claude/projects"))
            if not os.path.realpath(transcript_path).startswith(allowed_root + os.sep):
                print("[obsidian-brain] transcript_path outside ~/.claude/projects, skipping", file=sys.stderr)
                return

        if not session_id or not transcript_path:
            print("[obsidian-brain] missing session_id or transcript_path, skipping", file=sys.stderr)
            return

        # 2. Load config
        config = load_config()
        if not config.get("auto_log_enabled", True):
            print("[obsidian-brain] auto_log_enabled is False, skipping", file=sys.stderr)
            return

        vault_path = config.get("vault_path", "")
        if not vault_path:
            print("[obsidian-brain] no vault_path configured, skipping", file=sys.stderr)
            return

        sessions_folder = config.get("sessions_folder", "claude-sessions")
        min_messages = config.get("min_messages", 3)
        min_duration = config.get("min_duration_minutes", 2)

        # 3. Read and parse transcript
        messages = read_transcript(transcript_path)
        if not messages:
            print("[obsidian-brain] empty transcript, skipping", file=sys.stderr)
            return

        # 4. Extract user and assistant messages
        user_msgs = extract_user_messages(messages)
        assistant_msgs = extract_assistant_messages(messages)

        # 4a. Discover sibling snapshots EARLY — their presence overrides
        # every threshold skip. Runs once; reused by both skip checks below.
        # Scan today AND yesterday so a session that spans midnight still
        # finds snapshots written with the previous day's date prefix (Copilot
        # PR #43 finding). The glob is keyed by date in find_snapshots_for_session;
        # a single-day lookup would silently miss cross-midnight snapshots
        # and both drop the threshold bypass and the back-reference list.
        today = datetime.date.today()
        candidate_dates = [
            today.isoformat(),
            (today - datetime.timedelta(days=1)).isoformat(),
        ]
        sessions_dir = Path(vault_path) / sessions_folder
        # Use Path(cwd).name to handle trailing-slash cwd; then slugify to match
        # what extract_session_metadata() + make_filename() do canonically.
        early_project = slugify(Path(cwd).name) if cwd else ""
        snapshots: list[str] = []
        if early_project:
            seen: set[str] = set()
            for d in candidate_dates:
                for link in find_snapshots_for_session(
                    sessions_dir, session_id, d, early_project
                ):
                    if link not in seen:
                        seen.add(link)
                        snapshots.append(link)

        # 5. Skip check (message count only)
        if should_skip_session(user_msgs, 0, min_messages=min_messages, min_duration=min_duration):
            if not snapshots:
                print(f"[obsidian-brain] too few user messages ({len(user_msgs)}), skipping",
                      file=sys.stderr)
                return
            print(
                f"[obsidian-brain] below message threshold but {len(snapshots)} snapshot(s) "
                "exist — writing session note anyway as anchor",
                file=sys.stderr,
            )

        # 6. Extract metadata
        metadata = extract_session_metadata(messages, cwd)
        metadata["vault_path"] = vault_path
        metadata["sessions_folder"] = sessions_folder

        # 6a. Canonical snapshot discovery using the parsed metadata's project.
        # Re-run because early_project (basename of cwd) may differ from
        # metadata["project"] for non-standard repo layouts. Union the
        # results — session_id already filters to this session's snapshots,
        # so any hit from either glob is a real back-reference. This also
        # preserves the early bypass when the canonical project diverges.
        canonical_project = metadata.get("project", "")
        if canonical_project and canonical_project != early_project:
            canonical_hits: list[str] = []
            for d in candidate_dates:
                canonical_hits.extend(
                    find_snapshots_for_session(
                        sessions_dir, session_id, d, canonical_project
                    )
                )
            # Merge, de-dupe, preserve chronological order (sorted wikilinks).
            snapshots = sorted(set(snapshots) | set(canonical_hits))
        metadata["snapshots"] = snapshots

        # Re-check with actual duration — BUT if snapshots exist, bypass
        # thresholds so the session note always anchors the snapshots.
        if should_skip_session(user_msgs, metadata["duration_minutes"],
                               min_messages=min_messages, min_duration=min_duration):
            if not snapshots:
                print("[obsidian-brain] session below thresholds, skipping", file=sys.stderr)
                return
            print(
                f"[obsidian-brain] below thresholds but {len(snapshots)} snapshot(s) exist — "
                "writing session note anyway as anchor",
                file=sys.stderr,
            )

        # 7. Detect resumed session
        resumed = is_resumed_session(vault_path, sessions_folder, session_id)
        if resumed:
            print(f"[obsidian-brain] resumed session detected", file=sys.stderr)

        # 8. Build filename
        date_str = datetime.date.today().isoformat()
        project_slug = slugify(metadata.get("project", "session"))
        filename = make_filename(date_str, project_slug, session_id)

        # 9. Extract tool usage details and write raw note FIRST
        tool_uses = extract_tool_uses(messages)
        raw_body = build_raw_fallback(user_msgs, metadata, assistant_msgs=assistant_msgs, tool_uses=tool_uses, config=config)
        raw_content = _build_note(session_id, metadata, raw_body, resumed=resumed)
        if not write_vault_note(vault_path, sessions_folder, filename, raw_content):
            print("[obsidian-brain] failed to write raw note, aborting", file=sys.stderr)
            return
        print("[obsidian-brain] raw note written (summarization deferred to /recall)", file=sys.stderr)
    finally:
        # Run cache cleanup regardless of how _run() exits so /tmp does not
        # accumulate stale cache files on any SessionEnd outcome — including
        # threshold skips, missing config, auto_log_disabled, or errors.
        _cleanup_session_cache(session_id)


if __name__ == "__main__":
    main()
