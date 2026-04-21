from pathlib import Path

from scripts.vault_doctor_checks import Issue, snapshot_integrity


def _write_snapshot(path, session_id, backlink_stem, status="summarized", has_summary=True):
    summary_body = "## Summary\nbody\n" if has_summary else ""
    path.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {session_id}\n"
        f"project: demo\ntrigger: compact\nstatus: {status}\n"
        f'source_session_note: "[[{backlink_stem}]]"\n---\n\n# Snap\n\n{summary_body}',
        encoding="utf-8",
    )


def _write_session(path, session_id, snapshots: list[str] | None = None):
    snap_block = ""
    if snapshots:
        snap_block = "snapshots:\n" + "\n".join(f'  - "{s}"' for s in snapshots) + "\n"
    path.write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {session_id}\n"
        f"project: demo\n{snap_block}status: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )


def test_orphan_snapshot_detected(tmp_path):
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "missing", "nothing")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    orphans = [i for i in issues if i.check == "snapshot-orphan"]
    assert len(orphans) == 1


def test_broken_backlink_is_rebuilt_when_session_findable(tmp_path):
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-aa.md", "s1")
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "s1", "wrong-stem")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    broken = [i for i in issues if i.check == "snapshot-broken-backlink"]
    assert len(broken) == 1
    assert "2026-04-18-demo-aa" in broken[0].proposed_source


def test_session_missing_snapshots_list_is_fixed(tmp_path):
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-bb.md", "s2")
    _write_snapshot(sess / "2026-04-18-demo-bb-snapshot-100000.md", "s2", "2026-04-18-demo-bb")
    _write_snapshot(sess / "2026-04-18-demo-bb-snapshot-140000.md", "s2", "2026-04-18-demo-bb")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    missing = [i for i in issues if i.check == "session-snapshot-list-missing"]
    assert len(missing) == 1

    backup = tmp_path / "backup"
    snapshot_integrity.apply(missing, str(backup))

    text = (sess / "2026-04-18-demo-bb.md").read_text(encoding="utf-8")
    assert 'snapshots:' in text
    assert '2026-04-18-demo-bb-snapshot-100000' in text
    assert '2026-04-18-demo-bb-snapshot-140000' in text


