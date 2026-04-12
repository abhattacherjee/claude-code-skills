from obsidian_context_snapshot import _build_snapshot_body, _build_snapshot_note


def test_build_snapshot_body():
    user_msgs = ["Fix the bug", "Deploy it", "Check logs"]
    metadata = {
        "project": "test-project",
        "git_branch": "feature/test",
        "duration_minutes": 25.0,
        "errors": ["ImportError: no module named foo"],
        "files_touched": ["src/main.py"],
    }
    body = _build_snapshot_body(user_msgs, metadata, "compact")
    assert "test-project" in body
    assert "compact" in body
    assert "3 user message(s)" in body
    assert "Fix the bug" in body
    assert "feature/test" in body
    assert "25.0 min" in body
    assert "ImportError" in body
    assert "src/main.py" in body


def test_build_snapshot_note_frontmatter():
    metadata = {
        "project": "test-project",
        "git_branch": "main",
        "duration_minutes": 10,
        "errors": [],
        "files_touched": [],
    }
    body = "## What was happening\nStuff.\n"
    note = _build_snapshot_note("sid-123", metadata, body, "compact")
    assert "type: claude-snapshot" in note
    assert "claude/snapshot" in note
    assert "claude/project/test-project" in note
    assert "trigger: compact" in note
    assert "# Context Snapshot: test-project (main)" in note


def test_build_snapshot_body_truncation():
    long_msg = "x" * 500
    metadata = {
        "project": "test",
        "git_branch": "",
        "duration_minutes": 0,
        "errors": [],
        "files_touched": [],
    }
    body = _build_snapshot_body([long_msg], metadata, "clear")
    lines = body.split("\n")
    msg_lines = [l for l in lines if l.startswith("1. ")]
    assert len(msg_lines) == 1
    assert len(msg_lines[0]) <= 310  # 300 chars + "1. " prefix
