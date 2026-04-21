import json
from pathlib import Path

from hooks import vault_index, vault_stats


def _setup_vault(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    # 1 session, 2 snapshots (compact + clear) backed by it, 1 orphan
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        "status: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-aa-snapshot-120000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        'trigger: compact\nstatus: summarized\nsource_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-aa-snapshot-150000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        'trigger: clear\nstatus: auto-logged\nsource_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-zz-snapshot-180000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: missing\nproject: demo\n"
        'trigger: compact\nstatus: auto-logged\nsource_session_note: "[[does-not-exist]]"\n'
        "---\n\n# Orphan\n",
        encoding="utf-8",
    )
    return vault


def test_snapshot_stats_counts_by_trigger_and_integrity(tmp_path):
    vault = _setup_vault(tmp_path)
    db = vault_index.ensure_index(str(vault), ["claude-sessions"],
                                  db_path=str(tmp_path / "test.db"))
    payload = json.loads(vault_stats.compute_stats(db, "demo"))
    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 3
    assert snap["by_trigger"] == {"compact": 2, "clear": 1, "auto": 0}
    assert snap["sessions_with_snapshots"] == 2   # s1 and "missing"
    assert snap["max_snapshots_per_session"] == 2
    assert snap["orphaned_snapshots"] == 1
    assert snap["broken_backlinks"] >= 1
    assert 0.0 <= snap["summarized_fraction"] <= 1.0


def test_snapshot_stats_zero_state(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    db = vault_index.ensure_index(str(vault), ["claude-sessions"],
                                  db_path=str(tmp_path / "test2.db"))
    payload = json.loads(vault_stats.compute_stats(db, "demo"))
    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 0
    assert snap["summarized_fraction"] == 1.0
    assert snap["by_trigger"] == {"compact": 0, "clear": 0, "auto": 0}
    assert snap["read_errors"] == 0


def test_snapshot_stats_counts_unreadable_snapshots(tmp_path):
    """OSError on snapshot read is surfaced via read_errors, not silently dropped."""
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    snap_path = sess / "2026-04-18-demo-aa-snapshot-120000.md"
    snap_path.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        'trigger: compact\nstatus: auto-logged\nsource_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    db = vault_index.ensure_index(str(vault), ["claude-sessions"],
                                  db_path=str(tmp_path / "unreadable.db"))
    # Render the snapshot unreadable AFTER indexing (0o000 perms)
    import os
    os.chmod(snap_path, 0o000)
    try:
        payload = json.loads(vault_stats.compute_stats(db, "demo"))
    finally:
        os.chmod(snap_path, 0o600)

    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 1
    assert snap["read_errors"] == 1
    # The unreadable snapshot should NOT be silently counted as a trigger
    assert sum(snap["by_trigger"].values()) + snap["read_errors"] == snap["total_snapshots"]


def test_snapshot_stats_unknown_trigger_folds_into_auto(tmp_path):
    """Trigger values outside {compact, clear, auto} are counted as 'auto'."""
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-aa-snapshot-120000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\nproject: demo\n"
        'trigger: weird_value\nstatus: auto-logged\nsource_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    db = vault_index.ensure_index(str(vault), ["claude-sessions"],
                                  db_path=str(tmp_path / "test3.db"))
    payload = json.loads(vault_stats.compute_stats(db, "demo"))
    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 1
    assert snap["by_trigger"] == {"compact": 0, "clear": 0, "auto": 1}


def test_compute_stats_missing_db_returns_error(tmp_path):
    """compute_stats on a nonexistent DB returns {'error': ...} instead of raising."""
    payload = json.loads(vault_stats.compute_stats(str(tmp_path / "does-not-exist.db"), "demo"))
    assert "error" in payload
    assert "DB not found" in payload["error"]


def test_compute_stats_corrupt_db_returns_error(tmp_path):
    """compute_stats on a file that isn't a SQLite DB surfaces the inner exception."""
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not a sqlite file", encoding="utf-8")
    payload = json.loads(vault_stats.compute_stats(str(corrupt), "demo"))
    assert "error" in payload


def test_snapshot_stats_counts_summarized_even_when_file_unreadable(tmp_path):
    """Regression for Copilot PR #43 round 2 finding: a snapshot with
    `status: summarized` in the index but unreadable on disk must still
    contribute to summarized_fraction, since status comes from the DB row
    (which survives file-permission issues).
    """
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    snap_path = sess / "2026-04-18-demo-aa-snapshot-120000.md"
    snap_path.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\ntrigger: compact\nstatus: summarized\n"
        'source_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n\n## Summary\nindexed as summarized\n",
        encoding="utf-8",
    )
    db = vault_index.ensure_index(
        str(vault), ["claude-sessions"],
        db_path=str(tmp_path / "summary_vs_unreadable.db"),
    )
    # Now render unreadable AFTER indexing so status is captured in the DB row
    import os
    os.chmod(snap_path, 0o000)
    try:
        payload = json.loads(vault_stats.compute_stats(db, "demo"))
    finally:
        os.chmod(snap_path, 0o600)

    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 1
    assert snap["read_errors"] == 1
    # The key assertion: summarized_fraction reflects the indexed status,
    # not the on-disk readability. 1 summarized / 1 total == 1.0.
    assert snap["summarized_fraction"] == 1.0, (
        f"summarized_fraction should use indexed status, got {snap['summarized_fraction']}"
    )


def test_snapshot_stats_missing_trigger_folds_into_auto(tmp_path):
    """Regression for Copilot PR #43 finding: a snapshot note with no
    `trigger:` frontmatter field must NOT default into the compact bucket
    (inflates compact counts and masks legacy/malformed notes). Fold into
    'auto' instead, consistent with the unknown-value handling.
    """
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    (sess / "2026-04-18-demo-aa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    # Snapshot has NO trigger: field
    (sess / "2026-04-18-demo-aa-snapshot-120000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\nstatus: auto-logged\n"
        'source_session_note: "[[2026-04-18-demo-aa]]"\n'
        "---\n\n# Snap\n",
        encoding="utf-8",
    )
    db = vault_index.ensure_index(
        str(vault), ["claude-sessions"],
        db_path=str(tmp_path / "missing_trigger.db"),
    )
    payload = json.loads(vault_stats.compute_stats(db, "demo"))
    snap = payload["vault_wide"]["snapshots"]
    assert snap["total_snapshots"] == 1
    assert snap["by_trigger"] == {"compact": 0, "clear": 0, "auto": 1}
