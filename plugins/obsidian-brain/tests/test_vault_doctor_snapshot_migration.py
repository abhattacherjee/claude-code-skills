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
    """Normal same-date case — parent resolves via sessions_by_id.

    Uses an arbitrary (non-hash-based) parent filename to prove the
    resolver is truly keyed on session_id frontmatter, not on a
    filename shape that happens to match the old (date, slug, sid_hash)
    composer. Under pre-#68 code, the fabricated stem
    "2026-04-18-demo-<sha256('s4')[:4]>" would NOT match the actual
    filename here — pre-#68 would emit unresolved=True, this test
    would fail.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "s4"
    # Non-hash filename — deliberately does not match the old
    # (date, slug, sid_hash) composer output.
    parent_stem = "2026-04-18-demo-parent"
    (sess / f"{parent_stem}.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )
    # Snapshot filename also does not need to follow any specific scheme.
    p = sess / "2026-04-18-demo-snap-110000.md"
    p.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\nproject: demo\n"
        "trigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert not miss[0].extra.get("unresolved")  # parent resolved via session_id
    assert miss[0].extra["parent_stem"] == parent_stem
    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = p.read_text(encoding="utf-8")
    assert f'source_session_note: "[[{parent_stem}]]"' in text


def test_missing_backlink_unresolved_when_parent_absent(tmp_path):
    """Orphan snapshot (no session note matches session_id) -> unresolved.

    Only the first two assertions (len==1, unresolved=True) held under
    pre-#68 behavior; the three new assertions below (proposed_source=="",
    confidence==0.0, reason contains "parent session not found") encode
    tighter post-fix semantics that the old code — which fabricated a
    speculative wikilink with confidence=0.3 — did not satisfy.
    """
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
    assert miss[0].proposed_source == ""
    assert miss[0].confidence == 0.0
    assert "parent session not found" in miss[0].reason


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
    # The hash-based parent stem is vestigial — post-#68 the resolver
    # matches on session_id in frontmatter, not on filename shape. Any
    # filename carrying session_id="eeee" in frontmatter would work;
    # this form preserves the pre-#68 fixture for minimal churn.
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


def test_missing_backlink_unresolved_when_project_missing(tmp_path):
    """No project in snapshot frontmatter -> unresolved.

    Covers the second half of the `not sid or not proj` guard (the
    sid-missing half is covered by test_missing_backlink_unresolved_when_sid_missing).
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    p = sess / "2026-04-18-demo-ff-snapshot-100000.md"
    p.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: sid-abc\n"
        "trigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(str(tmp_path), "claude-sessions", "claude-insights", 3650)
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert miss[0].extra.get("unresolved")
    assert "project" in miss[0].reason
    assert "session_id" not in miss[0].reason


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


