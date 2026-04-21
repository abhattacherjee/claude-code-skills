import datetime
import io
import json
import re

import hooks.obsidian_context_snapshot as snap


def test_snapshot_frontmatter_has_status_and_source_session_note():
    session_id = "abc-def-ghi"
    metadata = {"project": "demo", "git_branch": "develop"}
    note = snap._build_snapshot_note(
        session_id,
        metadata,
        body="## What was happening\nsome body\n",
        trigger="compact",
    )
    assert "\nstatus: auto-logged\n" in note
    assert re.search(
        r'\nsource_session_note: "\[\[\d{4}-\d{2}-\d{2}-demo-[a-f0-9]{4}\]\]"\n',
        note,
    )


def test_run_writes_file_with_hhmmss_suffix(tmp_path, monkeypatch):
    """_run() integrates datetime.now() into the snapshot filename."""

    # Freeze datetime so the suffix is deterministic
    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 18, 14, 30, 27)

    monkeypatch.setattr(snap.datetime, "datetime", FrozenDatetime)

    # Set up a vault
    vault = tmp_path / "vault"
    sessions = vault / "claude-sessions"
    sessions.mkdir(parents=True)

    # Stub load_config — the real one reads ~/.claude/obsidian-brain-config.json
    # via Path.home() bound at import time, so $HOME monkeypatching won't reach it.
    monkeypatch.setattr(
        snap,
        "load_config",
        lambda: {
            "vault_path": str(vault),
            "sessions_folder": "claude-sessions",
            "snapshot_on_compact": True,
        },
    )

    # transcript_path containment check uses os.path.expanduser("~/.claude/projects")
    # which still reads $HOME at call time, so point it at tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))

    # Stub transcript-parsing helpers so _run() doesn't need a real JSONL
    monkeypatch.setattr(
        snap,
        "read_transcript",
        lambda path: [{"type": "user", "message": {"content": "hello"}}],
    )
    monkeypatch.setattr(snap, "extract_user_messages", lambda msgs: ["hello"])
    monkeypatch.setattr(
        snap,
        "extract_session_metadata",
        lambda msgs, cwd: {
            "project": "demo",
            "git_branch": "develop",
            "duration_minutes": 1,
        },
    )

    # transcript_path must sit inside ~/.claude/projects/ to pass the containment check
    projects_dir = tmp_path / ".claude" / "projects" / "demo"
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    stdin_json = json.dumps(
        {
            "session_id": "abc-def-ghi",
            "cwd": str(tmp_path),
            "transcript_path": str(transcript),
            "source": "compact",
        }
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_json))

    snap._run()

    # Exactly one snapshot note should have been written with the HHMMSS suffix
    written = list(sessions.glob("*.md"))
    assert len(written) == 1
    assert written[0].name.endswith("-snapshot-143027.md")
    assert re.match(
        r"2026-04-18-demo-[a-f0-9]{4}-snapshot-143027\.md$",
        written[0].name,
    )


from hooks.obsidian_utils import find_snapshots_for_session
from hooks.obsidian_session_log import _build_note


def _write_snapshot_fixture(sessions_dir, date, project, sid4, hhmmss, session_id):
    path = sessions_dir / f"{date}-{project}-{sid4}-snapshot-{hhmmss}.md"
    path.write_text(
        f"---\ntype: claude-snapshot\ndate: {date}\nsession_id: {session_id}\n"
        f"project: {project}\ntrigger: compact\nstatus: auto-logged\n---\n\n"
        "# Context Snapshot: demo (develop)\n\n## What was happening\nx\n",
        encoding="utf-8",
    )
    return path


