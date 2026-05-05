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

import obsidian_utils  # noqa: E402  — used for _first_seen_date qualified call
from obsidian_utils import (  # noqa: E402
    _append_sessionend_log,
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
# SessionEnd outcome enum (telemetry — issue #100 Phase 1)
# ---------------------------------------------------------------------------


class _Outcome:
    """String constants for SessionEnd hook outcomes written to the rotated audit log."""
    OK = "OK"  # Reserved for Phase 3 (#125) — reaper writes "Reaped OK" for reconstructed sessions
    OK_RAW_NOTE_ONLY = "OK_RAW_NOTE_ONLY"
    SKIPPED_BELOW_THRESHOLD = "SKIPPED_BELOW_THRESHOLD"
    SKIPPED_NO_TRANSCRIPT = "SKIPPED_NO_TRANSCRIPT"
    SKIPPED_NO_VAULT = "SKIPPED_NO_VAULT"
    SKIPPED_AUTO_LOG_OFF = "SKIPPED_AUTO_LOG_OFF"
    SKIPPED_INVALID_INPUT = "SKIPPED_INVALID_INPUT"
    SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS = "SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS"
    WRITE_FAILED = "WRITE_FAILED"
    EXCEPTION = "EXCEPTION"


# Updated by _run() as soon as hook_input is parsed; read by main()'s
# exception handler so EXCEPTION telemetry can carry real project/sid
# context instead of just "unknown".
_LAST_PROJECT: str = "unknown"
_LAST_SESSION_ID: str = "unknown"


# ---------------------------------------------------------------------------
# Telemetry helpers
# ---------------------------------------------------------------------------


def _project_slug_for_log(cwd: str) -> str:
    """Derive a project slug for telemetry from the hook's cwd field.

    Returns 'unknown' when cwd is empty rather than slugify's default 'session'.
    """
    return slugify(Path(cwd).name) if cwd else "unknown"


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
    reconstructed: bool = False,
) -> str:
    """Construct full markdown note with YAML frontmatter."""
    date_str = datetime.date.today().isoformat()
    project = metadata.get("project", "unknown")

    tags = [
        "claude/session",
        f"claude/project/{slugify(project)}",
        "claude/auto",
    ]
    if reconstructed:
        tags.append("claude/reconstructed")

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
    if reconstructed:
        fm_lines.append("reconstructed: true")
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

    if reconstructed:
        # Use the real transcript path threaded from the reaper call site;
        # fall back to a generic hint if not set (e.g. future callers).
        transcript_path = (
            metadata.get("transcript_path")
            or f"~/.claude/projects/<see session_id frontmatter>/{session_id[:8]}....jsonl"
        )
        banner = (
            "> **Reconstructed by SessionStart reaper.** The SessionEnd hook did not fire "
            "for this session (likely SIGKILL, harness crash, or process termination "
            f"before hook dispatch). Original JSONL: `{transcript_path}`. "
            "AI summarization deferred to `/recall`.\n\n"
        )
        body = banner + body

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
        # _run() may have updated _LAST_PROJECT / _LAST_SESSION_ID before raising;
        # use those for telemetry context rather than literal "unknown".
        try:
            _append_sessionend_log(
                project=_LAST_PROJECT,
                session_id=_LAST_SESSION_ID,
                outcome=_Outcome.EXCEPTION,
                detail=repr(exc)[:200],
            )
        except Exception:
            # Logging itself failed — nothing else to do; we still exit 0.
            pass
    sys.exit(0)


