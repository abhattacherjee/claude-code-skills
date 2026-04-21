#!/usr/bin/env python3
"""
obsidian_context_snapshot.py -- PreCompact hook for obsidian-brain plugin.

Captures a snapshot of the current session context before compaction or
context clear, writing it to the Obsidian vault. Uses raw message extraction
(no claude -p call) to avoid timing issues. Always exits 0.
"""

from __future__ import annotations

import datetime
import json
import os
import sys

# ---------------------------------------------------------------------------
# Import shared utilities
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obsidian_utils import (  # noqa: E402
    extract_assistant_messages,
    extract_session_metadata,
    extract_user_messages,
    load_config,
    make_filename,
    read_transcript,
    scrub_secrets,
    slugify,
    write_vault_note,
)


# ---------------------------------------------------------------------------
# Snapshot body construction
# ---------------------------------------------------------------------------


def _build_snapshot_body(
    user_msgs: list[str],
    metadata: dict,
    trigger: str,
    assistant_msgs: list[str] | None = None,
) -> str:
    """Build the snapshot note body from raw message data.

    Emits a trailing ``## Last messages (raw)`` section with alternating
    ``**User:**`` / ``**Assistant:**`` lines so that the shared raw-fallback
    parser in ``upgrade_unsummarized_note()`` can summarize a snapshot even
    when its JSONL transcript is no longer available (e.g. the session has
    been closed and the transcript garbage-collected).
    """
    if assistant_msgs is None:
        assistant_msgs = []
    sections: list[str] = []
    project = metadata.get("project", "unknown")

    # Last 10 user messages as context summary
    recent = user_msgs[-10:] if len(user_msgs) > 10 else user_msgs

    sections.append("## What was happening")
    sections.append(
        f"Context snapshot for **{project}** triggered by `{trigger}`. "
        f"Session had {len(user_msgs)} user message(s).\n"
    )
    sections.append("Recent user messages:")
    for i, msg in enumerate(recent, 1):
        snippet = scrub_secrets(msg[:300].replace("\n", " "))
        sections.append(f"{i}. {snippet}")
    sections.append("")

    sections.append("## Key context that may be lost")
    branch = metadata.get("git_branch", "")
    duration = metadata.get("duration_minutes", 0)
    sections.append(f"- **Project:** {project}")
    if branch:
        sections.append(f"- **Branch:** {branch}")
    sections.append(f"- **Duration so far:** {duration} min")
    errors = metadata.get("errors", [])
    if errors:
        sections.append("- **Recent errors:**")
        for e in errors[:5]:
            sections.append(f"  - {e}")
    sections.append("")

    sections.append("## Uncommitted work")
    files = metadata.get("files_touched", [])
    if files:
        for f in files[:30]:
            sections.append(f"- `{f}`")
    else:
        sections.append("No file modifications detected.")
    sections.append("")

    # Raw-fallback section: interleave last N user + assistant messages so
    # upgrade_unsummarized_note() can summarize from this file alone when
    # the JSONL transcript is gone. Matches the section header consumed by
    # the shared parser in obsidian_utils.py.
    _RAW_TAIL = 6
    recent_users = user_msgs[-_RAW_TAIL:] if len(user_msgs) > _RAW_TAIL else user_msgs
    recent_asst = assistant_msgs[-_RAW_TAIL:] if len(assistant_msgs) > _RAW_TAIL else assistant_msgs
    sections.append("## Last messages (raw)")
    # Alternate as best we can — some sessions are user-heavy or assistant-heavy.
    max_len = max(len(recent_users), len(recent_asst))
    for i in range(max_len):
        if i < len(recent_users):
            clean = scrub_secrets(recent_users[i][:800].replace("\n", " "))
            sections.append(f"**User:** {clean}")
            sections.append("")
        if i < len(recent_asst):
            clean = scrub_secrets(recent_asst[i][:800].replace("\n", " "))
            sections.append(f"**Assistant:** {clean}")
            sections.append("")

    return "\n".join(sections)


