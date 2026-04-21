"""Tests for importance column on notes table and importance parsing."""

import sqlite3
from unittest.mock import patch

import pytest

import obsidian_utils
import vault_index


def _write_note(path, frontmatter: dict, body: str = ""):
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestImportanceColumn:
    def test_notes_table_has_importance_column(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
        conn.close()
        assert "importance" in cols

    def test_importance_defaults_to_5(self, tmp_vault):
        note = tmp_vault / "claude-sessions" / "2026-04-15-test-a1b2.md"
        _write_note(note, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="Some content")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT importance FROM notes").fetchone()
        conn.close()
        assert row[0] == 5

    def test_importance_migration_on_existing_db(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE notes ("
            "  path TEXT PRIMARY KEY, type TEXT NOT NULL, date TEXT, project TEXT,"
            "  title TEXT, source_session TEXT, source_note TEXT, tags TEXT,"
            "  status TEXT, mtime REAL NOT NULL, size INTEGER, body TEXT DEFAULT ''"
            ")"
        )
        conn.execute(
            "INSERT INTO notes (path, type, mtime) VALUES (?, ?, ?)",
            ("/old/note.md", "claude-session", 1000.0),
        )
        conn.commit()
        conn.close()
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
        importance = conn.execute(
            "SELECT importance FROM notes WHERE path = ?", ("/old/note.md",)
        ).fetchone()[0]
        conn.close()
        assert "importance" in cols
        assert importance == 5

    def test_update_importance(self, tmp_vault):
        note = tmp_vault / "claude-sessions" / "2026-04-15-test-c3d4.md"
        _write_note(note, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="Important work")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE notes SET importance = ? WHERE path = ?", (9, str(note)))
        conn.commit()
        row = conn.execute("SELECT importance FROM notes WHERE path = ?", (str(note),)).fetchone()
        conn.close()
        assert row[0] == 9


class TestImportancePreservedOnReindex:
    def test_ensure_index_preserves_importance(self, tmp_vault):
        """Re-indexing does not reset importance to default."""
        note = tmp_vault / "claude-sessions" / "2026-04-15-test-preserve-a1b2.md"
        _write_note(note, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="Important security audit work")

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Set importance to 9
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE notes SET importance = 9 WHERE path = ?", (str(note),))
        conn.commit()
        conn.close()

        # Re-index (simulates next ensure_index call)
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Verify importance is still 9, not reset to 5
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT importance FROM notes WHERE path = ?", (str(note),)).fetchone()
        conn.close()
        assert row[0] == 9


class TestImportanceParsing:
    def test_parse_importance_from_summary(self):
        summary = "## Summary\nDid work.\n\n## Importance\n7\n"
        assert obsidian_utils.parse_importance(summary) == 7

    def test_parse_importance_with_explanation(self):
        summary = "## Importance\n8 - Major architectural decision\n"
        assert obsidian_utils.parse_importance(summary) == 8

    def test_parse_importance_missing_returns_default(self):
        summary = "## Summary\nDid work.\n"
        assert obsidian_utils.parse_importance(summary) == 5

    def test_parse_importance_invalid_returns_default(self):
        summary = "## Importance\nhigh\n"
        assert obsidian_utils.parse_importance(summary) == 5

    def test_parse_importance_clamps_to_range(self):
        assert obsidian_utils.parse_importance("## Importance\n0\n") == 1
        assert obsidian_utils.parse_importance("## Importance\n15\n") == 10

    def test_parse_importance_from_subagent_line(self):
        summary = "## Summary\nDid work.\n\nIMPORTANCE: 6\n"
        assert obsidian_utils.parse_importance(summary) == 6


class TestImportanceWriteBack:
    def test_upgrade_note_writes_importance_to_db(self, tmp_vault, mock_config):
        """upgrade_note_with_summary() writes parsed importance to vault index DB."""
        note_path = str(tmp_vault / "claude-sessions" / "2026-04-15-test-wb-a1b2.md")
        # Write a raw unsummarized note
        (tmp_vault / "claude-sessions" / "2026-04-15-test-wb-a1b2.md").write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-15\n"
            "session_id: wb-test-session\n"
            "project: test-project\n"
            "status: auto-logged\n"
            "tags:\n"
            "  - claude/session\n"
            "---\n"
            "\n"
            "# Session: test-project\n"
            "\n"
            "## Summary\n"
            "AI summary unavailable\n"
            "\n"
            "## Conversation (raw)\n"
            "**User:** test\n",
            encoding="utf-8",
        )

        # Index the vault so the note is in the DB
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Patch _default_db_path to point to our test DB
        with patch.object(vault_index, "_default_db_path", return_value=db_path):
            summary = (
                "## Summary\nDid important security work.\n\n"
                "## Key Decisions\nNone noted.\n\n"
                "## Changes Made\nNone noted.\n\n"
                "## Errors Encountered\nNone.\n\n"
                "## Open Questions / Next Steps\nNone.\n\n"
                "IMPORTANCE: 9\n"
            )
            result = obsidian_utils.upgrade_note_with_summary(
                note_path, summary, str(tmp_vault), "claude-sessions", "test-project"
            )
            assert not result.startswith("Failed:")

        # Verify importance was written to DB
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT importance FROM notes WHERE path = ?", (note_path,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 9
