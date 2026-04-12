"""Tests for hooks/vault_index.py — SQLite + FTS5 vault index."""

import os
import sqlite3
import time
from unittest.mock import patch

import pytest

import vault_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Commit 1: Schema + ensure_index + sync engine
# ---------------------------------------------------------------------------


class TestEnsureIndex:
    def test_ensure_index_creates_tables(self, tmp_vault):
        """Empty vault creates notes + notes_fts tables."""
        db_path = str(tmp_vault / "test.db")
        result = vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )
        assert result == db_path

        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            ).fetchall()
        }
        conn.close()

        assert "notes" in tables
        # FTS5 tables show up with suffixes but the base name should be present
        assert any("notes_fts" in t for t in tables)

    def test_ensure_index_returns_db_path(self, tmp_vault):
        """Returns path ending in obsidian-brain-vault.db when no override."""
        db_path = str(tmp_vault / "obsidian-brain-vault.db")
        result = vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions"], db_path=db_path
        )
        assert result.endswith("obsidian-brain-vault.db")


class TestInsertAndSync:
    def test_insert_single_note(self, tmp_vault):
        """Index a note, verify all columns."""
        note = tmp_vault / "claude-sessions" / "2026-04-10-myproj-abcd.md"
        _write_note(
            note,
            {
                "type": "claude-session",
                "date": "2026-04-10",
                "project": "myproj",
                "source_session": "sess-1234",
                "source_session_note": "[[2026-04-09-myproj-prev.md]]",
                "tags": ["claude/session", "claude/project/myproj"],
                "status": "summarized",
            },
            body="# Session: myproj\n\nDid some work on the widget.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM notes").fetchone()
        conn.close()

        assert row is not None
        assert row["type"] == "claude-session"
        assert row["project"] == "myproj"
        assert row["tags"] == "claude/session,claude/project/myproj"
        assert row["title"] == "Session: myproj"
        assert row["source_session"] == "sess-1234"
        assert row["source_note"] == "2026-04-09-myproj-prev.md"
        assert row["size"] > 0

    def test_mtime_skip(self, tmp_vault):
        """Unchanged file not re-read on second ensure_index."""
        note = tmp_vault / "claude-sessions" / "2026-04-10-proj-skip.md"
        _write_note(
            note,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Session: proj\n\nOriginal body.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Second call — file not changed, open should not be called for parsing
        with patch("builtins.open", wraps=open) as mock_open:
            vault_index.ensure_index(
                str(tmp_vault), ["claude-sessions"], db_path=db_path
            )
            # open() should NOT have been called with the note path for parsing
            # (it may be called for the DB itself by sqlite3)
            note_calls = [
                c
                for c in mock_open.call_args_list
                if len(c.args) > 0 and str(note) in str(c.args[0])
            ]
            assert len(note_calls) == 0, f"Note file was re-read: {note_calls}"

    def test_update_changed_file(self, tmp_vault):
        """Modified file (bumped mtime) re-indexed with new title."""
        note = tmp_vault / "claude-sessions" / "2026-04-10-proj-upd.md"
        _write_note(
            note,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Session: Original Title\n\nBody.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Modify file (need mtime to change)
        time.sleep(0.05)
        _write_note(
            note,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Session: Updated Title\n\nNew body.",
        )

        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT title FROM notes").fetchone()
        conn.close()

        assert row["title"] == "Session: Updated Title"

    def test_delete_removed_file(self, tmp_vault):
        """Deleted vault file removed from index."""
        note = tmp_vault / "claude-sessions" / "2026-04-10-proj-del.md"
        _write_note(
            note,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Session: To Delete\n\nBody.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Delete file
        note.unlink()

        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.close()

        assert count == 0


# ---------------------------------------------------------------------------
# Commit 2: rebuild_index + index_note
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def test_rebuild_index_clean_slate(self, tmp_vault):
        """Stale entries removed, fresh files indexed."""
        note1 = tmp_vault / "claude-sessions" / "note1.md"
        _write_note(
            note1,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Note 1\n\nBody one.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        # Now delete note1, add note2, rebuild
        note1.unlink()
        note2 = tmp_vault / "claude-sessions" / "note2.md"
        _write_note(
            note2,
            {"type": "claude-insight", "date": "2026-04-11", "project": "proj"},
            body="# Note 2\n\nBody two.",
        )

        stats = vault_index.rebuild_index(
            str(tmp_vault), ["claude-sessions"], db_path=db_path
        )

        assert stats["inserted"] == 1
        assert "claude-insight" in stats["by_type"]

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT path FROM notes").fetchall()
        conn.close()

        paths = [r["path"] for r in rows]
        assert len(paths) == 1
        assert "note2.md" in paths[0]


class TestIndexNote:
    def test_index_note_single_file(self, tmp_vault):
        """Single-file upsert into existing DB."""
        db_path = str(tmp_vault / "test.db")
        # Create empty DB first
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)

        note = tmp_vault / "claude-insights" / "insight1.md"
        _write_note(
            note,
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "tags": ["claude/insight", "claude/topic/testing"],
            },
            body="# Insight: Testing Patterns\n\nAlways use fixtures.",
        )

        result = vault_index.index_note(db_path, str(note))
        assert result is True

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM notes WHERE type = 'claude-insight'").fetchone()
        conn.close()

        assert row is not None
        assert row["title"] == "Insight: Testing Patterns"


# ---------------------------------------------------------------------------
# Commit 3: search_vault + FTS
# ---------------------------------------------------------------------------


class TestSearchVault:
    def _populate_vault(self, tmp_vault):
        """Create several notes for search testing."""
        notes = [
            (
                "claude-sessions/sess1.md",
                {
                    "type": "claude-session",
                    "date": "2026-04-10",
                    "project": "alpha",
                    "tags": ["claude/session"],
                },
                "# Session: Alpha Sprint\n\nImplemented authentication module with JWT tokens.",
            ),
            (
                "claude-sessions/sess2.md",
                {
                    "type": "claude-session",
                    "date": "2026-04-11",
                    "project": "beta",
                    "tags": ["claude/session"],
                },
                "# Session: Beta Refactor\n\nRefactored database layer for performance.",
            ),
            (
                "claude-insights/insight1.md",
                {
                    "type": "claude-insight",
                    "date": "2026-04-10",
                    "project": "alpha",
                    "tags": ["claude/insight", "claude/topic/auth"],
                },
                "# Insight: JWT Best Practices\n\nAlways rotate JWT signing keys.",
            ),
        ]
        for rel_path, fm, body in notes:
            path = tmp_vault / rel_path
            _write_note(path, fm, body)

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )
        return db_path

    def test_fts_search_returns_relevant_results(self, tmp_vault):
        """FTS search returns matching notes ranked."""
        db_path = self._populate_vault(tmp_vault)

        results = vault_index.search_vault(db_path, "JWT authentication")
        assert len(results) >= 1
        # JWT notes should be in results
        titles = [r["title"] for r in results]
        assert any("JWT" in t for t in titles)

    def test_search_vault_with_project_filter(self, tmp_vault):
        """Project filter narrows results."""
        db_path = self._populate_vault(tmp_vault)

        results = vault_index.search_vault(db_path, "session", project="alpha")
        for r in results:
            assert r["project"] == "alpha"

    def test_search_vault_nonexistent_db(self, tmp_path):
        """Non-existent DB returns empty list."""
        results = vault_index.search_vault(
            str(tmp_path / "nonexistent.db"), "test"
        )
        assert results == []

    def test_ensure_index_syncs_new_files_before_search(self, tmp_vault):
        """ensure_index() picks up files added after initial index build."""
        db = str(tmp_vault / "test.db")
        # Build initial index with one note
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-12-old.md",
            {"type": "claude-insight", "date": "2026-04-12", "project": "test"},
            "# Old Insight\n\nExisting content about caching.",
        )
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db)

        # Add a new note AFTER initial index
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-12-new.md",
            {"type": "claude-insight", "date": "2026-04-12", "project": "test"},
            "# Fresh Discovery\n\nBrand new insight about performance tuning.",
        )

        # Without re-syncing, search won't find it
        results_stale = vault_index.search_vault(db, "performance tuning")
        assert not any("Fresh" in r["title"] for r in results_stale)

        # After ensure_index (lazy sync), the new note is found
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db)
        results_fresh = vault_index.search_vault(db, "performance tuning")
        assert any("Fresh" in r["title"] for r in results_fresh)

    def test_search_vault_hyphenated_query(self, tmp_vault):
        """Hyphenated queries find notes containing both words (not NOT)."""
        # Create a note with "maintain" and "catalog" in body
        _write_note(
            tmp_vault / "claude-insights" / "maintain-catalogs.md",
            {"type": "claude-insight", "date": "2026-04-12", "project": "test"},
            "# Maintain Catalogs\n\nAlways use /maintain-catalogs for catalog additions.",
        )
        db = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db
        )

        # "maintain-catalog" should find the note (not exclude it via NOT)
        results = vault_index.search_vault(db, "maintain-catalog")
        assert len(results) >= 1
        assert any("Maintain" in r["title"] for r in results)

    def test_sanitize_fts_query_strips_hyphens(self):
        """_sanitize_fts_query replaces hyphens with spaces to avoid FTS5 NOT."""
        from vault_index import _sanitize_fts_query

        result = _sanitize_fts_query("maintain-catalog")
        assert "-" not in result
        assert '"maintain"' in result
        assert '"catalog"' in result


