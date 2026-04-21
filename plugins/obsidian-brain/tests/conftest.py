# tests/conftest.py
"""Shared fixtures for obsidian-brain test suite."""

import json
import os
import sys

import pytest

# Add hooks/ to sys.path so test modules can import obsidian_utils etc.
_HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_HOOKS_DIR))

# Add repo root to sys.path so tests can use the `hooks.<module>` package form
# (in addition to the bare `obsidian_utils` form used by older tests).
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(_REPO_ROOT))


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temp vault with sessions and insights directories."""
    sessions = tmp_path / "claude-sessions"
    insights = tmp_path / "claude-insights"
    sessions.mkdir()
    insights.mkdir()
    return tmp_path


@pytest.fixture
def mock_config(tmp_vault, monkeypatch):
    """Patch load_config() to return config pointing at tmp_vault."""
    import obsidian_utils

    config = {
        "vault_path": str(tmp_vault),
        "sessions_folder": "claude-sessions",
        "insights_folder": "claude-insights",
        "dashboards_folder": "claude-dashboards",
        "min_messages": 3,
        "min_duration_minutes": 2,
        "summary_model": "haiku",
        "auto_log_enabled": True,
        "snapshot_on_compact": True,
        "snapshot_on_clear": True,
    }
    monkeypatch.setattr(obsidian_utils, "load_config", lambda: config)
    return config


@pytest.fixture
def sample_session_note(tmp_vault):
    """Create a session note with valid frontmatter + summary sections."""
    note_path = tmp_vault / "claude-sessions" / "2026-04-10-test-project-abcd.md"
    note_path.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-10\n"
        "session_id: test-session-id-1234\n"
        "project: test-project\n"
        'project_path: "/tmp/test-project"\n'
        'git_branch: "feature/test"\n'
        "duration_minutes: 30.5\n"
        "tags:\n"
        "  - claude/session\n"
        "  - claude/project/test-project\n"
        "  - claude/auto\n"
        "status: summarized\n"
        "---\n"
        "\n"
        "# Session: test-project (feature/test)\n"
        "\n"
        "## Summary\n"
        "Implemented the frobulator widget with TDD approach.\n"
        "\n"
        "## Key Decisions\n"
        "- Used factory pattern for widget creation.\n"
        "\n"
        "## Changes Made\n"
        "- `src/frobulator.py` — new widget implementation\n"
        "\n"
        "## Errors Encountered\n"
        "None.\n"
        "\n"
        "## Open Questions / Next Steps\n"
        "- [ ] Add integration tests for frobulator\n"
        "- [ ] Review PR #42\n",
        encoding="utf-8",
    )
    return note_path


@pytest.fixture
def sample_unsummarized_note(tmp_vault):
    """Create a note with status: auto-logged and placeholder summary."""
    note_path = tmp_vault / "claude-sessions" / "2026-04-10-test-project-ef01.md"
    note_path.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-10\n"
        "session_id: unsummarized-session-id\n"
        "project: test-project\n"
        'project_path: "/tmp/test-project"\n'
        'git_branch: "develop"\n'
        "duration_minutes: 15.0\n"
        "tags:\n"
        "  - claude/session\n"
        "  - claude/project/test-project\n"
        "  - claude/auto\n"
        "status: auto-logged\n"
        "---\n"
        "\n"
        "# Session: test-project (develop)\n"
        "\n"
        "## Summary\n"
        "Session in **test-project** (15.0 min). "
        "AI summary unavailable \u2014 raw extraction below.\n"
        "\n"
        "## Conversation (raw)\n"
        "**User:** hello\n"
        "**Assistant:** hi there\n",
        encoding="utf-8",
    )
    return note_path


@pytest.fixture
def sample_jsonl(tmp_path):
    """Create a minimal JSONL transcript with user/assistant messages."""
    jsonl_path = tmp_path / "transcript.jsonl"
    entries = [
        {
            "type": "user",
            "timestamp": "2026-04-10T10:00:00Z",
            "message": {"role": "user", "content": "Fix the login bug"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-10T10:01:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll look at the login handler."},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/src/login.py"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-04-10T10:02:00Z",
            "message": {"role": "user", "content": "Great, now deploy it"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-10T10:05:00Z",
            "message": {
                "role": "assistant",
                "content": "Done. The fix is deployed.",
            },
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return jsonl_path