def test_find_snapshots_returns_chronological_wikilinks(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    _write_snapshot_fixture(sess, "2026-04-18", "demo", "abcd", "155140", "sess-1")
    _write_snapshot_fixture(sess, "2026-04-18", "demo", "abcd", "143027", "sess-1")
    # Different session
    _write_snapshot_fixture(sess, "2026-04-18", "demo", "abcd", "120000", "sess-2")

    result = find_snapshots_for_session(sess, "sess-1", "2026-04-18", "demo")
    assert result == [
        "[[2026-04-18-demo-abcd-snapshot-143027]]",
        "[[2026-04-18-demo-abcd-snapshot-155140]]",
    ]


def test_build_note_includes_snapshots_list_when_nonempty():
    metadata = {"project": "demo", "git_branch": "develop", "duration_minutes": 42,
                "project_path": "/x", "sessions_folder": "claude-sessions"}
    metadata["snapshots"] = [
        "[[2026-04-18-demo-abcd-snapshot-143027]]",
        "[[2026-04-18-demo-abcd-snapshot-155140]]",
    ]
    note = _build_note("sess-1", metadata, body="content\n")
    assert "\nsnapshots:\n" in note
    assert '  - "[[2026-04-18-demo-abcd-snapshot-143027]]"' in note


def test_build_note_omits_snapshots_list_when_empty():
    metadata = {"project": "demo", "git_branch": "develop", "duration_minutes": 2,
                "project_path": "/x", "sessions_folder": "claude-sessions"}
    note = _build_note("sess-1", metadata, body="content\n")
    assert "snapshots:" not in note  # field fully omitted — tidiness


import hooks.obsidian_session_log as sesslog


def test_session_log_writes_anchor_when_snapshots_exist_despite_low_messages(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    sessions = vault / "claude-sessions"
    sessions.mkdir(parents=True)
    # Pre-create a snapshot for session s1. Date must be today's (or yesterday's)
    # because the hook's early-snapshot glob only scans those two date prefixes
    # to handle midnight-spanning sessions. Hardcoded dates drift out of the
    # window and silently break this test (feedback_time_dependent_test_seeds).
    today = datetime.date.today().isoformat()
    (sessions / f"{today}-demo-abcd-snapshot-143027.md").write_text(
        f"---\ntype: claude-snapshot\ndate: {today}\nsession_id: s1\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )

    # Config with very high min_messages to force the early skip path
    monkeypatch.setattr(sesslog, "load_config", lambda: {
        "vault_path": str(vault),
        "sessions_folder": "claude-sessions",
        "min_messages": 99,  # force early-skip path
        "min_duration_minutes": 0,
        "auto_log_enabled": True,
    })

    # Stub transcript parsing to return exactly 1 user message
    monkeypatch.setattr(sesslog, "read_transcript", lambda path: [
        {"type": "user", "message": {"content": "hello"}},
    ])
    monkeypatch.setattr(sesslog, "extract_user_messages", lambda msgs: ["hello"])
    monkeypatch.setattr(sesslog, "extract_assistant_messages", lambda msgs: [])
    monkeypatch.setattr(sesslog, "extract_tool_uses", lambda msgs: [])
    monkeypatch.setattr(sesslog, "extract_session_metadata", lambda msgs, cwd: {
        "project": "demo", "git_branch": "develop", "duration_minutes": 0,
        "project_path": str(tmp_path), "files_touched": [], "errors": [],
    })
    # Use a cwd whose basename is "demo" so the early glob finds the snapshot.
    demo_cwd = tmp_path / "demo"
    demo_cwd.mkdir()

    # Fake transcript path inside ~/.claude/projects
    projects_dir = tmp_path / ".claude" / "projects" / "demo"
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    stdin_json = json.dumps({
        "session_id": "s1",
        "cwd": str(demo_cwd),
        "transcript_path": str(transcript),
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_json))

    sesslog._run()

    # Assert a session note (not a snapshot) landed in addition to the pre-seeded snapshot
    session_notes = [p for p in sessions.glob("*.md") if "-snapshot-" not in p.name]
    assert len(session_notes) == 1, f"expected anchor session note; found: {[p.name for p in sessions.glob('*.md')]}"
    content = session_notes[0].read_text(encoding="utf-8")
    assert "snapshots:" in content
    assert f"{today}-demo-abcd-snapshot-143027" in content


def test_early_skip_bypass_is_independently_exercised(tmp_path, monkeypatch):
    """Step 5 (message-count skip) must bypass independently of step 6.

    Strategy: use a project directory name that slugifies to match the
    pre-seeded snapshot, but have extract_session_metadata return a
    DIFFERENT canonical project. Then step 4a finds the snapshot (via
    the cwd-derived slug), step 5 bypasses, but step 6a's canonical
    re-glob runs against the wrong project and would return []. If
    step 5 weren't properly checking, the run would skip silently.
    """
    vault = tmp_path / "vault"
    sessions = vault / "claude-sessions"
    sessions.mkdir(parents=True)
    # Date must be today's so the hook's today/yesterday-only snapshot glob
    # can find it (see feedback_time_dependent_test_seeds).
    today = datetime.date.today().isoformat()
    (sessions / f"{today}-demo-abcd-snapshot-143027.md").write_text(
        f"---\ntype: claude-snapshot\ndate: {today}\nsession_id: s1\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sesslog, "load_config", lambda: {
        "vault_path": str(vault),
        "sessions_folder": "claude-sessions",
        "min_messages": 99,          # force step 5 skip
        "min_duration_minutes": 0,
        "auto_log_enabled": True,
    })
    monkeypatch.setattr(sesslog, "read_transcript", lambda path: [
        {"type": "user", "message": {"content": "hi"}},
    ])
    monkeypatch.setattr(sesslog, "extract_user_messages", lambda msgs: ["hi"])
    monkeypatch.setattr(sesslog, "extract_assistant_messages", lambda msgs: [])
    monkeypatch.setattr(sesslog, "extract_tool_uses", lambda msgs: [])
    # Canonical project differs from cwd basename — step 6a re-glob misses
    monkeypatch.setattr(sesslog, "extract_session_metadata", lambda msgs, cwd: {
        "project": "unrelated-project",     # snapshot is under 'demo'
        "git_branch": "develop", "duration_minutes": 0,
        "project_path": str(tmp_path), "files_touched": [], "errors": [],
    })

    # cwd basename slugifies to 'demo' → step 4a glob matches the snapshot
    demo_cwd = tmp_path / "demo"
    demo_cwd.mkdir()
    projects_dir = tmp_path / ".claude" / "projects" / "demo"
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    stdin_json = json.dumps({
        "session_id": "s1",
        "cwd": str(demo_cwd),
        "transcript_path": str(transcript),
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_json))

    sesslog._run()

    # If step 5's bypass works, an anchor session note lands (because early
    # glob found the snapshot). If step 5 weren't bypassing, _run() would
    # have returned after `should_skip_session(user_msgs, 0, ...)` fires.
    session_notes = [p for p in sessions.glob("*.md") if "-snapshot-" not in p.name]
    assert len(session_notes) == 1, (
        f"step 5 early-bypass did not fire; found: "
        f"{[p.name for p in sessions.glob('*.md')]}"
    )


def test_session_log_finds_yesterday_snapshot_across_midnight(tmp_path, monkeypatch):
    """Regression for Copilot PR #43 finding: SessionEnd must scan today AND
    yesterday's date prefix so day-spanning sessions don't lose their
    pre-midnight snapshots' back-references.
    """
    vault = tmp_path / "vault"
    sessions = vault / "claude-sessions"
    sessions.mkdir(parents=True)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    # Seed a snapshot dated yesterday for this session
    yesterday_snap = sessions / f"{yesterday.isoformat()}-demo-abcd-snapshot-235030.md"
    yesterday_snap.write_text(
        f"---\ntype: claude-snapshot\ndate: {yesterday.isoformat()}\n"
        "session_id: s1\nproject: demo\ntrigger: compact\n"
        "status: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sesslog, "load_config", lambda: {
        "vault_path": str(vault),
        "sessions_folder": "claude-sessions",
        "min_messages": 99,  # force bypass-or-skip path
        "min_duration_minutes": 0,
        "auto_log_enabled": True,
    })
    monkeypatch.setattr(sesslog, "read_transcript", lambda path: [
        {"type": "user", "message": {"content": "cross midnight"}},
    ])
    monkeypatch.setattr(sesslog, "extract_user_messages", lambda msgs: ["cross midnight"])
    monkeypatch.setattr(sesslog, "extract_assistant_messages", lambda msgs: [])
    monkeypatch.setattr(sesslog, "extract_tool_uses", lambda msgs: [])
    monkeypatch.setattr(sesslog, "extract_session_metadata", lambda msgs, cwd: {
        "project": "demo", "git_branch": "develop", "duration_minutes": 0,
        "project_path": str(tmp_path), "files_touched": [], "errors": [],
    })

    demo_cwd = tmp_path / "demo"
    demo_cwd.mkdir()
    projects_dir = tmp_path / ".claude" / "projects" / "demo"
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    stdin_json = json.dumps({
        "session_id": "s1",
        "cwd": str(demo_cwd),
        "transcript_path": str(transcript),
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_json))

    sesslog._run()

    # Session note should land (threshold bypass fired because yesterday's
    # snapshot was discovered via the candidate-dates loop) AND its
    # snapshots: list must include yesterday's wikilink.
    session_notes = [p for p in sessions.glob("*.md") if "-snapshot-" not in p.name]
    assert len(session_notes) == 1, (
        f"expected anchor session note across midnight; got: "
        f"{[p.name for p in sessions.glob('*.md')]}"
    )
    content = session_notes[0].read_text(encoding="utf-8")
    assert "snapshots:" in content
    assert yesterday_snap.stem in content, (
        f"yesterday's snapshot not back-referenced in session note:\n{content}"
    )


def test_snapshot_body_emits_last_messages_raw_section():
    """Regression for Copilot PR #43 finding: snapshot bodies must include a
    `## Last messages (raw)` section so `upgrade_unsummarized_note()`'s
    raw-fallback parser can summarize a snapshot without the JSONL transcript.
    """
    metadata = {"project": "demo", "git_branch": "develop", "duration_minutes": 5}
    body = snap._build_snapshot_body(
        user_msgs=["hello there", "does this work?"],
        metadata=metadata,
        trigger="compact",
        assistant_msgs=["yes, hi", "it sure does"],
    )
    # Exact section header the shared fallback parser looks for
    assert "## Last messages (raw)" in body
    # Must contain alternating User/Assistant lines in that section
    raw_tail = body.split("## Last messages (raw)", 1)[1]
    assert "**User:** hello there" in raw_tail
    assert "**Assistant:** yes, hi" in raw_tail
    assert "**User:** does this work?" in raw_tail
    assert "**Assistant:** it sure does" in raw_tail