def _build_snapshot_note(
    session_id: str,
    metadata: dict,
    body: str,
    trigger: str,
    date_str: str | None = None,
) -> str:
    """Construct full snapshot note with YAML frontmatter.

    ``date_str`` is optional; if omitted, today() is used. Callers that also
    construct a filename should pass their pre-computed ``date_str`` so the
    backlink stem and the actual filename can never skew across a midnight
    clock tick inside a single _run() invocation.
    """
    if date_str is None:
        date_str = datetime.date.today().isoformat()
    project = metadata.get("project", "unknown")
    project_slug = slugify(project)
    # Derive the parent session note's filename stem via the same helper the
    # session log uses, so the backlink can never drift from the real file.
    parent_filename = make_filename(date_str, project_slug, session_id)
    parent_stem = parent_filename[:-3] if parent_filename.endswith(".md") else parent_filename

    tags = [
        "claude/snapshot",
        f"claude/project/{project_slug}",
        "claude/auto",
    ]

    fm_lines = [
        "---",
        "type: claude-snapshot",
        f"date: {date_str}",
        f"session_id: {session_id}",
        f"project: {project}",
        f"trigger: {trigger}",
        "tags:",
        *[f"  - {t}" for t in tags],
        "status: auto-logged",
        f'source_session_note: "[[{parent_stem}]]"',
        "---",
    ]

    title = f"# Context Snapshot: {project}"
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
        print(f"[obsidian-brain] context-snapshot unexpected error: {exc}", file=sys.stderr)
    sys.exit(0)


def _run() -> None:
    # 1. Read hook input from stdin
    try:
        raw = sys.stdin.read(1_000_000)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[obsidian-brain] invalid stdin JSON: {exc}", file=sys.stderr)
        return

    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    transcript_path = hook_input.get("transcript_path", "")
    source = hook_input.get("source", "compact")

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
    vault_path = config.get("vault_path", "")
    if not vault_path:
        print("[obsidian-brain] no vault_path configured, skipping", file=sys.stderr)
        return

    sessions_folder = config.get("sessions_folder", "claude-sessions")

    # 3. Check if snapshots enabled for this trigger source
    if source in ("compact", "auto"):
        if not config.get("snapshot_on_compact", True):
            print("[obsidian-brain] snapshot_on_compact disabled, skipping", file=sys.stderr)
            return
        trigger = "compact"
    elif source == "clear":
        if not config.get("snapshot_on_clear", True):
            print("[obsidian-brain] snapshot_on_clear disabled, skipping", file=sys.stderr)
            return
        trigger = "clear"
    else:
        trigger = source

    # 4. Read transcript and extract data
    messages = read_transcript(transcript_path)
    if not messages:
        print("[obsidian-brain] empty transcript, skipping snapshot", file=sys.stderr)
        return

    user_msgs = extract_user_messages(messages)
    assistant_msgs = extract_assistant_messages(messages)
    metadata = extract_session_metadata(messages, cwd)

    # 5. Build snapshot note.
    # Compute date_str + hhmmss together so the frontmatter backlink stem
    # (which embeds date_str) and the filename (which embeds both) share the
    # same single source of truth — no midnight-rollover skew inside one run.
    now = datetime.datetime.now()
    date_str = now.date().isoformat()
    hhmmss = now.strftime("%H%M%S")
    project_slug = slugify(metadata.get("project", "session"))

    body = _build_snapshot_body(user_msgs, metadata, trigger,
                                assistant_msgs=assistant_msgs)
    content = _build_snapshot_note(session_id, metadata, body, trigger, date_str=date_str)

    # 6. Write to vault with -snapshot-<HHMMSS> suffix (seconds-resolution avoids
    # collisions between multiple /compact invocations in the same day).
    filename = make_filename(date_str, project_slug, session_id, suffix=f"-snapshot-{hhmmss}")

    if write_vault_note(vault_path, sessions_folder, filename, content):
        print(f"[obsidian-brain] snapshot written: {filename}", file=sys.stderr)
    else:
        print("[obsidian-brain] failed to write snapshot", file=sys.stderr)


if __name__ == "__main__":
    main()
