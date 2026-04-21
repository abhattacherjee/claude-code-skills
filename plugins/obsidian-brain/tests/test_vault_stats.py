"""Tests for hooks/vault_stats.py — vault statistics module."""

import json
import os
import sqlite3
import time

import pytest

import vault_index
import vault_stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(path, frontmatter: dict, body: str = ""):
    """Write a markdown note with YAML frontmatter."""
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


def _setup_db(tmp_vault, notes=None, accesses=None):
    """Create and populate a test DB.

    notes: list of dicts with keys: filename, frontmatter, body (optional)
    accesses: list of dicts with keys: note_path, timestamp, context_type, project (optional)
    """
    db_path = str(tmp_vault / "test.db")
    vault_index.ensure_index(
        str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
    )

    if notes:
        for note in notes:
            folder = note.get("folder", "claude-sessions")
            note_path = tmp_vault / folder / note["filename"]
            _write_note(note_path, note["frontmatter"], note.get("body", ""))

        # Re-index to pick up new files
        vault_index.ensure_index(
            str(tmp_vault), ["claude-sessions", "claude-insights"], db_path=db_path
        )

        # Update importance via direct SQL if specified
        conn = sqlite3.connect(db_path)
        for note in notes:
            if "importance" in note:
                abs_path = str(tmp_vault / note.get("folder", "claude-sessions") / note["filename"])
                conn.execute(
                    "UPDATE notes SET importance = ? WHERE path = ?",
                    (note["importance"], abs_path),
                )
        conn.commit()
        conn.close()

    if accesses:
        conn = sqlite3.connect(db_path)
        for acc in accesses:
            # Convert relative paths to absolute (matching vault_index storage)
            note_p = acc["note_path"]
            if not os.path.isabs(note_p):
                note_p = str(tmp_vault / note_p)
            conn.execute(
                "INSERT INTO access_log (note_path, timestamp, context_type, project) "
                "VALUES (?, ?, ?, ?)",
                (
                    note_p,
                    acc["timestamp"],
                    acc["context_type"],
                    acc.get("project"),
                ),
            )
        conn.commit()
        conn.close()

    return db_path


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestComputeStatsEmptyDB:
    def test_empty_db_returns_zero_counts(self, tmp_vault):
        db_path = _setup_db(tmp_vault)
        result = json.loads(vault_stats.compute_stats(db_path, "test-project"))

        assert result["vault_wide"]["total_notes"] == 0
        assert result["vault_wide"]["access_log_entries"] == 0
        assert result["vault_wide"]["oldest_access"] is None
        assert result["vault_wide"]["top_accessed"] == []
        assert result["project"]["total_notes"] == 0
        assert result["project"]["access_events"] == 0
        assert result["project"]["avg_accesses"] == 0.0

    def test_empty_db_signal_coverage_all_neither(self, tmp_vault):
        db_path = _setup_db(tmp_vault)
        result = json.loads(vault_stats.compute_stats(db_path, "test-project"))
        sc = result["vault_wide"]["signal_coverage"]
        assert sc["has_activation"] == 0
        assert sc["has_importance"] == 0
        assert sc["has_both"] == 0
        assert sc["has_neither"] == 0


class TestComputeStatsWithNotes:
    def test_total_notes_counted(self, tmp_vault):
        notes = [
            {
                "filename": "note1.md",
                "frontmatter": {
                    "type": "claude-session",
                    "date": "2026-04-01",
                    "project": "proj-a",
                },
            },
            {
                "filename": "note2.md",
                "frontmatter": {
                    "type": "claude-session",
                    "date": "2026-04-02",
                    "project": "proj-b",
                },
            },
        ]
        db_path = _setup_db(tmp_vault, notes=notes)
        result = json.loads(vault_stats.compute_stats(db_path, "proj-a"))
        assert result["vault_wide"]["total_notes"] == 2

    def test_importance_distribution_bucketed(self, tmp_vault):
        notes = [
            {
                "filename": "n1.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
                "importance": 2,  # trivial
            },
            {
                "filename": "n2.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-02", "project": "p"},
                "importance": 5,  # standard
            },
            {
                "filename": "n3.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-03", "project": "p"},
                "importance": 7,  # significant
            },
            {
                "filename": "n4.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-04", "project": "p"},
                "importance": 10,  # critical
            },
        ]
        db_path = _setup_db(tmp_vault, notes=notes)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        dist = result["vault_wide"]["importance_distribution"]
        assert dist["trivial"] == 1
        assert dist["standard"] == 1
        assert dist["significant"] == 1
        assert dist["critical"] == 1