def test_missing_backlink_cross_midnight_uses_session_id_index(tmp_path):
    """Snapshot from before-midnight must backlink to after-midnight parent.

    Regression for #68: §3 previously composed the parent stem from the
    snapshot's own `date` field, which breaks when PreCompact fires on
    day N and SessionEnd on day N+1. The parent is now resolved via
    sessions_by_id keyed by session_id, which is stable across midnight.
    """
    import hashlib as _h
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "cross-midnight-sid"
    hash4 = _h.sha256(sid.encode()).hexdigest()[:4]

    # Parent session — dated the day AFTER the snapshot. Written inline
    # (not via _write_session helper) so the frontmatter date matches
    # the filename date — keeps this cross-midnight fixture internally
    # consistent and self-documenting.
    parent_stem = f"2026-04-10-demo-{hash4}"
    (sess / f"{parent_stem}.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-10\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )

    # Snapshot — dated the day BEFORE its parent session (cross-midnight)
    snap = sess / f"2026-04-09-demo-{hash4}-snapshot-235959.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-09\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )

    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650,
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1
    assert not miss[0].extra.get("unresolved")
    assert miss[0].extra["parent_stem"] == parent_stem
    # Proposal must reference the AFTER-midnight parent, not the snapshot's own date
    assert f'source_session_note: "[[{parent_stem}]]"' in miss[0].proposed_source
    assert "2026-04-09-demo-" not in miss[0].proposed_source

    snapshot_migration.apply(miss, str(tmp_path / "backup"))
    text = snap.read_text(encoding="utf-8")
    assert f'source_session_note: "[[{parent_stem}]]"' in text


# ----- Issue #81 regression tests: duplicate-sid collision handling -----


def test_missing_backlink_ambiguous_when_duplicate_session_ids(tmp_path):
    """When multiple session notes carry the same sid, ``sessions_by_id``
    must not pick an arbitrary winner for backlink resolution. Instead,
    scan() detects sid collisions while building the index and treats
    snapshots with that sid as unresolved.

    Expected behavior: emit an UNRESOLVED Issue for snapshots whose sid
    is in the collision set — never a speculative
    ``source_session_note`` wikilink. The reason string contains both
    "ambiguous" (human-readable marker) and the full sid (greppable by
    operators).
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "11111111-2222-3333-4444-555555555555"
    # Two sessions sharing the same session_id on different dates.
    # Write them directly (not via _write_session) so filename date
    # matches frontmatter date per PR #80 review guidance.
    (sess / "2026-04-15-demo-first.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-15\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# S1\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-demo-second.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# S2\n",
        encoding="utf-8",
    )
    # Snapshot missing source_session_note (the §3 trigger) with the colliding sid.
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650,
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1, f"expected exactly one snapshot-missing-backlink, got {miss}"
    assert miss[0].extra.get("unresolved") is True, (
        f"duplicate-sid snapshot must be unresolved, got extra={miss[0].extra}"
    )
    assert miss[0].proposed_source == "", (
        f"must not fabricate a wikilink for ambiguous parent, got proposed_source={miss[0].proposed_source!r}"
    )
    assert miss[0].confidence == 0.0, (
        f"ambiguous parent must have confidence=0.0, got {miss[0].confidence}"
    )
    assert "ambiguous" in miss[0].reason, (
        f"reason must contain 'ambiguous', got: {miss[0].reason!r}"
    )
    assert sid in miss[0].reason, (
        f"reason must contain the full sid {sid!r} for grep, got: {miss[0].reason!r}"
    )

    # §4 must NOT emit a session-missing-snapshots-list for the colliding sid
    # (neither session can be declared the authoritative parent).
    sess_miss = [i for i in issues if i.check == "session-missing-snapshots-list"]
    for issue in sess_miss:
        # If §4 fires, it must not be for either of the two colliding sessions.
        assert not issue.note_path.endswith("2026-04-15-demo-first.md"), (
            f"§4 must not emit for a colliding-sid session, got: {issue}"
        )
        assert not issue.note_path.endswith("2026-04-18-demo-second.md"), (
            f"§4 must not emit for a colliding-sid session, got: {issue}"
        )


def test_missing_backlink_two_snapshots_sharing_session_id_both_resolve(tmp_path):
    """Regression guard: two snapshots for ONE session (non-colliding) both backlink.

    Simulates two PreCompact fires within a single session. The sid
    points at a UNIQUE session (no collision) and both snapshots must
    resolve via ``sessions_by_id`` with confidence 0.95 — the
    collision-detection path must not over-trigger on the legitimate
    "multiple snapshots per session" case.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "unique-session-id-xyz"
    parent_stem = "2026-04-18-demo-multi"
    (sess / f"{parent_stem}.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )
    snap_a = sess / "2026-04-18-demo-multi-snap-100000.md"
    snap_a.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap A\n",
        encoding="utf-8",
    )
    snap_b = sess / "2026-04-18-demo-multi-snap-140000.md"
    snap_b.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap B\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650,
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 2, (
        f"expected two snapshot-missing-backlink (one per snapshot), got {len(miss)}: {miss}"
    )
    for issue in miss:
        assert issue.extra.get("unresolved") is False, (
            f"non-colliding sid must resolve, got extra={issue.extra}"
        )
        assert issue.extra.get("parent_stem") == parent_stem, (
            f"parent_stem must be {parent_stem!r}, got {issue.extra.get('parent_stem')!r}"
        )
        assert issue.confidence == 0.95, (
            f"non-colliding resolution must have confidence=0.95, got {issue.confidence}"
        )


# ----- Issue #81 follow-ups from PR #85 review -----


def test_missing_backlink_cross_project_collision_detected_with_project_filter(tmp_path):
    """Issue #81 second-order: --project=foo must NOT silently disarm
    collision detection when colliding sessions span projects.

    Scenario: one session in project ``demo`` and one in project
    ``other`` share a session_id. The user runs ``scan(project="demo")``
    expecting project-scoped issues. Without project-blind collision
    detection, the ``other`` session gets filtered out at ingest, the
    collision goes unregistered, and the demo snapshot's backlink falls
    back to an arbitrary filesystem-order-dependent winner — resurrecting
    exactly the bug this PR fixes, inside the filtered scan.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "cross-proj-2222-3333-4444-555555555555"
    (sess / "2026-04-15-demo-collide.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-15\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# Demo session\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-other-collide.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: other\nstatus: summarized\n---\n\n# Other session\n",
        encoding="utf-8",
    )
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650, project="demo",
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1, f"expected one snapshot-missing-backlink, got {miss}"
    assert miss[0].extra.get("unresolved") is True, (
        f"cross-project collision must still be ambiguous under --project filter, "
        f"got extra={miss[0].extra}"
    )
    assert "ambiguous" in miss[0].reason, (
        f"reason must contain 'ambiguous', got: {miss[0].reason!r}"
    )
    assert sid in miss[0].reason, (
        f"reason must contain the full sid for grep, got: {miss[0].reason!r}"
    )


def test_missing_backlink_three_way_sid_collision(tmp_path):
    """Issue #81: three session notes sharing one sid all trigger the
    ambiguous branch (guards against a future refactor that branches on
    "first duplicate vs. nth duplicate").
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid = "three-way-aaaa-bbbb-cccc-dddddddddddd"
    for n, date in enumerate(("2026-04-15", "2026-04-16", "2026-04-17"), start=1):
        (sess / f"{date}-demo-s{n}.md").write_text(
            f"---\ntype: claude-session\ndate: {date}\nsession_id: {sid}\n"
            f"project: demo\nstatus: summarized\n---\n\n# S{n}\n",
            encoding="utf-8",
        )
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650,
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    assert len(miss) == 1, f"expected one snapshot-missing-backlink, got {miss}"
    assert miss[0].extra.get("unresolved") is True
    assert "ambiguous" in miss[0].reason
    assert sid in miss[0].reason


def test_missing_backlink_mixed_collision_and_unique_sids(tmp_path):
    """Issue #81: collision filter is per-sid, not global. A scan with
    both a colliding sid and a unique sid must flag the colliding
    snapshot as ambiguous AND resolve the unique snapshot normally.
    """
    sess = tmp_path / "claude-sessions"; sess.mkdir()
    sid_collide = "mix-collide-aaaa-bbbb-cccc-dddddddddddd"
    sid_unique = "mix-unique-1111-2222-3333-444444444444"
    # Two sessions sharing sid_collide
    (sess / "2026-04-15-demo-dup1.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-15\nsession_id: {sid_collide}\n"
        "project: demo\nstatus: summarized\n---\n\n# Dup1\n",
        encoding="utf-8",
    )
    (sess / "2026-04-16-demo-dup2.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-16\nsession_id: {sid_collide}\n"
        "project: demo\nstatus: summarized\n---\n\n# Dup2\n",
        encoding="utf-8",
    )
    # One session with sid_unique
    unique_stem = "2026-04-17-demo-unique"
    (sess / f"{unique_stem}.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-17\nsession_id: {sid_unique}\n"
        "project: demo\nstatus: summarized\n---\n\n# Unique\n",
        encoding="utf-8",
    )
    # Snapshot for the colliding sid
    snap_c = sess / "2026-04-18-demo-collide-snap-120000.md"
    snap_c.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid_collide}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# SnapC\n",
        encoding="utf-8",
    )
    # Snapshot for the unique sid
    snap_u = sess / "2026-04-18-demo-unique-snap-120000.md"
    snap_u.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid_unique}\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# SnapU\n",
        encoding="utf-8",
    )
    issues = snapshot_migration.scan(
        str(tmp_path), "claude-sessions", "claude-insights", 3650,
    )
    miss = [i for i in issues if i.check == "snapshot-missing-backlink"]
    by_path = {i.note_path: i for i in miss}
    assert str(snap_c) in by_path and str(snap_u) in by_path, (
        f"expected issues for both snapshots, got paths={list(by_path)}"
    )
    # Colliding snapshot → ambiguous/unresolved
    ic = by_path[str(snap_c)]
    assert ic.extra.get("unresolved") is True
    assert "ambiguous" in ic.reason
    assert sid_collide in ic.reason
    # Unique snapshot → resolved with parent_stem
    iu = by_path[str(snap_u)]
    assert iu.extra.get("unresolved") is False, (
        f"unique sid must resolve, got extra={iu.extra}"
    )
    assert iu.extra.get("parent_stem") == unique_stem
    assert iu.confidence == 0.95
