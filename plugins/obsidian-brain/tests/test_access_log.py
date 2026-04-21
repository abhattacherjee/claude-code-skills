"""Tests for access_log table, log_access(), and batch_activations()."""

import math
import sqlite3
import time

import pytest

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


class TestAccessLogSchema:
    def test_ensure_index_creates_access_log_table(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "access_log" in tables

    def test_access_log_has_correct_columns(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(access_log)").fetchall()}
        conn.close()
        assert cols == {"id", "note_path", "timestamp", "context_type", "project"}

    def test_access_log_indexes_exist(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        indexes = {row[1] for row in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='access_log'"
        ).fetchall()}
        conn.close()
        assert "idx_access_note" in indexes
        assert "idx_access_time" in indexes


class TestLogAccess:
    def test_log_access_inserts_row(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/note.md", "recall", "test-project")
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM access_log").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][1] == "/vault/note.md"
        assert rows[0][3] == "recall"
        assert rows[0][4] == "test-project"

    def test_log_access_records_current_timestamp(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        before = time.time()
        vault_index.log_access(db_path, "/vault/note.md", "search")
        after = time.time()
        conn = sqlite3.connect(db_path)
        ts = conn.execute("SELECT timestamp FROM access_log").fetchone()[0]
        conn.close()
        assert before <= ts <= after

    def test_log_access_project_optional(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/note.md", "search")
        conn = sqlite3.connect(db_path)
        project = conn.execute("SELECT project FROM access_log").fetchone()[0]
        conn.close()
        assert project is None

    def test_log_access_multiple_entries(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/note.md", "recall", "proj")
        vault_index.log_access(db_path, "/vault/note.md", "search", "proj")
        vault_index.log_access(db_path, "/vault/other.md", "ask", "proj")
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
        note_count = conn.execute(
            "SELECT COUNT(*) FROM access_log WHERE note_path = ?",
            ("/vault/note.md",)
        ).fetchone()[0]
        conn.close()
        assert count == 3
        assert note_count == 2

    def test_log_access_does_not_raise_on_bad_db(self, tmp_path):
        db_path = str(tmp_path / "nonexistent.db")
        vault_index.log_access(db_path, "/vault/note.md", "recall")


class TestBatchActivations:
    def test_empty_paths_returns_empty_dict(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        result = vault_index.batch_activations(db_path, [])
        assert result == {}

    def test_no_accesses_returns_zero_activation(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        result = vault_index.batch_activations(db_path, ["/vault/note.md"])
        assert result == {"/vault/note.md": 0.0}

    def test_single_recent_access_positive_activation(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/note.md", "recall")
        result = vault_index.batch_activations(db_path, ["/vault/note.md"])
        assert result["/vault/note.md"] > 0.0

    def test_more_accesses_higher_activation(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/a.md", "recall")
        vault_index.log_access(db_path, "/vault/b.md", "recall")
        vault_index.log_access(db_path, "/vault/b.md", "search")
        vault_index.log_access(db_path, "/vault/b.md", "ask")
        result = vault_index.batch_activations(db_path, ["/vault/a.md", "/vault/b.md"])
        assert result["/vault/b.md"] > result["/vault/a.md"]

    def test_multiple_notes_independent(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        vault_index.log_access(db_path, "/vault/a.md", "recall")
        vault_index.log_access(db_path, "/vault/b.md", "search")
        result = vault_index.batch_activations(
            db_path, ["/vault/a.md", "/vault/b.md", "/vault/c.md"]
        )
        assert len(result) == 3
        assert result["/vault/a.md"] > 0.0
        assert result["/vault/b.md"] > 0.0
        assert result["/vault/c.md"] == 0.0

    def test_activation_formula_matches_actr(self, tmp_vault):
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        conn = sqlite3.connect(db_path)
        now = time.time()
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type) VALUES (?, ?, ?)",
            ("/vault/note.md", now - 60, "recall"),
        )
        conn.execute(
            "INSERT INTO access_log (note_path, timestamp, context_type) VALUES (?, ?, ?)",
            ("/vault/note.md", now - 3600, "search"),
        )
        conn.commit()
        conn.close()
        result = vault_index.batch_activations(db_path, ["/vault/note.md"])
        activation = result["/vault/note.md"]
        expected = math.log(60 ** (-0.5) + 3600 ** (-0.5))
        assert abs(activation - expected) < 0.1

    def test_bad_db_returns_zeros(self, tmp_path):
        db_path = str(tmp_path / "nonexistent.db")
        result = vault_index.batch_activations(db_path, ["/vault/note.md"])
        assert result == {"/vault/note.md": 0.0}


class TestAccessLoggingIntegration:
    def test_search_vault_logs_access_for_results(self, tmp_vault):
        """search_vault() logs access for each returned result."""
        note = tmp_vault / "claude-sessions" / "2026-04-15-test-abcd.md"
        _write_note(note, {
            "type": "claude-session",
            "date": "2026-04-15",
            "project": "test",
            "status": "summarized",
        }, body="authentication login bug fix")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
        results = vault_index.search_vault(db_path, "authentication login")
        assert len(results) >= 1
        conn = sqlite3.connect(db_path)
        access_rows = conn.execute("SELECT note_path, context_type FROM access_log").fetchall()
        conn.close()
        accessed_paths = {row[0] for row in access_rows}
        assert str(note) in accessed_paths
        assert all(row[1] == "search" for row in access_rows)

    def test_query_related_notes_logs_access(self, tmp_vault):
        """query_related_notes() logs access for returned results."""
        note = tmp_vault / "claude-insights" / "2026-04-15-test-insight-1234.md"
        _write_note(note, {
            "type": "claude-insight",
            "date": "2026-04-15",
            "project": "test",
            "source_session": "session-abc",
            "status": "active",
        }, body="Important insight about testing")
        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path)
        results = vault_index.query_related_notes(
            db_path, "test", session_ids=["session-abc"],
            session_tags=[], session_summary=""
        )
        assert len(results) >= 1
        conn = sqlite3.connect(db_path)
        access_rows = conn.execute("SELECT note_path, context_type FROM access_log").fetchall()
        conn.close()
        accessed_paths = {row[0] for row in access_rows}
        assert str(note) in accessed_paths
        assert all(row[1] == "related" for row in access_rows)
