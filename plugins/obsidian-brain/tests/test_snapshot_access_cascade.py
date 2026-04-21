import sqlite3
from pathlib import Path

import pytest

from hooks import vault_index


def _seed(vault, sess):
    (sess).mkdir(parents=True, exist_ok=True)
    parent_path = sess / "2026-04-18-demo-aaaa.md"
    parent_path.write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        "status: summarized\n---\n\n# Session\n",
        encoding="utf-8",
    )
    snap_path = sess / "2026-04-18-demo-aaaa-snapshot-140000.md"
    snap_path.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        "status: summarized\n"
        'source_session_note: "[[2026-04-18-demo-aaaa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    return parent_path, snap_path


def test_log_access_on_snapshot_inserts_two_rows(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    parent_path, snap_path = _seed(vault, sess)
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "test.db")
    )
    # Clear cache so this test's snap_path is not stale from a previous run
    vault_index._PARENT_CACHE.clear()

    vault_index.log_access(db_path, str(snap_path), "search", "demo")

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT note_path FROM access_log").fetchall()
    conn.close()
    paths = {r[0] for r in rows}
    assert str(snap_path) in paths
    assert str(parent_path) in paths


def test_log_access_on_session_inserts_single_row(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    parent_path, _ = _seed(vault, sess)
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "test.db")
    )
    vault_index._PARENT_CACHE.clear()

    vault_index.log_access(db_path, str(parent_path), "recall", "demo")

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT note_path FROM access_log").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == str(parent_path)


def test_log_access_with_broken_snapshot_backlink_is_tolerant(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    snap = sess / "2026-04-18-demo-cccc-snapshot-090000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: no-such\n"
        'project: demo\nstatus: auto-logged\nsource_session_note: "[[does-not-exist]]"\n'
        "---\n\n# Orphan snap\n",
        encoding="utf-8",
    )
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "test.db")
    )
    vault_index._PARENT_CACHE.clear()

    # Must not raise
    vault_index.log_access(db_path, str(snap), "search", "demo")

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT note_path FROM access_log").fetchall()
    conn.close()
    # Only the snapshot is logged; parent cannot be resolved
    assert {r[0] for r in rows} == {str(snap)}


def test_parent_session_resolved_with_single_quoted_wikilink(tmp_path):
    """Regression for Copilot PR #43 finding: `source_session_note` regex
    must accept single-quoted and unquoted wikilinks, not just double-quoted.
    YAML allows all three and hand-edits may use any.
    """
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    parent = sess / "2026-04-18-demo-eeee.md"
    parent.write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: sq\n"
        "project: demo\nstatus: summarized\n---\n\n# Session\n",
        encoding="utf-8",
    )
    # Single-quoted wikilink — previously NOT matched by the regex
    snap = sess / "2026-04-18-demo-eeee-snapshot-120000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: sq\n"
        "project: demo\nstatus: summarized\n"
        "source_session_note: '[[2026-04-18-demo-eeee]]'\n"
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "single.db")
    )
    vault_index._PARENT_CACHE.clear()

    result = vault_index._parent_session_for_snapshot(str(snap), db_path)
    assert result == str(parent), (
        f"single-quoted wikilink should resolve to parent; got {result!r}"
    )


def test_parent_session_resolved_with_unquoted_wikilink(tmp_path):
    """Unquoted wikilink form is also valid YAML; must resolve."""
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    parent = sess / "2026-04-18-demo-ffff.md"
    parent.write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: uq\n"
        "project: demo\nstatus: summarized\n---\n\n# Session\n",
        encoding="utf-8",
    )
    snap = sess / "2026-04-18-demo-ffff-snapshot-120000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: uq\n"
        "project: demo\nstatus: summarized\n"
        "source_session_note: [[2026-04-18-demo-ffff]]\n"
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "unquoted.db")
    )
    vault_index._PARENT_CACHE.clear()

    result = vault_index._parent_session_for_snapshot(str(snap), db_path)
    assert result == str(parent)


def test_log_access_transient_db_error_does_not_poison_cache(tmp_path):
    """A DB-open failure during parent resolution must not cache None permanently.

    Regression guard for a silent failure where `_parent_session_for_snapshot`
    caught all exceptions and cached None on any sqlite3 error — e.g. a
    transient 'database is locked' during high concurrency would disable the
    parent cascade for that snapshot for the process lifetime.
    """
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    parent_path, snap_path = _seed(vault, sess)
    db_path = vault_index.ensure_index(
        str(vault), ["claude-sessions"], db_path=str(tmp_path / "test.db")
    )
    vault_index._PARENT_CACHE.clear()

    # Simulate transient DB error by pointing at a nonexistent DB file.
    bad_db = str(tmp_path / "does-not-exist.db")
    result = vault_index._parent_session_for_snapshot(str(snap_path), bad_db)
    assert result is None
    # Critical: cache must NOT contain a poisoned None for snap_path.
    assert str(snap_path) not in vault_index._PARENT_CACHE

    # Next call with the real DB must resolve the parent.
    result2 = vault_index._parent_session_for_snapshot(str(snap_path), db_path)
    assert result2 == str(parent_path)


def test_log_access_on_unindexed_snapshot_does_not_poison_cache(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    parent_path, snap_path = _seed(vault, sess)
    # Build DB but seed it with a DIFFERENT vault so snap_path is NOT indexed.
    db_path = str(tmp_path / "test.db")
    vault_index.ensure_index(str(tmp_path / "other-vault"), ["claude-sessions"], db_path=db_path)
    vault_index._PARENT_CACHE.clear()

    # First call: snap_path not in DB, cache should NOT record None.
    vault_index.log_access(db_path, str(snap_path), "search", "demo")
    assert str(snap_path) not in vault_index._PARENT_CACHE

    # Re-index with the real vault — now snap_path is present.
    vault_index.ensure_index(str(vault), ["claude-sessions"], db_path=db_path)

    # Second call: cache should now resolve the parent.
    vault_index.log_access(db_path, str(snap_path), "search", "demo")
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT note_path FROM access_log").fetchall()
    conn.close()
    paths = [r[0] for r in rows]
    # Snapshot logged twice; parent logged once (only after indexing).
    assert paths.count(str(snap_path)) == 2
    assert paths.count(str(parent_path)) == 1
