#!/usr/bin/env python3
"""
obsidian_session_log.py -- SessionEnd hook for obsidian-brain plugin.

Reads the session transcript, writes a raw fallback note to the Obsidian vault,
then attempts AI summarization to upgrade it. Always exits 0.
"""

import datetime
import json
import os
import sys

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
    generate_summary,
    is_resumed_session,
    load_config,
    make_filename,
    read_transcript,
    should_skip_session,
    slugify,
    write_vault_note,
)


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
        raw = sys.stdin.read()
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[obsidian-brain] invalid stdin JSON: {exc}", file=sys.stderr)
        return

    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    transcript_path = hook_input.get("transcript_path", "")

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
    summary_model = config.get("summary_model", "haiku")
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

    # 5. Skip check
    if should_skip_session(user_msgs, 0, min_messages=min_messages, min_duration=min_duration):
        # Duration not yet known; check message count only (duration=0 bypasses duration check)
        print(f"[obsidian-brain] too few user messages ({len(user_msgs)}), skipping", file=sys.stderr)
        return

    # 6. Extract metadata
    metadata = extract_session_metadata(messages, cwd)

    # Re-check with actual duration
    if should_skip_session(user_msgs, metadata["duration_minutes"],
                           min_messages=min_messages, min_duration=min_duration):
        print(f"[obsidian-brain] session below thresholds, skipping", file=sys.stderr)
        return

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
    raw_body = build_raw_fallback(user_msgs, metadata, assistant_msgs=assistant_msgs, tool_uses=tool_uses)
    raw_content = _build_note(session_id, metadata, raw_body, resumed=resumed)
    if not write_vault_note(vault_path, sessions_folder, filename, raw_content):
        print("[obsidian-brain] failed to write raw note, aborting", file=sys.stderr)
        return
    print("[obsidian-brain] raw note written, attempting summarization...", file=sys.stderr)

    # 10. Attempt AI summarization with 15s timeout
    summary = generate_summary(
        user_msgs, assistant_msgs, metadata,
        model=summary_model, timeout=15,
    )

    # 11. If summary succeeds, overwrite with summarized version
    if summary:
        summarized_content = _build_note(session_id, metadata, summary, resumed=resumed)
        if write_vault_note(vault_path, sessions_folder, filename, summarized_content):
            print("[obsidian-brain] upgraded to AI summary", file=sys.stderr)
        else:
            print("[obsidian-brain] summary write failed, raw note preserved", file=sys.stderr)
    else:
        print("[obsidian-brain] summarization failed/timed out, raw note preserved", file=sys.stderr)


if __name__ == "__main__":
    main()