def _run() -> None:
    global _LAST_PROJECT, _LAST_SESSION_ID
    # Reset so a stale value from a prior invocation in the same process does
    # not bleed into this run's EXCEPTION telemetry.
    _LAST_PROJECT = "unknown"
    _LAST_SESSION_ID = "unknown"

    # 1. Read hook input from stdin
    try:
        raw = sys.stdin.read(1_000_000)
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[obsidian-brain] invalid stdin JSON: {exc}", file=sys.stderr)
        hook_input = {}

    # JSON can legally return non-dict (list, string, number); coerce to {}
    # so downstream .get() calls don't AttributeError. Treated as
    # SKIPPED_INVALID_INPUT below via the empty-input branch.
    if not isinstance(hook_input, dict):
        hook_input = {}

    # Extract session_id up front so the finally block can always clean up,
    # regardless of which early-return path below we take.
    session_id = hook_input.get("session_id", "")
    if session_id:
        _LAST_SESSION_ID = session_id

    try:
        if not hook_input:
            _append_sessionend_log(
                project="unknown",
                session_id=session_id,
                outcome=_Outcome.SKIPPED_INVALID_INPUT,
                detail="empty or unparseable stdin",
            )
            return

        cwd = hook_input.get("cwd", "")
        if cwd:
            _LAST_PROJECT = _project_slug_for_log(cwd)
        transcript_path = hook_input.get("transcript_path", "")

        # Validate transcript_path stays inside ~/.claude/projects/
        if transcript_path:
            allowed_root = os.path.realpath(os.path.expanduser("~/.claude/projects"))
            if not os.path.realpath(transcript_path).startswith(allowed_root + os.sep):
                print("[obsidian-brain] transcript_path outside ~/.claude/projects, skipping", file=sys.stderr)
                _append_sessionend_log(
                    project=_project_slug_for_log(cwd),
                    session_id=session_id,
                    outcome=_Outcome.SKIPPED_TRANSCRIPT_OUTSIDE_PROJECTS,
                    detail=os.path.realpath(transcript_path),
                )
                return

        if not session_id or not transcript_path:
            print("[obsidian-brain] missing session_id or transcript_path, skipping", file=sys.stderr)
            _append_sessionend_log(
                project=_project_slug_for_log(cwd),
                session_id=session_id,
                outcome=_Outcome.SKIPPED_INVALID_INPUT,
                detail=(
                    "missing session_id" if not session_id
                    else "missing transcript_path"
                ),
            )
            return

        # 2. Load config
        config = load_config()
        if not config.get("auto_log_enabled", True):
            print("[obsidian-brain] auto_log_enabled is False, skipping", file=sys.stderr)
            _append_sessionend_log(
                project=_project_slug_for_log(cwd),
                session_id=session_id,
                outcome=_Outcome.SKIPPED_AUTO_LOG_OFF,
            )
            return

        vault_path = config.get("vault_path", "")
        if not vault_path:
            print("[obsidian-brain] no vault_path configured, skipping", file=sys.stderr)
            _append_sessionend_log(
                project=_project_slug_for_log(cwd),
                session_id=session_id,
                outcome=_Outcome.SKIPPED_NO_VAULT,
            )
            return

        sessions_folder = config.get("sessions_folder", "claude-sessions")
        min_messages = config.get("min_messages", 3)
        min_duration = config.get("min_duration_minutes", 2)

        # 3. Read and parse transcript
        messages = read_transcript(transcript_path)
        if not messages:
            print("[obsidian-brain] empty transcript, skipping", file=sys.stderr)
            _append_sessionend_log(
                project=_project_slug_for_log(cwd),
                session_id=session_id,
                outcome=_Outcome.SKIPPED_NO_TRANSCRIPT,
                detail=transcript_path,
            )
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
                _append_sessionend_log(
                    project=_project_slug_for_log(cwd),
                    session_id=session_id,
                    outcome=_Outcome.SKIPPED_BELOW_THRESHOLD,
                    msgs=len(user_msgs),
                    dur_min=0.0,
                    detail="message-count check",
                )
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
        # Cached: also drives detail="snapshot-bypass" on the OK_RAW_NOTE_ONLY log line below.
        was_threshold_skipped = should_skip_session(
            user_msgs, metadata["duration_minutes"],
            min_messages=min_messages, min_duration=min_duration,
        )
        if was_threshold_skipped:
            if not snapshots:
                print("[obsidian-brain] session below thresholds, skipping", file=sys.stderr)
                _append_sessionend_log(
                    project=metadata.get("project") or _project_slug_for_log(cwd),
                    session_id=session_id,
                    outcome=_Outcome.SKIPPED_BELOW_THRESHOLD,
                    msgs=len(user_msgs),
                    dur_min=float(metadata.get("duration_minutes", 0.0)),
                    detail="duration check",
                )
                return
            print(
                f"[obsidian-brain] below thresholds but {len(snapshots)} snapshot(s) exist — "
                "writing session note anyway as anchor",
                file=sys.stderr,
            )

        # 7. Detect resumed session
        # Pass the authoritative cwd from hook_input so the project_path filter
        # uses Claude Code's truth-of-record rather than os.getcwd(), which can
        # drift if anything chdir'd inside the hook process.
        resumed = is_resumed_session(vault_path, sessions_folder, session_id, cwd=cwd)
        if resumed:
            print(f"[obsidian-brain] resumed session detected", file=sys.stderr)

        # 8. Build filename
        # Use _first_seen_date so insights saved during the session and the
        # session note written here resolve to the same basename even when
        # the session crosses midnight or is resumed across calendar days.
        date_str = obsidian_utils._first_seen_date(session_id)
        project_slug = slugify(metadata.get("project", "session"))
        filename = make_filename(date_str, project_slug, session_id)

        # 9. Extract tool usage details and write raw note FIRST
        tool_uses = extract_tool_uses(messages)
        raw_body = build_raw_fallback(user_msgs, metadata, assistant_msgs=assistant_msgs, tool_uses=tool_uses, config=config)
        raw_content = _build_note(session_id, metadata, raw_body, resumed=resumed)
        write_err = write_vault_note(vault_path, sessions_folder, filename, raw_content)
        if write_err is not None:
            print(f"[obsidian-brain] failed to write raw note: {write_err}", file=sys.stderr)
            _append_sessionend_log(
                project=metadata.get("project") or _project_slug_for_log(cwd),
                session_id=session_id,
                outcome=_Outcome.WRITE_FAILED,
                msgs=len(user_msgs),
                dur_min=float(metadata.get("duration_minutes", 0.0)),
                detail=f"{write_err}; target={Path(vault_path) / sessions_folder / filename}",
            )
            return
        print("[obsidian-brain] raw note written (summarization deferred to /recall)", file=sys.stderr)
        _append_sessionend_log(
            project=metadata.get("project") or _project_slug_for_log(cwd),
            session_id=session_id,
            outcome=_Outcome.OK_RAW_NOTE_ONLY,
            msgs=len(user_msgs),
            dur_min=float(metadata.get("duration_minutes", 0.0)),
            detail="snapshot-bypass" if (was_threshold_skipped and snapshots) else "",
        )
    finally:
        # Run cache cleanup regardless of how _run() exits so /tmp does not
        # accumulate stale cache files on any SessionEnd outcome — including
        # threshold skips, missing config, auto_log_disabled, or errors.
        _cleanup_session_cache(session_id)


if __name__ == "__main__":
    main()