# ---------------------------------------------------------------------------
# Commit 4: extract_keywords + query_related_notes + corrupt DB
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_extract_keywords(self):
        """Removes stopwords and short words, returns <= 8."""
        text = (
            "Implemented the authentication module with JWT tokens "
            "and added comprehensive test coverage for the login flow. "
            "The authentication system uses rotating keys."
        )
        keywords = vault_index.extract_keywords(text)
        assert len(keywords) <= 8
        assert len(keywords) > 0
        # "the", "and", "with" etc. should be excluded
        assert "the" not in keywords
        assert "and" not in keywords
        assert "with" not in keywords
        # Short words like "an", "it" excluded
        assert "an" not in keywords
        # "authentication" should appear (it's repeated)
        assert "authentication" in keywords


class TestQueryRelatedNotes:
    def test_query_related_notes_layered_ranking(self, tmp_vault):
        """Fills slots: backlinks first, then tags, then FTS."""
        # Create notes with different relationship types
        # Note linked via session_id (backlink)
        backlink_note = tmp_vault / "claude-insights" / "backlink.md"
        _write_note(
            backlink_note,
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "source_session": "sess-A",
                "tags": ["claude/insight"],
            },
            body="# Insight: Backlinked\n\nThis is linked via source_session.",
        )

        # Note linked via topic tag
        tag_note = tmp_vault / "claude-insights" / "tagged.md"
        _write_note(
            tag_note,
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "tags": ["claude/insight", "claude/topic/testing"],
            },
            body="# Insight: Tagged\n\nThis shares a topic tag.",
        )

        # Note findable via FTS only
        fts_note = tmp_vault / "claude-insights" / "fts_only.md"
        _write_note(
            fts_note,
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "tags": ["claude/insight"],
            },
            body="# Insight: FTS Match\n\nThis note discusses frobulator optimization.",
        )

        db_path = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        results = vault_index.query_related_notes(
            db_path,
            project="proj",
            session_ids=["sess-A"],
            session_tags=["claude/topic/testing"],
            session_summary="We worked on frobulator optimization and testing patterns.",
            limit=20,
        )

        assert len(results) >= 1

        # Check layer ordering: backlinks should come before tags, tags before FTS
        layers = [r["layer"] for r in results]
        layer_order = {"backlink": 0, "tag": 1, "fts": 2}

        # Verify layers are in correct order (backlink < tag < fts)
        for i in range(len(layers) - 1):
            assert layer_order.get(layers[i], 99) <= layer_order.get(
                layers[i + 1], 99
            ), f"Layer order violated: {layers}"