class TestComputeStatsWithAccessLog:
    def test_access_by_context_grouped(self, tmp_vault):
        now = time.time()
        notes = [
            {
                "filename": "a.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        accesses = [
            {"note_path": "claude-sessions/a.md", "timestamp": now - 100, "context_type": "recall"},
            {"note_path": "claude-sessions/a.md", "timestamp": now - 200, "context_type": "recall"},
            {"note_path": "claude-sessions/a.md", "timestamp": now - 300, "context_type": "search"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        abc = result["vault_wide"]["access_by_context"]
        assert abc["recall"] == 2
        assert abc["search"] == 1

    def test_top_accessed_sorted(self, tmp_vault):
        now = time.time()
        notes = [
            {
                "filename": f"note{i}.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            }
            for i in range(3)
        ]
        accesses = []
        # note0: 1 access, note1: 3 accesses, note2: 2 accesses
        for _ in range(1):
            accesses.append({"note_path": "claude-sessions/note0.md", "timestamp": now - 100, "context_type": "recall"})
        for _ in range(3):
            accesses.append({"note_path": "claude-sessions/note1.md", "timestamp": now - 100, "context_type": "recall"})
        for _ in range(2):
            accesses.append({"note_path": "claude-sessions/note2.md", "timestamp": now - 100, "context_type": "recall"})

        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        top = result["vault_wide"]["top_accessed"]
        assert len(top) == 3
        assert top[0]["accesses"] == 3
        assert top[0]["path"].endswith("claude-sessions/note1.md")
        assert top[1]["accesses"] == 2
        assert top[2]["accesses"] == 1


class TestComputeStatsProjectScoping:
    def test_project_filter_only_counts_matching(self, tmp_vault):
        now = time.time()
        notes = [
            {
                "filename": "pa1.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "alpha"},
            },
            {
                "filename": "pa2.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-02", "project": "alpha"},
            },
            {
                "filename": "pb1.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-03", "project": "beta"},
            },
        ]
        accesses = [
            {"note_path": "claude-sessions/pa1.md", "timestamp": now - 100, "context_type": "recall", "project": "alpha"},
            {"note_path": "claude-sessions/pa2.md", "timestamp": now - 200, "context_type": "recall", "project": "alpha"},
            {"note_path": "claude-sessions/pb1.md", "timestamp": now - 300, "context_type": "recall", "project": "beta"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "alpha"))
        assert result["project"]["name"] == "alpha"
        assert result["project"]["total_notes"] == 2
        assert result["project"]["access_events"] == 2
        assert result["project"]["avg_accesses"] == 1.0

    def test_project_top_accessed_limited_to_5(self, tmp_vault):
        now = time.time()
        notes = [
            {
                "filename": f"p{i}.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "proj"},
            }
            for i in range(7)
        ]
        accesses = [
            {"note_path": f"claude-sessions/p{i}.md", "timestamp": now - 100, "context_type": "recall", "project": "proj"}
            for i in range(7)
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "proj"))
        assert len(result["project"]["top_accessed"]) <= 5


class TestComputeStatsSignalCoverage:
    def test_signal_coverage_sets(self, tmp_vault):
        now = time.time()
        notes = [
            {  # has both activation and importance
                "filename": "both.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
                "importance": 8,
            },
            {  # has activation only (importance = 5 is default)
                "filename": "act_only.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-02", "project": "p"},
                "importance": 5,
            },
            {  # has importance only (no access)
                "filename": "imp_only.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-03", "project": "p"},
                "importance": 9,
            },
            {  # has neither
                "filename": "neither.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-04", "project": "p"},
                "importance": 5,
            },
        ]
        accesses = [
            {"note_path": "claude-sessions/both.md", "timestamp": now - 100, "context_type": "recall"},
            {"note_path": "claude-sessions/act_only.md", "timestamp": now - 200, "context_type": "recall"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        sc = result["vault_wide"]["signal_coverage"]
        assert sc["has_activation"] == 2
        assert sc["has_importance"] == 2
        assert sc["has_both"] == 1
        assert sc["has_neither"] == 1


class TestComputeStatsActivation:
    def test_top_accessed_includes_nonzero_activation(self, tmp_vault):
        now = time.time()
        notes = [
            {
                "filename": "active.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        accesses = [
            {"note_path": "claude-sessions/active.md", "timestamp": now - 60, "context_type": "recall"},
            {"note_path": "claude-sessions/active.md", "timestamp": now - 120, "context_type": "recall"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        top = result["vault_wide"]["top_accessed"]
        assert len(top) == 1
        assert top[0]["activation"] != 0.0
        assert isinstance(top[0]["activation"], float)


class TestComputeStatsMissingDB:
    def test_missing_db_returns_error_json(self, tmp_vault):
        result = json.loads(vault_stats.compute_stats("/nonexistent/path.db", "p"))
        assert "error" in result
        assert "not found" in result["error"].lower() or "DB not found" in result["error"]


class TestComputeStatsDBSize:
    def test_db_size_bytes_nonnegative(self, tmp_vault):
        db_path = _setup_db(tmp_vault)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        assert result["vault_wide"]["db_size_bytes"] >= 0


class TestImportanceBucketBoundaries:
    """Verify _importance_bucket boundary values."""

    @pytest.mark.parametrize("value,expected", [
        (1, "trivial"),
        (2, "trivial"),
        (3, "trivial"),
        (4, "standard"),
        (5, "standard"),
        (6, "standard"),
        (7, "significant"),
        (8, "significant"),
        (9, "critical"),
        (10, "critical"),
    ])
    def test_bucket_boundaries(self, value, expected):
        assert vault_stats._importance_bucket(value) == expected


class TestOrphanedAccessLogEntries:
    """Verify that access_log entries for deleted notes don't appear in stats."""

    def test_orphaned_access_excluded_from_top_accessed(self, tmp_vault):
        """Access events for notes deleted from vault don't appear in top_accessed."""
        now = time.time()
        notes = [
            {
                "filename": "exists.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        accesses = [
            # This note exists
            {"note_path": "claude-sessions/exists.md", "timestamp": now - 100, "context_type": "search"},
            # This note does NOT exist in vault (orphaned access)
            {"note_path": "/vault/deleted-note.md", "timestamp": now - 50, "context_type": "search"},
            {"note_path": "/vault/deleted-note.md", "timestamp": now - 60, "context_type": "recall"},
            {"note_path": "/vault/deleted-note.md", "timestamp": now - 70, "context_type": "search"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        top_paths = [t["path"] for t in result["vault_wide"]["top_accessed"]]
        assert "/vault/deleted-note.md" not in top_paths

    def test_orphaned_access_excluded_from_signal_coverage(self, tmp_vault):
        """Orphaned access events don't inflate has_activation count."""
        now = time.time()
        notes = [
            {
                "filename": "real.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        accesses = [
            {"note_path": "/vault/ghost.md", "timestamp": now - 50, "context_type": "search"},
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        # Ghost note shouldn't count as activation
        assert result["vault_wide"]["signal_coverage"]["has_activation"] == 0
        assert result["vault_wide"]["signal_coverage"]["has_neither"] == 1


class TestAvgAccessesEdgeCases:
    """Verify avg_accesses handles edge cases."""

    def test_zero_accesses_returns_zero(self, tmp_vault):
        """Project with notes but zero access events → avg_accesses = 0.0."""
        notes = [
            {
                "filename": "a.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
            {
                "filename": "b.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        db_path = _setup_db(tmp_vault, notes=notes)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        assert result["project"]["avg_accesses"] == 0.0

    def test_fractional_avg(self, tmp_vault):
        """5 accesses / 2 notes = 2.5."""
        now = time.time()
        notes = [
            {
                "filename": "n1.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
            {
                "filename": "n2.md",
                "frontmatter": {"type": "claude-session", "date": "2026-04-01", "project": "p"},
            },
        ]
        accesses = [
            {"note_path": "claude-sessions/n1.md", "timestamp": now - i * 10, "context_type": "search", "project": "p"}
            for i in range(5)
        ]
        db_path = _setup_db(tmp_vault, notes=notes, accesses=accesses)
        result = json.loads(vault_stats.compute_stats(db_path, "p"))
        assert result["project"]["avg_accesses"] == 2.5
