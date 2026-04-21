"""Verifies _sync() does not delete rows from sibling folders with a shared prefix."""

import sqlite3

import pytest

import vault_index


def test_sync_does_not_delete_sibling_prefix_folder(tmp_vault):
    """A file in 'claude-sessions-archive' must not be considered 'in claude-sessions'."""
    sessions = tmp_vault / "claude-sessions"
    archive = tmp_vault / "claude-sessions-archive"
    archive.mkdir()

    # Archived note present on disk, in a folder NOT scanned by this sync call.
    archived_note = archive / "2026-04-01-old-proj-aaaa.md"
    archived_note.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-01\n"
        "project: old-proj\n"
        "title: Archived\n"
        "tags:\n  - claude/session\n"
        "status: summarized\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    db_path = str(tmp_vault / "test.db")

    # First sync indexes BOTH folders (so the archived note is in the DB).
    vault_index.ensure_index(
        str(tmp_vault), ["claude-sessions", "claude-sessions-archive"],
        db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    before = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE path LIKE ?",
        (f"%{archive}%",),
    ).fetchone()[0]
    conn.close()
    assert before == 1, "Archived note should be indexed after the first sync"

    # Second sync only asks for 'claude-sessions'. The bug is that startswith()
    # considers the archive folder to live inside claude-sessions (shared prefix)
    # and deletes its row.
    vault_index.ensure_index(
        str(tmp_vault), ["claude-sessions"], db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    after = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE path LIKE ?",
        (f"%{archive}%",),
    ).fetchone()[0]
    conn.close()
    assert after == 1, (
        "Archived note row must survive a partial-folder sync — "
        "claude-sessions-archive is NOT inside claude-sessions."
    )