class TestCorruptDB:
    def test_corrupt_db_auto_recovery(self, tmp_vault):
        """Truncated DB triggers auto-rebuild on ensure_index."""
        note = tmp_vault / "claude-sessions" / "note.md"
        _write_note(
            note,
            {"type": "claude-session", "date": "2026-04-10", "project": "proj"},
            body="# Session: Recovery Test\n\nBody.",
        )

        db_path = str(tmp_vault / "test.db")

        # Create a corrupt DB file
        with open(db_path, "wb") as f:
            f.write(b"this is not a valid sqlite database")

        # ensure_index should recover by deleting and recreating
        result = vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions"], db_path=db_path
        )
        assert result == db_path

        # Verify the DB is now valid and has the note
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.close()
        assert count == 1


# ---------------------------------------------------------------------------
# Additional edge case tests (from review)
# ---------------------------------------------------------------------------


class TestIndexNoteFailurePaths:
    """index_note() returns False for various failure modes."""

    def test_index_note_nonexistent_db(self, tmp_vault):
        result = vault_index.index_note("/tmp/nonexistent.db", "/tmp/some.md")
        assert result is False

    def test_index_note_nonexistent_note(self, tmp_vault):
        db = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db)
        result = vault_index.index_note(db, "/tmp/nonexistent-note.md")
        assert result is False

    def test_index_note_no_frontmatter(self, tmp_vault):
        db = str(tmp_vault / "test.db")
        vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db)
        note = tmp_vault / "claude-sessions" / "plain.md"
        note.write_text("Just plain text, no frontmatter.", encoding="utf-8")
        result = vault_index.index_note(db, str(note))
        assert result is False