def test_summary_status_mismatch_auto_fixes(tmp_path):
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-cc.md", "s3")
    # Status says auto-logged but ## Summary is already populated
    _write_snapshot(sess / "2026-04-18-demo-cc-snapshot-090000.md", "s3",
                    "2026-04-18-demo-cc", status="auto-logged", has_summary=True)
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    mismatches = [i for i in issues if i.check == "snapshot-summary-status-mismatch"]
    assert len(mismatches) == 1

    snapshot_integrity.apply(mismatches, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-cc-snapshot-090000.md").read_text(encoding="utf-8")
    assert "status: summarized" in text
    assert "status: auto-logged" not in text


def test_idempotent_scan_after_apply(tmp_path):
    """Running scan again after apply returns no issues."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-bb.md", "s2")
    _write_snapshot(sess / "2026-04-18-demo-bb-snapshot-100000.md", "s2", "2026-04-18-demo-bb")

    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    fixable = [i for i in issues if not i.extra.get("unresolved")]
    snapshot_integrity.apply(fixable, str(tmp_path / "backup"))
    reissues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    assert len(reissues) == 0


def test_orphan_apply_returns_unresolved(tmp_path):
    """Orphan check has no auto-fix; apply must record status='unresolved'."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "missing", "nothing")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    orphans = [i for i in issues if i.check == "snapshot-orphan"]
    results = snapshot_integrity.apply(orphans, str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "unresolved"


def test_broken_backlink_apply_rewrites_wikilink(tmp_path):
    """End-to-end apply for the broken-backlink fix path."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-aa.md", "s1")
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "s1", "wrong-stem")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    broken = [i for i in issues if i.check == "snapshot-broken-backlink"]
    snapshot_integrity.apply(broken, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-aa-snapshot-120000.md").read_text(encoding="utf-8")
    assert 'source_session_note: "[[2026-04-18-demo-aa]]"' in text
    assert "wrong-stem" not in text


def test_stale_snapshot_list_is_pruned(tmp_path):
    """End-to-end apply for the session-snapshot-list-stale fix path."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Session frontmatter lists two snapshots (in [[wikilink]] form, matching
    # the canonical format scan() produces), but only one exists on disk.
    _write_session(sess / "2026-04-18-demo-zz.md", "sZ", snapshots=[
        "[[2026-04-18-demo-zz-snapshot-100000]]",
        "[[2026-04-18-demo-zz-snapshot-200000]]",  # this one doesn't exist
    ])
    _write_snapshot(sess / "2026-04-18-demo-zz-snapshot-100000.md", "sZ", "2026-04-18-demo-zz")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    stale = [i for i in issues if i.check == "session-snapshot-list-stale"]
    assert len(stale) == 1
    snapshot_integrity.apply(stale, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-zz.md").read_text(encoding="utf-8")
    assert "2026-04-18-demo-zz-snapshot-100000" in text
    assert "2026-04-18-demo-zz-snapshot-200000" not in text


def test_summarized_without_summary_is_detected(tmp_path):
    """Status claims summarized but body has no ## Summary section."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-cc.md", "s3")
    _write_snapshot(sess / "2026-04-18-demo-cc-snapshot-090000.md", "s3",
                    "2026-04-18-demo-cc", status="summarized", has_summary=False)
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    mismatches = [i for i in issues if i.check == "snapshot-summary-status-mismatch"]
    assert len(mismatches) == 1
    snapshot_integrity.apply(mismatches, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-cc-snapshot-090000.md").read_text(encoding="utf-8")
    assert "status: auto-logged" in text


def test_session_missing_list_works_without_status_field(tmp_path):
    """Regression for HIGH-1: apply must succeed when session has no status: line."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Sparse legacy session — frontmatter has no status: field
    (sess / "2026-04-18-demo-bb.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s2\n"
        "project: demo\n---\n\n# S\n",
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-bb-snapshot-100000.md", "s2", "2026-04-18-demo-bb")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    missing = [i for i in issues if i.check == "session-snapshot-list-missing"]
    assert len(missing) == 1
    snapshot_integrity.apply(missing, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-bb.md").read_text(encoding="utf-8")
    assert 'snapshots:' in text
    assert '2026-04-18-demo-bb-snapshot-100000' in text
    # Idempotency — re-scan should find nothing
    reissues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    assert not any(i.check == "session-snapshot-list-missing" for i in reissues)


# ----- Coverage-focused tests (helpers, scan edge cases, apply edge cases) -----


def test_scan_returns_empty_when_sessions_dir_absent(tmp_path):
    """Vault has no claude-sessions/ at all."""
    issues = snapshot_integrity.scan(str(tmp_path), "claude-sessions", "claude-insights", 30)
    assert issues == []


def test_scan_skips_non_md_and_unparseable(tmp_path):
    """scan() iterdir loop must skip non-.md, empty, and no-frontmatter files."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Non-.md file (skipped on suffix check)
    (sess / "notes.txt").write_text("plain text", encoding="utf-8")
    # Empty .md file (returned text is "" so falsy)
    (sess / "empty.md").write_text("", encoding="utf-8")
    # .md with no frontmatter at all
    (sess / "no-fm.md").write_text("# heading only\n", encoding="utf-8")
    # .md with frontmatter but no project/type — still parsed but won't match
    (sess / "stub.md").write_text("---\nfoo: bar\n---\n", encoding="utf-8")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    assert issues == []


def test_scan_filters_by_project(tmp_path):
    """_project_matches drops notes from a different project when filter set."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-aa.md", "s1")
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "s1", "wrong-stem")
    # Filter for a project that doesn't exist
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30, project="other-project"
    )
    assert issues == []
    # Same vault, matching project filter (case-insensitive)
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30, project="DEMO"
    )
    assert any(i.check == "snapshot-broken-backlink" for i in issues)


def test_scan_skips_session_with_blank_session_id(tmp_path):
    """Session note with empty session_id field must not be indexed."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    (sess / "2026-04-18-demo-no-sid.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id:\n"
        "project: demo\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )
    # And a snapshot pointing to a (non-)existent session
    _write_snapshot(sess / "2026-04-18-demo-bb-snapshot-100000.md", "ghost", "ghost-stem")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    # Should be flagged as orphan
    assert any(i.check == "snapshot-orphan" for i in issues)


def test_session_with_no_snapshots_skipped(tmp_path):
    """Session that has zero snapshots on disk must not produce any issue."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-nn.md", "sN")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    # No snapshots, no issues
    assert issues == []


