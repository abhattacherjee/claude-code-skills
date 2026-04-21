"""Verifies batch access logging: one connection, one commit per search call."""

import sqlite3

import pytest

import vault_index


@pytest.fixture
def indexed_vault(tmp_vault):
    """Vault with three indexed notes matching the query 'foo'."""
    sessions = tmp_vault / "claude-sessions"
    for i, slug in enumerate(["a", "b", "c"]):
        (sessions / f"2026-04-16-proj-{slug}.md").write_text(
            "---\n"
            "type: claude-session\n"
            "date: 2026-04-16\n"
            "project: proj\n"
            f"title: Note {slug}\n"
            "tags:\n  - claude/session\n"
            "status: summarized\n"
            "---\n"
            "foo bar baz\n",
            encoding="utf-8",
        )
    db_path = str(tmp_vault / "test.db")
    vault_index.ensure_index(str(tmp_vault), ["claude-sessions"], db_path=db_path)
    return db_path


@pytest.fixture
def indexed_vault_with_related(tmp_vault):
    """Vault with an anchor session note and a related insight sharing a topic tag.

    Both notes carry ``claude/topic/retrieval`` so ``query_related_notes``
    Layer 2 (tag overlap) returns the insight when queried with the anchor's
    tags.
    """
    sessions = tmp_vault / "claude-sessions"
    insights = tmp_vault / "claude-insights"

    anchor_path = sessions / "2026-04-16-proj-anchor.md"
    anchor_path.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-16\n"
        "session_id: anchor-session-id\n"
        "project: proj\n"
        "title: Anchor session\n"
        "tags:\n"
        "  - claude/session\n"
        "  - claude/topic/retrieval\n"
        "status: summarized\n"
        "---\n"
        "Anchor session body discussing retrieval.\n",
        encoding="utf-8",
    )

    insight_path = insights / "2026-04-16-retrieval-insight.md"
    insight_path.write_text(
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-16\n"
        "project: proj\n"
        "title: Retrieval insight\n"
        "tags:\n"
        "  - claude/insight\n"
        "  - claude/topic/retrieval\n"
        "status: summarized\n"
        "---\n"
        "Insight about retrieval systems.\n",
        encoding="utf-8",
    )

    db_path = str(tmp_vault / "test.db")
    vault_index.ensure_index(
        str(tmp_vault),
        ["claude-sessions", "claude-insights"],
        db_path=db_path,
    )
    return db_path, str(anchor_path)


def test_search_vault_inserts_one_row_per_result(indexed_vault):
    """Smoke test: one search returning N results must insert exactly N rows."""
    results = vault_index.search_vault(indexed_vault, "foo", project="proj", limit=10)
    assert len(results) >= 1, "Query should match at least one note"

    conn = sqlite3.connect(indexed_vault)
    count = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
    conn.close()
    assert count == len(results)


def test_search_vault_uses_single_connection(indexed_vault, monkeypatch):
    """log_access should NOT be called in a loop — batch insert only."""
    call_count = {"n": 0}
    original = vault_index.log_access

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(vault_index, "log_access", counting)
    vault_index.search_vault(indexed_vault, "foo", project="proj", limit=10)
    assert call_count["n"] == 0, (
        f"log_access was called {call_count['n']} times — "
        "search_vault should use batch insert on its own connection instead."
    )


def test_query_related_notes_uses_batch_logging(
    indexed_vault_with_related, monkeypatch
):
    """query_related_notes must go through the batch path, not log_access loop.

    Asserts (a) access_log row count == returned result count,
    (b) ``log_access`` is never called (monkeypatch, 0 calls),
    (c) inserted rows have ``context_type == 'related'``.
    """
    db_path, _anchor_path = indexed_vault_with_related

    call_count = {"n": 0}
    original = vault_index.log_access

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(vault_index, "log_access", counting)

    results = vault_index.query_related_notes(
        db_path,
        project="proj",
        session_ids=[],
        session_tags=["claude/topic/retrieval"],
        session_summary="",
        limit=20,
    )
    assert len(results) >= 1, (
        "Layer 2 (tag overlap) should return at least the retrieval insight"
    )

    assert call_count["n"] == 0, (
        f"log_access was called {call_count['n']} times — "
        "query_related_notes should use batch insert instead."
    )

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
        related_count = conn.execute(
            "SELECT COUNT(*) FROM access_log WHERE context_type = 'related'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert total == len(results)
    assert related_count == len(results), (
        f"Expected all {len(results)} rows to have context_type='related', "
        f"got {related_count}"
    )