class TestLayeredRankingStrong:
    """Stronger assertions on layered ranking order."""

    def test_all_three_layers_present(self, tmp_vault):
        """All three layers contribute results and maintain order."""
        # Layer 1: backlink
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-10-bl.md",
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "source_session": "sess-X",
                "tags": ["claude/insight"],
            },
            "# Backlinked\n\nDirect provenance.",
        )
        # Layer 2: tag match (no backlink)
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-10-tg.md",
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "tags": ["claude/insight", "claude/topic/perf"],
            },
            "# Tagged\n\nRelated by topic.",
        )
        # Layer 3: FTS only (no backlink, no shared tag)
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-10-kw.md",
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "tags": ["claude/insight"],
            },
            "# Keyword\n\nOptimization and performance caching patterns.",
        )

        db = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db
        )

        results = vault_index.query_related_notes(
            db_path=db,
            project="proj",
            session_ids=["sess-X"],
            session_tags=["claude/topic/perf"],
            session_summary="Working on caching and optimization performance",
            limit=20,
        )

        assert len(results) == 3
        layers = [r["layer"] for r in results]
        assert layers[0] == "backlink"
        assert layers[1] == "tag"
        assert layers[2] == "fts"
        # No duplicates
        paths = [r["path"] for r in results]
        assert len(set(paths)) == 3

    def test_deduplication_across_layers(self, tmp_vault):
        """A note matching Layer 1 is not duplicated in Layer 2."""
        _write_note(
            tmp_vault / "claude-insights" / "2026-04-10-both.md",
            {
                "type": "claude-insight",
                "date": "2026-04-10",
                "project": "proj",
                "source_session": "sess-Y",
                "tags": ["claude/insight", "claude/topic/auth"],
            },
            "# Both Layers\n\nMatches backlink and tag.",
        )

        db = str(tmp_vault / "test.db")
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db
        )

        results = vault_index.query_related_notes(
            db_path=db,
            project="proj",
            session_ids=["sess-Y"],
            session_tags=["claude/topic/auth"],
            session_summary="authentication patterns",
            limit=20,
        )

        assert len(results) == 1
        assert results[0]["layer"] == "backlink"  # found in Layer 1, not duplicated


class TestBuildContextBriefFallback:
    """build_context_brief() falls back to file scan when vault index is unavailable."""

    def test_fallback_when_vault_index_import_fails(self, tmp_vault, mock_config, monkeypatch):
        """Insights still appear when vault_index module is missing."""
        import obsidian_utils

        # Create an insight note
        insight = tmp_vault / "claude-insights" / "2026-04-10-test-insight.md"
        insight.write_text(
            "---\n"
            "type: claude-insight\n"
            "date: 2026-04-10\n"
            "project: test-project\n"
            "tags:\n"
            "  - claude/insight\n"
            "---\n\n"
            "# Fallback Insight\n\n"
            "This should appear via file scan fallback.\n",
            encoding="utf-8",
        )

        # Stub session ID and cache
        monkeypatch.setattr(obsidian_utils, "_get_session_id_fast", lambda: "test-sid")
        monkeypatch.setattr(obsidian_utils, "cache_get", lambda *a: None)
        monkeypatch.setattr(obsidian_utils, "cache_set", lambda *a: None)

        # Block vault_index import by removing it from sys.modules and path
        import sys as _sys
        monkeypatch.delitem(_sys.modules, "vault_index", raising=False)
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "vault_index":
                raise ImportError("vault_index not available")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        brief = obsidian_utils.build_context_brief(
            str(tmp_vault), "claude-sessions", "claude-insights", "test-project",
        )

        assert "Fallback Insight" in brief
