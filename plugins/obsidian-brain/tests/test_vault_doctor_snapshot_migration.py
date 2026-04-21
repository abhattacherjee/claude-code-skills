import datetime
import os
from pathlib import Path

from scripts.vault_doctor_checks import snapshot_migration


def _write_legacy_snapshot(path, mtime_iso="2026-04-18T14:30:27", session_id="s1"):
    path.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {session_id}\n"
        "project: demo\ntrigger: compact\n---\n\n# Snap\n\n## What was happening\nx\n",
        encoding="utf-8",
    )
    dt = datetime.datetime.fromisoformat(mtime_iso)
    os.utime(path, (dt.timestamp(), dt.timestamp()))


def _write_session(path, session_id="s1"):
    path.write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {session_id}\n"
        "project: demo\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )


def test_legacy_filename_gets_hhmmss_suffix(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-aa-snapshot.md")
    _write_session(sess / "2026-04-18-demo-aa.md")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1
    assert "snapshot-143027" in legacy[0].proposed_source

    results = snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    assert all(r.status == "applied" for r in results)
    assert (sess / "2026-04-18-demo-aa-snapshot-143027.md").exists()
    assert not (sess / "2026-04-18-demo-aa-snapshot.md").exists()


def test_legacy_filename_collision_skips_with_warning(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-aa-snapshot.md")
    _write_legacy_snapshot(sess / "2026-04-18-demo-aa-snapshot-143027.md")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert any(i.extra.get("unresolved") for i in legacy)


def test_missing_status_auto_logged_when_no_summary(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-bb-snapshot-120000.md")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-status"]
    assert len(miss) == 1
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-bb-snapshot-120000.md").read_text(encoding="utf-8")
    assert "status: auto-logged" in text


def test_missing_status_summarized_when_summary_exists(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-cc-snapshot-130000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s3\nproject: demo\n"
        "trigger: compact\n---\n\n# Snap\n\n## Summary\nreal summary body\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-status"]
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = p.read_text(encoding="utf-8")
    assert "status: summarized" in text


def test_missing_backlink_populates_source_session_note(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    # Parent filename must match the computed stem: <date>-<slug(project)>-<sha256(sid)[:4]>
    # For session_id="s4" the hash prefix is computed deterministically.
    import hashlib as _h
    sid = "s4"
    hash4 = _h.sha256(sid.encode()).hexdigest()[:4]
    parent_stem = f"2026-04-18-demo-{hash4}"
    _write_session(sess / f"{parent_stem}.md", session_id=sid)
    p = sess / f"{parent_stem}-snapshot-110000.md"
    p.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\nproject: demo\n"
        "trigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert not miss[0].extra.get("unresolved")  # parent exists
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = p.read_text(encoding="utf-8")
    assert f'source_session_note: "[[{parent_stem}]]"' in text


def test_missing_backlink_unresolved_when_parent_absent(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-zz-snapshot-110000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: nonexistent\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert miss[0].extra.get("unresolved")


def test_session_missing_snapshots_list_is_backfilled(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-dd.md", session_id="s5")
    _write_legacy_snapshot(sess / "2026-04-18-demo-dd-snapshot-100000.md", session_id="s5")
    _write_legacy_snapshot(sess / "2026-04-18-demo-dd-snapshot-140000.md", session_id="s5")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "session-missing-snapshots-list"]
    assert len(miss) == 1
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-dd.md").read_text(encoding="utf-8")
    assert "snapshots:" in text
    assert "2026-04-18-demo-dd-snapshot-100000" in text
    assert "2026-04-18-demo-dd-snapshot-140000" in text


def test_wikilink_rewrite_across_vault_on_rename(tmp_path):
    """Rename should rewrite [[old-stem]] references across the vault."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    insights = tmp_path / "claude-insights"; insights.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-xx-snapshot.md")
    _write_session(sess / "2026-04-18-demo-xx.md")
    # An insight note references the legacy stem
    (insights / "ref.md").write_text(
        "---\ntype: claude-insight\n---\n\nsee [[2026-04-18-demo-xx-snapshot]] for context\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    ref_text = (insights / "ref.md").read_text(encoding="utf-8")
    assert "[[2026-04-18-demo-xx-snapshot-143027]]" in ref_text
    assert "[[2026-04-18-demo-xx-snapshot]]" not in ref_text


def test_migration_is_idempotent(tmp_path):
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-ee-snapshot.md", session_id="eeee")
    # Parent stem must match hash of "eeee" since _write_legacy_snapshot hardcodes project="demo"
    import hashlib as _h
    hash4 = _h.sha256(b"eeee").hexdigest()[:4]
    _write_session(sess / f"2026-04-18-demo-{hash4}.md", session_id="eeee")
    # First pass
    issues1 = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    snapshot_migration.apply([i for i in issues1 if not i.extra.get("unresolved")],
                             str(tmp_path / "backup"))
    # Second pass — should be empty (or only unresolved issues)
    issues2 = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    # All remaining issues should be unresolved (nothing fixable left)
    assert all(i.extra.get("unresolved") for i in issues2)


def test_missing_backlink_unresolved_when_sid_missing(tmp_path):
    """No session_id in frontmatter -> unresolved (cannot compute parent)."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-ff-snapshot-100000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert miss[0].extra.get("unresolved")
    # Apply should record unresolved status
    results = snapshot_migration.apply(miss, str(tmp_path / "backup"))
    assert results[0].status == "unresolved"


def test_scan_returns_empty_when_sessions_folder_missing(tmp_path):
    """scan() must return [] when the sessions folder does not exist."""
    # No claude-sessions dir created at tmp_path
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    assert issues == []


def test_scan_project_filter_excludes_other_projects(tmp_path):
    """Project filter should skip snapshots whose project differs."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-gg-snapshot.md")
    # Keep project=demo but filter by 'other' — should exclude.
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650, project="other"
    )
    assert issues == []


def test_scan_skips_notes_without_frontmatter(tmp_path):
    """A .md file without frontmatter should be silently skipped by scan()."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    (sess / "no-frontmatter.md").write_text("just a body, no yaml\n", encoding="utf-8")
    # And still detect a real legacy snapshot alongside.
    _write_legacy_snapshot(sess / "2026-04-18-demo-hh-snapshot.md")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    # Only the valid snapshot produces issues; the orphan file is ignored.
    assert any(i.note_path.endswith("2026-04-18-demo-hh-snapshot.md") for i in issues)


def test_apply_unknown_check_is_skipped(tmp_path):
    """apply() should mark unrecognized check names as 'skipped'."""
    from scripts.vault_doctor_checks import Issue as _Issue
    fake = _Issue(
        check="not-a-real-check",
        note_path=str(tmp_path / "x.md"),
        project="demo",
        current_source="",
        proposed_source="",
        reason="",
        confidence=1.0,
    )
    results = snapshot_migration.apply([fake], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "skipped"


def test_apply_status_raises_runtime_error_when_no_frontmatter(tmp_path):
    """apply() should record an error when the snapshot has no frontmatter."""
    from scripts.vault_doctor_checks import Issue as _Issue
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "broken.md"
    p.write_text("no frontmatter at all\n", encoding="utf-8")
    issue = _Issue(
        check="snapshot-missing-status",
        note_path=str(p),
        project="demo",
        current_source="(no status field)",
        proposed_source="status: auto-logged",
        reason="test",
        confidence=0.98,
    )
    results = snapshot_migration.apply([issue], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "error"
    assert "frontmatter" in (results[0].error or "")


# ----- PR-review regression tests -----


def test_wikilink_rewrite_uses_vault_root_not_parent_twice(tmp_path):
    """CRITICAL-1 regression: sessions_folder can be nested more than one
    level below the vault root. ``_rewrite_wikilinks_in_vault`` must scan
    from the true vault root, not from ``src.parents[1]``.
    """
    # Vault root is tmp_path; sessions live under notes/claude-sessions
    # (two levels deep). An insight note lives under claude-insights at the
    # vault root — the OLD code rooted wikilink rewrite at ``notes/`` and
    # therefore missed the insight.
    vault = tmp_path
    sess = vault / "notes" / "claude-sessions"; sess.mkdir(parents=True)
    insights = vault / "claude-insights"; insights.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-nest-snapshot.md")
    _write_session(sess / "2026-04-18-demo-nest.md")
    (insights / "ref.md").write_text(
        "---\ntype: claude-insight\n---\n\n"
        "see [[2026-04-18-demo-nest-snapshot]] for context\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(vault), "notes/claude-sessions", "claude-insights", 3650
    )
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1
    snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    ref_text = (insights / "ref.md").read_text(encoding="utf-8")
    assert "[[2026-04-18-demo-nest-snapshot-143027]]" in ref_text
    assert "[[2026-04-18-demo-nest-snapshot]]" not in ref_text


def test_legacy_filename_plus_session_list_batch_translates_stems(tmp_path):
    """CRITICAL-2 regression: when both snapshot-legacy-filename and
    session-missing-snapshots-list fire in the same batch, the session's
    final ``snapshots:`` list must reference the POST-rename stem.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-bat-snapshot.md",
                           session_id="sBAT")
    _write_session(sess / "2026-04-18-demo-bat.md", session_id="sBAT")
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    # Apply the full batch (both legacy-filename AND
    # session-missing-snapshots-list, plus whatever else scan found).
    fixable = [i for i in issues if not i.extra.get("unresolved")]
    snapshot_migration.apply(fixable, str(tmp_path / "backup"))
    # Session must now list the NEW stem, not the OLD one.
    sess_text = (sess / "2026-04-18-demo-bat.md").read_text(encoding="utf-8")
    assert "2026-04-18-demo-bat-snapshot-143027" in sess_text
    # Old stem must not appear in the session's snapshots block
    # (substring-match is strict: we look for [[old]] surrounded by quotes).
    assert '"[[2026-04-18-demo-bat-snapshot]]"' not in sess_text


def test_rename_rollback_on_wikilink_failure(tmp_path, monkeypatch):
    """CRITICAL-3 regression: if ``_rewrite_wikilinks_in_vault`` raises,
    the rename must be rolled back and the Issue must surface as
    ``status="error"``.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    legacy_path = sess / "2026-04-18-demo-rb-snapshot.md"
    _write_legacy_snapshot(legacy_path)
    _write_session(sess / "2026-04-18-demo-rb.md")
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1

    # Force the wikilink rewrite to raise so we can verify rollback.
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated wikilink rewrite failure")

    monkeypatch.setattr(snapshot_migration, "_rewrite_wikilinks_in_vault", _boom)
    results = snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "error"
    # Rollback: the original legacy filename must still exist, the new
    # name must NOT exist.
    assert legacy_path.exists(), "rename must be rolled back on rewrite failure"
    assert not (sess / "2026-04-18-demo-rb-snapshot-143027.md").exists()


def test_crlf_frontmatter_is_parsed_migration(tmp_path):
    """HIGH-5 regression for the migration module: CRLF + BOM must parse."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    # Legacy snapshot with BOM + CRLF
    p = sess / "2026-04-18-demo-cr-snapshot.md"
    p.write_bytes(
        b"\xef\xbb\xbf---\r\ntype: claude-snapshot\r\ndate: 2026-04-18\r\n"
        b"session_id: sCRLF\r\nproject: demo\r\ntrigger: compact\r\n---\r\n\r\n# Snap\r\n"
    )
    # Set mtime so the HHMMSS is deterministic
    dt = datetime.datetime.fromisoformat("2026-04-18T14:30:27")
    os.utime(p, (dt.timestamp(), dt.timestamp()))
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    miss_status = [i for i in issues if i.check == "snapshot-missing-status"]
    # Both checks MUST fire; the BOM/CRLF must not prevent frontmatter parsing.
    assert len(legacy) == 1, "CRLF/BOM frontmatter must be detected as legacy"
    assert len(miss_status) == 1, "CRLF/BOM frontmatter must also register missing status"


def test_missing_status_idempotent_when_already_present(tmp_path):
    """HIGH-8 regression: stale Issue replay against a snapshot that
    already has ``status:`` must be a no-op skip, not a double-write.
    """
    from scripts.vault_doctor_checks import Issue as _Issue
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-idem-snapshot-100000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\ntrigger: compact\nstatus: summarized\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issue = _Issue(
        check="snapshot-missing-status",
        note_path=str(p),
        project="demo",
        current_source="(no status field)",
        proposed_source="status: auto-logged",
        reason="stale replay",
    )
    results = snapshot_migration.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "skipped"
    assert "already present" in (results[0].error or "")


def test_missing_backlink_idempotent_when_already_present(tmp_path):
    """HIGH-8 regression: stale Issue replay against a snapshot that
    already has ``source_session_note:`` must be a no-op skip.
    """
    from scripts.vault_doctor_checks import Issue as _Issue
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-idem-snapshot-110000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s1\n"
        "project: demo\ntrigger: compact\nstatus: summarized\n"
        'source_session_note: "[[already-there]]"\n---\n\n# Snap\n',
        encoding="utf-8",
    )
    issue = _Issue(
        check="snapshot-missing-backlink",
        note_path=str(p),
        project="demo",
        current_source="(no source_session_note)",
        proposed_source='source_session_note: "[[parent]]"',
        reason="stale replay",
    )
    results = snapshot_migration.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "skipped"
    assert "already present" in (results[0].error or "")


def test_rewrite_wikilinks_returns_zero_when_nothing_to_replace(tmp_path):
    """_rewrite_wikilinks_in_vault covers the non-match loop path."""
    vault = tmp_path
    (vault / "unrelated.md").write_text("no wikilinks here\n", encoding="utf-8")
    count, modified = snapshot_migration._rewrite_wikilinks_in_vault(
        str(vault), "nonexistent-stem", "new-stem"
    )
    assert count == 0
    assert modified == []


def test_missing_list_apply_skipped_when_snapshots_already_present(tmp_path):
    """Regression: defensive re-check prevents duplicate snapshots: blocks in migration.

    Parity with snapshot_integrity: if a stale Issue from an earlier
    scan is replayed against a session whose frontmatter already has a
    snapshots: block, apply must short-circuit with status='skipped'
    rather than inject a duplicate block above ``status:``.
    """
    from scripts.vault_doctor_checks import Issue as _Issue
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    # Session already has a snapshots: block
    (sess / "2026-04-18-demo-zz.md").write_text(
        '---\ntype: claude-session\ndate: 2026-04-18\nsession_id: zzzz\nproject: demo\n'
        'snapshots:\n  - "[[2026-04-18-demo-zz-snapshot-100000]]"\n'
        'status: summarized\n---\n\n# S\n',
        encoding="utf-8",
    )
    _write_legacy_snapshot(sess / "2026-04-18-demo-zz-snapshot-100000.md", session_id="zzzz")
    # Build a stale/replayed Issue for session-missing-snapshots-list
    stale_issue = _Issue(
        check="session-missing-snapshots-list",
        note_path=str(sess / "2026-04-18-demo-zz.md"),
        project="demo",
        current_source="(no snapshots field)",
        proposed_source="[[2026-04-18-demo-zz-snapshot-100000]]",
        reason="stale replay",
        confidence=0.98,
    )
    results = snapshot_migration.apply([stale_issue], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "already present" in (results[0].error or "")
    text = (sess / "2026-04-18-demo-zz.md").read_text(encoding="utf-8")
    # Exactly one snapshots: block
    assert text.count("snapshots:") == 1


def test_session_missing_snapshots_list_not_corrupted_by_body_status(tmp_path):
    """CRITICAL-4 regression for the migration module: a body-level
    ``status:`` line must not be matched when injecting the snapshots
    block.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    # Session without status: in frontmatter, but body contains
    # ``## Status ...`` + a ``status: active`` line.
    (sess / "2026-04-18-demo-bs.md").write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-18\n"
        "session_id: sBS\n"
        "project: demo\n"
        "---\n\n"
        "# Session\n\n"
        "## Status of things\n"
        "status: active\n",
        encoding="utf-8",
    )
    _write_legacy_snapshot(sess / "2026-04-18-demo-bs-snapshot-100000.md",
                           session_id="sBS")
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    miss = [i for i in issues if i.check == "session-missing-snapshots-list"]
    assert len(miss) == 1
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-bs.md").read_text(encoding="utf-8")
    # Body-level ``## Status of things`` + ``status: active`` MUST still
    # appear verbatim, unmodified — the snapshots block must NOT have been
    # injected before the body line.
    assert "## Status of things\nstatus: active" in text
    # Frontmatter must now contain the snapshots block.
    fm = text.split("---\n", 2)[1]
    assert "snapshots:" in fm
    assert "2026-04-18-demo-bs-snapshot-100000" in fm


def test_apply_skipped_does_not_create_backup(tmp_path):
    """Regression: idempotent skip must not create a backup file (stale-Issue replay efficiency)."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    # Session already has snapshots: list (stale Issue replay scenario)
    (sess / "2026-04-18-demo-zz.md").write_text(
        '---\ntype: claude-session\ndate: 2026-04-18\nsession_id: zzzz\nproject: demo\n'
        'snapshots:\n  - "[[2026-04-18-demo-zz-snapshot-100000]]"\n'
        'status: summarized\n---\n\n# S\n',
        encoding="utf-8",
    )
    _write_legacy_snapshot(sess / "2026-04-18-demo-zz-snapshot-100000.md", session_id="zzzz")
    from scripts.vault_doctor_checks import Issue
    stale_issue = Issue(
        check="session-missing-snapshots-list",
        note_path=str(sess / "2026-04-18-demo-zz.md"),
        project="demo",
        current_source="(no snapshots field)",
        proposed_source="[[2026-04-18-demo-zz-snapshot-100000]]",
        reason="stale replay",
        confidence=0.98,
    )
    backup_root = tmp_path / "backup"
    results = snapshot_migration.apply([stale_issue], str(backup_root))
    assert results[0].status == "skipped"
    # No backup file should exist for this skipped issue
    backup_dir = backup_root / "session-missing-snapshots-list"
    if backup_dir.exists():
        assert not list(backup_dir.iterdir()), (
            f"unexpected backup files: {list(backup_dir.iterdir())}"
        )


def test_apply_backup_path_points_to_backup_file_not_directory(tmp_path):
    """Regression: Result.backup_path must be the actual backup file."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-bb-snapshot-120000.md", session_id="sB")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-status"]
    assert len(miss) == 1
    backup_root = tmp_path / "backup"
    results = snapshot_migration.apply(miss, str(backup_root))
    assert results[0].status == "applied"
    # The backup_path must point to the backup file
    backup_path = Path(results[0].backup_path)
    assert backup_path.is_file(), f"backup_path is not a file: {backup_path}"
    assert backup_path.name == "2026-04-18-demo-bb-snapshot-120000.md"


def test_rename_does_not_rewrite_wikilinks_in_backup_dir(tmp_path):
    """Copilot round-3 regression: backup file must retain pre-migration
    wikilink stem.

    ``_rewrite_wikilinks_in_vault`` walks ``vault_root.rglob("*.md")``.
    If ``backup_root`` lives inside the vault (tests place it under
    ``tmp_path``; real callers may too), the just-created backup copy
    has its ``[[old-stem]]`` references rewritten to ``[[new-stem]]`` —
    making the backup useless for rollback. The fix excludes
    ``backup_root`` from the rglob walk.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    insights = tmp_path / "claude-insights"; insights.mkdir()
    # Snapshot whose BODY references its own stem (e.g. cross-snapshot
    # link previously inserted by hand or by a sibling snapshot's
    # references). After rename, the LIVE file is rewritten — but the
    # backup copy MUST NOT be.
    legacy_path = sess / "2026-04-18-demo-bk-snapshot.md"
    legacy_body = (
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: sBK\n"
        "project: demo\ntrigger: compact\n---\n\n# Snap\n\n"
        "self-ref: [[2026-04-18-demo-bk-snapshot]]\n"
    )
    legacy_path.write_text(legacy_body, encoding="utf-8")
    dt = datetime.datetime.fromisoformat("2026-04-18T14:30:27")
    os.utime(legacy_path, (dt.timestamp(), dt.timestamp()))
    _write_session(sess / "2026-04-18-demo-bk.md", session_id="sBK")
    # External insight that also references the legacy stem — proves the
    # live rewrite still works (regression guard against over-exclusion).
    (insights / "ref.md").write_text(
        "---\ntype: claude-insight\n---\n\nrefs [[2026-04-18-demo-bk-snapshot]]\n",
        encoding="utf-8",
    )

    backup_root = tmp_path / "backup"  # Inside the vault — exercises the bug surface.
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1
    snapshot_migration.apply(legacy, str(backup_root))

    # 1. Live insight file IS rewritten to new stem (live rewrite still works).
    insight_text = (insights / "ref.md").read_text(encoding="utf-8")
    assert "[[2026-04-18-demo-bk-snapshot-143027]]" in insight_text
    assert "[[2026-04-18-demo-bk-snapshot]]" not in insight_text

    # 2. Live (renamed) snapshot file IS rewritten to new stem.
    new_path = sess / "2026-04-18-demo-bk-snapshot-143027.md"
    assert new_path.is_file()
    new_text = new_path.read_text(encoding="utf-8")
    assert "self-ref: [[2026-04-18-demo-bk-snapshot-143027]]" in new_text

    # 3. Backup copy MUST retain the OLD stem reference — backups are useless
    #    for rollback if they're rewritten alongside the live vault.
    backup_files = list((backup_root / "snapshot-legacy-filename").iterdir())
    assert len(backup_files) == 1
    backup_text = backup_files[0].read_text(encoding="utf-8")
    assert "self-ref: [[2026-04-18-demo-bk-snapshot]]" in backup_text, (
        "backup must NOT be rewritten — got: " + repr(backup_text)
    )
    assert "[[2026-04-18-demo-bk-snapshot-143027]]" not in backup_text


def test_legacy_rename_result_points_to_post_rename_path(tmp_path):
    """Regression: Result.note_path must reference the new filename after rename."""
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-rn-snapshot.md", session_id="sRN")
    _write_session(sess / "2026-04-18-demo-rn.md", session_id="sRN")
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1
    results = snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "applied"
    # Result.note_path must point at the post-rename file (which exists),
    # not the pre-rename path (which no longer exists).
    from pathlib import Path
    new_path = Path(results[0].note_path)
    assert new_path.is_file(), f"Result.note_path is not a file: {new_path}"
    assert new_path.name.endswith("-snapshot-143027.md"), f"unexpected name: {new_path.name}"
    # The old path must NOT exist
    old_path = sess / "2026-04-18-demo-rn-snapshot.md"
    assert not old_path.exists()


# ----- Copilot round-5 regression tests -----


def test_legacy_rename_runtime_collision_guard(tmp_path):
    """Round-5 regression: synthetic Issue must trigger the runtime
    collision guard at apply() time.

    scan() flags collisions via ``extra["unresolved"]=True``, but a
    synthetic Issue constructed without going through scan() (or a file
    that appears between scan and apply) would otherwise let
    ``os.rename`` silently overwrite the target on POSIX — destroying
    user data. apply() must re-check ``dst.exists()`` before renaming.
    """
    from scripts.vault_doctor_checks import Issue
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-cg-snapshot.md", session_id="sCG")
    # Pre-create the would-be target. scan() would mark this unresolved,
    # but we construct a synthetic Issue WITHOUT ``unresolved=True`` to
    # exercise the runtime guard inside apply().
    target = sess / "2026-04-18-demo-cg-snapshot-143027.md"
    target.write_text("--- pre-existing target content ---", encoding="utf-8")
    synthetic = Issue(
        check="snapshot-legacy-filename",
        note_path=str(sess / "2026-04-18-demo-cg-snapshot.md"),
        project="demo",
        current_source="2026-04-18-demo-cg-snapshot.md",
        proposed_source="2026-04-18-demo-cg-snapshot-143027.md",
        reason="rename adds HHMMSS",
        confidence=0.95,
        extra={
            "new_name": "2026-04-18-demo-cg-snapshot-143027.md",
            "vault_path": str(tmp_path),
            # NOTE: no "unresolved": True — simulates skipping scan's
            # collision check (synthetic Issue / race with another writer).
        },
    )
    results = snapshot_migration.apply([synthetic], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "unresolved", (
        f"expected 'unresolved' for runtime collision, got {results[0].status}: {results[0].error}"
    )
    assert "collision" in (results[0].error or "").lower()
    # Pre-existing target file must be UNTOUCHED (no silent overwrite).
    assert target.read_text(encoding="utf-8") == "--- pre-existing target content ---"
    # Source file must still exist (rename did not happen).
    assert (sess / "2026-04-18-demo-cg-snapshot.md").exists()


def test_apply_does_not_mutate_issue_note_path(tmp_path):
    """Round-5 regression: apply() must not mutate the passed-in
    ``Issue.note_path``.

    The Issue dataclass is shared with logging and may be reused by
    callers after apply() returns. Mutating it surprises callers and
    invalidates diagnostic snapshots.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    _write_legacy_snapshot(sess / "2026-04-18-demo-im-snapshot.md", session_id="sIM")
    _write_session(sess / "2026-04-18-demo-im.md", session_id="sIM")
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    # Capture pre-apply note_path values (deep enough to survive apply).
    pre_apply_paths = [i.note_path for i in issues]
    snapshot_migration.apply(issues, str(tmp_path / "backup"))
    post_apply_paths = [i.note_path for i in issues]
    assert pre_apply_paths == post_apply_paths, (
        f"Issue.note_path was mutated by apply():\n"
        f"  pre={pre_apply_paths}\n"
        f"  post={post_apply_paths}"
    )


def test_no_rollback_after_partial_wikilink_rewrite(tmp_path, monkeypatch):
    """Round-5 regression: when ``_rewrite_wikilinks_in_vault`` raises
    AFTER successfully rewriting at least one file, apply() must NOT
    roll back the rename — rolling back would orphan the surviving
    rewrites (they would reference a missing file).

    The Result must surface the partial state via ``status="error"``
    with a descriptive message, and ``renamed_paths`` must record the
    rename so subsequent issues in the batch resolve correctly.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    legacy_path = sess / "2026-04-18-demo-pr-snapshot.md"
    _write_legacy_snapshot(legacy_path, session_id="sPR")
    _write_session(sess / "2026-04-18-demo-pr.md", session_id="sPR")
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650
    )
    legacy = [i for i in issues if i.check == "snapshot-legacy-filename"]
    assert len(legacy) == 1

    # Simulate a partial-success failure: rewriter raises with
    # ``modified_paths`` already populated (some files succeeded).
    def _partial_boom(*args, **kwargs):
        err = RuntimeError("simulated wikilink failure after partial success")
        err.modified_paths = ["/fake/successful/insight.md"]  # type: ignore[attr-defined]
        raise err

    monkeypatch.setattr(snapshot_migration, "_rewrite_wikilinks_in_vault", _partial_boom)
    results = snapshot_migration.apply(legacy, str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "error", (
        f"expected error for partial-rewrite failure, got {results[0].status}"
    )
    assert "partially failed" in (results[0].error or "").lower(), results[0].error
    assert "manual review" in (results[0].error or "").lower(), results[0].error
    # Critical: rename was NOT rolled back. The new path exists, the old
    # path does not — surviving wikilink rewrites can still resolve.
    new_path = sess / "2026-04-18-demo-pr-snapshot-143027.md"
    assert new_path.exists(), (
        "rename must NOT be rolled back when wikilink rewrite partially succeeded "
        "(rollback would orphan the surviving rewrites)"
    )
    assert not legacy_path.exists(), "old path must not be restored"
    # Result.note_path points at the surviving (renamed) file so the user
    # can locate it for manual review.
    assert results[0].note_path == str(new_path)