def test_apply_unknown_check_is_skipped(tmp_path):
    """apply() with an Issue whose check name has no branch must record skipped."""
    issue = Issue(
        check="bogus-check-name",
        note_path=str(tmp_path / "x.md"),
        project="demo",
        current_source="",
        proposed_source="",
        reason="synthetic",
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "skipped"


def test_apply_records_error_when_note_missing(tmp_path):
    """apply() must record status='error' when the target note can't be read/written."""
    # Construct a session-snapshot-list-missing Issue pointing at a path
    # whose parent dir doesn't exist, so _write_atomic raises.
    bogus_path = str(tmp_path / "no-such-dir" / "ghost.md")
    issue = Issue(
        check="session-snapshot-list-missing",
        note_path=bogus_path,
        project="demo",
        current_source="",
        proposed_source="[[2026-04-18-demo-xx-snapshot-100000]]",
        reason="synthetic",
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert len(results) == 1
    # Either RuntimeError (no fence in empty text) or OSError on write
    assert results[0].status == "error"


def test_apply_broken_backlink_skipped_when_already_correct(tmp_path):
    """Re-applying a broken-backlink fix when source_session_note already correct → skipped."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-aa.md", "s1")
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "s1", "2026-04-18-demo-aa")
    # Manually craft an Issue that would no-op (proposed_source == current)
    issue = Issue(
        check="snapshot-broken-backlink",
        note_path=str(sess / "2026-04-18-demo-aa-snapshot-120000.md"),
        project="demo",
        current_source="[[2026-04-18-demo-aa]]",
        proposed_source="[[2026-04-18-demo-aa]]",
        reason="synthetic no-op",
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "skipped"


def test_apply_status_mismatch_skipped_when_already_correct(tmp_path):
    """status-mismatch apply must short-circuit when status already matches proposed."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-cc.md", "s3")
    # Snapshot already has status: summarized
    _write_snapshot(sess / "2026-04-18-demo-cc-snapshot-090000.md", "s3",
                    "2026-04-18-demo-cc", status="summarized", has_summary=True)
    issue = Issue(
        check="snapshot-summary-status-mismatch",
        note_path=str(sess / "2026-04-18-demo-cc-snapshot-090000.md"),
        project="demo",
        current_source="status=summarized",
        proposed_source="status=summarized",
        reason="synthetic no-op",
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "skipped"


def test_apply_stale_skipped_when_no_stale_entries(tmp_path):
    """stale-list apply with empty extra['stale'] must short-circuit."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-bb.md", "s2")
    issue = Issue(
        check="session-snapshot-list-stale",
        note_path=str(sess / "2026-04-18-demo-bb.md"),
        project="demo",
        current_source="",
        proposed_source="",
        reason="synthetic",
        extra={"stale": []},  # nothing to remove → no-op
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "skipped"


def test_apply_session_missing_runtime_error_on_no_frontmatter(tmp_path):
    """When session note has no frontmatter at all, apply must record error."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    bad_session = sess / "2026-04-18-demo-pp.md"
    bad_session.write_text("# no frontmatter here\n", encoding="utf-8")
    issue = Issue(
        check="session-snapshot-list-missing",
        note_path=str(bad_session),
        project="demo",
        current_source="",
        proposed_source="[[2026-04-18-demo-pp-snapshot-100000]]",
        reason="synthetic",
    )
    results = snapshot_integrity.apply([issue], str(tmp_path / "backup"))
    assert results[0].status == "error"
    assert "frontmatter" in (results[0].error or "")


def test_parse_fm_handles_messy_lines(tmp_path):
    """Cover _parse_fm branches: blank/indented lines, lines without colon."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Frontmatter with a blank-continuation line and a no-colon stray line
    (sess / "2026-04-18-demo-qq.md").write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-18\n"
        "session_id: sQ\n"
        "project: demo\n"
        "status: summarized\n"
        "  indented_stray_line\n"
        "no_colon_line\n"
        "---\n\n# S\n",
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-qq-snapshot-100000.md", "sQ", "2026-04-18-demo-qq")
    # Should still resolve and produce no issues (snapshot has matching parent)
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    # Only the missing-list issue should fire
    assert any(i.check == "session-snapshot-list-missing" for i in issues)


def test_inline_yaml_snapshots_list_is_treated_as_missing(tmp_path):
    """MEDIUM-1 regression: inline `snapshots: [...]` parses as string; isinstance guard kicks in."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Inline-list YAML — _parse_fm will store this as a string, not a list.
    (sess / "2026-04-18-demo-ii.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: sI\n"
        "project: demo\nsnapshots: [foo, bar]\nstatus: summarized\n---\n\n# S\n",
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-ii-snapshot-100000.md", "sI", "2026-04-18-demo-ii")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    # Should treat inline-string as "no list" → emits missing, NOT stale.
    assert any(i.check == "session-snapshot-list-missing" for i in issues)
    assert not any(i.check == "session-snapshot-list-stale" for i in issues)


# ----- PR-review regression tests -----


def test_status_injection_not_corrupted_by_body_status_line(tmp_path):
    """CRITICAL-4 regression: a ``status:`` line in the BODY (e.g. inside a
    code block or after a ``## Status`` heading) must NOT be matched by the
    snapshots-block injection regex. The block must land inside the
    frontmatter, and the body must be left untouched.
    """
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Session WITHOUT a status: line in the frontmatter, but body contains
    # ``status: active`` starting a line inside a fenced code block.
    (sess / "2026-04-18-demo-sb.md").write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-18\n"
        "session_id: sB\n"
        "project: demo\n"
        "---\n\n"
        "# Session\n\n"
        "## Status of things\n"
        "status: active\n"  # body line that naively matches ^status:
        "\n"
        "```yaml\n"
        "status: inside-code-block\n"
        "```\n",
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-sb-snapshot-100000.md", "sB",
                    "2026-04-18-demo-sb")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    missing = [i for i in issues if i.check == "session-snapshot-list-missing"]
    assert len(missing) == 1
    snapshot_integrity.apply(missing, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-sb.md").read_text(encoding="utf-8")
    # Body must still contain both status: lines verbatim (unmodified)
    assert "## Status of things\nstatus: active\n" in text
    assert "status: inside-code-block" in text
    # Frontmatter (first ---\n … ---\n) must contain the snapshots: block.
    fm_match = text.split("---\n", 2)
    assert len(fm_match) >= 3
    frontmatter = fm_match[1]
    assert "snapshots:" in frontmatter
    assert "2026-04-18-demo-sb-snapshot-100000" in frontmatter
    # The body portion must NOT carry an injected snapshots: block.
    body = fm_match[2]
    assert "snapshots:" not in body


def test_missing_list_apply_skipped_when_snapshots_already_present(tmp_path):
    """Regression: defensive re-check prevents duplicate snapshots: blocks.

    If a stale Issue from an earlier scan is replayed against a session
    whose frontmatter already contains ``snapshots:``, the apply path
    must short-circuit with status='skipped' rather than inject a
    duplicate block above ``status:``.
    """
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Session already has a snapshots: block in frontmatter
    _write_session(sess / "2026-04-18-demo-xx.md", "sX", snapshots=[
        "[[2026-04-18-demo-xx-snapshot-100000]]",
    ])
    _write_snapshot(sess / "2026-04-18-demo-xx-snapshot-100000.md", "sX", "2026-04-18-demo-xx")
    _write_snapshot(sess / "2026-04-18-demo-xx-snapshot-150000.md", "sX", "2026-04-18-demo-xx")
    # Build a stale/replayed Issue: scan() wouldn't emit this since snapshots:
    # is present, but we construct one directly to simulate stale-Issue replay.
    from scripts.vault_doctor_checks import Issue
    stale_issue = Issue(
        check="session-snapshot-list-missing",
        note_path=str(sess / "2026-04-18-demo-xx.md"),
        project="demo",
        current_source="snapshots field absent",
        proposed_source="[[2026-04-18-demo-xx-snapshot-150000]]",
        reason="stale replay",
        confidence=0.98,
    )
    results = snapshot_integrity.apply([stale_issue], str(tmp_path / "backup"))
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "already present" in (results[0].error or "")
    text = (sess / "2026-04-18-demo-xx.md").read_text(encoding="utf-8")
    # Exactly one snapshots: block
    assert text.count("snapshots:") == 1


def test_stale_apply_does_not_mutate_body_bullet_lists(tmp_path):
    """Regression: stale-entry removal must ONLY touch frontmatter, not body.

    The prior implementation used ``text.splitlines(keepends=True)``
    which scanned the entire file — so a body bullet list quoting a
    historical wikilink (e.g. in a ``## References`` section) was
    silently deleted. The PR guarantees mutations land inside
    frontmatter only.
    """
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Session frontmatter lists a stale snapshot; body has a bullet list
    # with the SAME pattern (user quoting a historical wikilink).
    stale_stem = "2026-04-18-demo-yy-snapshot-999999"
    (sess / "2026-04-18-demo-yy.md").write_text(
        f'---\ntype: claude-session\ndate: 2026-04-18\nsession_id: sY\nproject: demo\n'
        f'snapshots:\n  - "[[{stale_stem}]]"\n  - "[[2026-04-18-demo-yy-snapshot-100000]]"\n'
        f'status: summarized\n---\n\n# S\n\n## References\n\n'
        f'- "[[{stale_stem}]]"\n'
        "- Important body bullet that happens to match the pattern\n",
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-yy-snapshot-100000.md", "sY", "2026-04-18-demo-yy")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    stale = [i for i in issues if i.check == "session-snapshot-list-stale"]
    assert len(stale) == 1
    snapshot_integrity.apply(stale, str(tmp_path / "backup"))
    text = (sess / "2026-04-18-demo-yy.md").read_text(encoding="utf-8")
    # Stale entry removed from frontmatter
    assert f'[[{stale_stem}]]' not in text.split("---\n", 2)[1]
    # Body bullet NOT deleted
    assert f'- "[[{stale_stem}]]"' in text.split("---\n", 2)[2]


def test_crlf_frontmatter_is_parsed(tmp_path):
    """HIGH-5 regression: notes with CRLF line endings must still be picked up."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    # Raw CRLF on disk; no BOM.
    (sess / "2026-04-18-demo-cr.md").write_bytes(
        b"---\r\ntype: claude-session\r\ndate: 2026-04-18\r\n"
        b"session_id: sCR\r\nproject: demo\r\nstatus: summarized\r\n---\r\n\r\n# S\r\n"
    )
    (sess / "2026-04-18-demo-cr-snapshot-100000.md").write_bytes(
        b"---\r\ntype: claude-snapshot\r\ndate: 2026-04-18\r\n"
        b"session_id: sCR\r\nproject: demo\r\ntrigger: compact\r\n"
        b"status: summarized\r\n"
        b'source_session_note: "[[2026-04-18-demo-cr]]"\r\n---\r\n\r\n'
        b"# Snap\r\n\r\n## Summary\r\nbody\r\n"
    )
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    # Snapshot was backed up correctly, session has no snapshots: list yet —
    # so we expect the session-snapshot-list-missing issue to fire.
    assert any(i.check == "session-snapshot-list-missing" for i in issues), (
        "CRLF frontmatter must be normalised and detected"
    )


def test_apply_backup_path_points_to_backup_file_not_directory(tmp_path):
    """Regression: Result.backup_path must be the actual backup file, not the per-check directory."""
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    _write_session(sess / "2026-04-18-demo-aa.md", "s1")
    _write_snapshot(sess / "2026-04-18-demo-aa-snapshot-120000.md", "s1", "wrong-stem")
    issues = snapshot_integrity.scan(str(vault), "claude-sessions", "claude-insights", 30)
    broken = [i for i in issues if i.check == "snapshot-broken-backlink"]
    backup_root = tmp_path / "backup"
    results = snapshot_integrity.apply(broken, str(backup_root))
    assert len(results) == 1
    assert results[0].status == "applied"
    # backup_path must be a file, not a directory
    backup_path = Path(results[0].backup_path)
    assert backup_path.is_file(), f"backup_path is not a file: {backup_path}"
    assert backup_path.name == "2026-04-18-demo-aa-snapshot-120000.md"


def test_stale_apply_handles_unquoted_yaml_list_items(tmp_path):
    """Copilot round-3 regression: apply must remove stale entries written
    as unquoted YAML scalars.

    ``_parse_fm`` strips surrounding quotes during scan, so ``- [[stem]]``
    (unquoted YAML scalar) and ``- "[[stem]]"`` both register as the same
    snapshot value. The prior apply branch only matched the quoted forms,
    so unquoted stale entries scanned as stale but applied as no-op —
    creating an idempotency illusion (status='skipped') while leaving the
    stale wikilink in place.
    """
    vault = tmp_path; sess = vault / "claude-sessions"; sess.mkdir()
    stale_stem = "2026-04-18-demo-uu-snapshot-999999"
    # Note the UNQUOTED list item form: `- [[...]]` instead of `- "[[...]]"`
    (sess / "2026-04-18-demo-uu.md").write_text(
        f'---\ntype: claude-session\ndate: 2026-04-18\nsession_id: sU\nproject: demo\n'
        f'snapshots:\n  - [[{stale_stem}]]\n  - [[2026-04-18-demo-uu-snapshot-100000]]\n'
        f'status: summarized\n---\n\n# S\n',
        encoding="utf-8",
    )
    _write_snapshot(sess / "2026-04-18-demo-uu-snapshot-100000.md", "sU",
                    "2026-04-18-demo-uu")
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30
    )
    stale = [i for i in issues if i.check == "session-snapshot-list-stale"]
    assert len(stale) == 1
    results = snapshot_integrity.apply(stale, str(tmp_path / "backup"))
    assert results[0].status == "applied", (
        f"unquoted stale entry should be pruned, got: {results[0].status} "
        f"({results[0].error!r})"
    )
    text = (sess / "2026-04-18-demo-uu.md").read_text(encoding="utf-8")
    fm = text.split("---\n", 2)[1]
    # Unquoted stale entry pruned from frontmatter
    assert stale_stem not in fm
    # Live entry preserved
    assert "2026-04-18-demo-uu-snapshot-100000" in fm
