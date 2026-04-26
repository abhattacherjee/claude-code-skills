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


# ----- Issue #81 regression tests: duplicate-sid collision handling -----


def test_snapshot_broken_backlink_ambiguous_when_duplicate_session_ids(tmp_path):
    """Snapshots with duplicate candidate sessions for the same
    ``session_id`` must be treated as unresolved rather than as having
    a confidently broken backlink.

    When multiple session notes share the same ``session_id``, the
    checker cannot reliably determine which note a
    ``source_session_note`` should reference. In that ambiguous case,
    the snapshot is classified as a snapshot-orphan (unresolved), and
    no ``snapshot-broken-backlink`` issue is emitted.
    """
    vault = tmp_path
    sess = vault / "claude-sessions"; sess.mkdir()
    sid = "11111111-2222-3333-4444-555555555555"
    # Two sessions sharing the same session_id on different dates.
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
    # Snapshot with source_session_note pointing at "something-that-could-match-either".
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        f'project: demo\ntrigger: compact\nstatus: summarized\n'
        f'source_session_note: "[[something-that-could-match-either]]"\n---\n\n# Snap\n\n'
        "## Summary\nbody\n",
        encoding="utf-8",
    )
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30,
    )
    # Filter to issues for THIS snapshot (ignore session-list issues etc.)
    snap_issues = [i for i in issues if i.note_path == str(snap)]
    assert len(snap_issues) == 1, (
        f"expected exactly one issue for the colliding snapshot, got {snap_issues}"
    )
    issue = snap_issues[0]
    assert issue.check == "snapshot-orphan", (
        f"colliding-sid snapshot must route to snapshot-orphan, got check={issue.check!r}"
    )
    assert issue.extra.get("unresolved") is True, (
        f"ambiguous parent must be unresolved, got extra={issue.extra}"
    )
    assert "ambiguous" in issue.reason, (
        f"reason must contain 'ambiguous', got: {issue.reason!r}"
    )
    assert sid in issue.reason, (
        f"reason must contain the full sid {sid!r} for grep, got: {issue.reason!r}"
    )
    # Absolutely no snapshot-broken-backlink for this snapshot (would suggest
    # a confidently-wrong parent).
    broken = [i for i in issues
              if i.check == "snapshot-broken-backlink" and i.note_path == str(snap)]
    assert broken == [], (
        f"colliding sid must NOT produce snapshot-broken-backlink, got: {broken}"
    )
    # Forward-consistency loop iterates sessions_by_id.items() and can
    # emit session-snapshot-list-missing / session-snapshot-list-stale
    # against either of the colliding session notes. Colliding sids
    # must be excluded from that loop so neither session note receives
    # a list-consistency issue triggered by this snapshot.
    sess_paths = {
        str(sess / "2026-04-15-demo-first.md"),
        str(sess / "2026-04-18-demo-second.md"),
    }
    forward = [
        i for i in issues
        if i.check in ("session-snapshot-list-missing", "session-snapshot-list-stale")
        and i.note_path in sess_paths
    ]
    assert forward == [], (
        f"colliding-sid sessions must be skipped in forward-consistency loop, got: {forward}"
    )


# ----- Issue #81 follow-ups from PR #85 review -----


def test_snapshot_broken_backlink_cross_project_collision_detected_with_project_filter(tmp_path):
    """Issue #81 second-order: --project=foo must NOT silently disarm
    collision detection when colliding sessions span projects. The
    cross-project scenario is exactly the class vault-doctor is meant
    to catch (project-rename migrations, re-imports), and without
    project-blind collision detection the broken-backlink path would
    emit a confident wrong fix inside the filtered scan.
    """
    vault = tmp_path
    sess = vault / "claude-sessions"; sess.mkdir()
    sid = "cross-proj-aaaa-bbbb-cccc-dddddddddddd"
    (sess / "2026-04-15-demo-collide.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-15\nsession_id: {sid}\n"
        "project: demo\nstatus: summarized\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    (sess / "2026-04-18-other-collide.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-18\nsession_id: {sid}\n"
        "project: other\nstatus: summarized\n---\n\n# Other\n",
        encoding="utf-8",
    )
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid}\n"
        f'project: demo\ntrigger: compact\nstatus: summarized\n'
        f'source_session_note: "[[2026-04-15-demo-collide]]"\n---\n\n# Snap\n\n'
        "## Summary\nbody\n",
        encoding="utf-8",
    )
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30, project="demo",
    )
    snap_issues = [i for i in issues if i.note_path == str(snap)]
    assert len(snap_issues) == 1, (
        f"expected exactly one issue for the cross-project colliding snapshot, got {snap_issues}"
    )
    issue = snap_issues[0]
    assert issue.check == "snapshot-orphan", (
        f"cross-project collision must route to snapshot-orphan, got check={issue.check!r}"
    )
    assert issue.extra.get("unresolved") is True
    assert "ambiguous" in issue.reason
    assert sid in issue.reason
    broken = [i for i in issues
              if i.check == "snapshot-broken-backlink" and i.note_path == str(snap)]
    assert broken == [], (
        f"cross-project colliding sid must NOT produce snapshot-broken-backlink, got: {broken}"
    )


def test_snapshot_broken_backlink_three_way_sid_collision(tmp_path):
    """Issue #81: three session notes sharing one sid all route the
    snapshot to ambiguous orphan (refactor guard — ensures the filter
    is triggered on the nth duplicate, not only the second).
    """
    vault = tmp_path
    sess = vault / "claude-sessions"; sess.mkdir()
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
        f'project: demo\ntrigger: compact\nstatus: summarized\n'
        f'source_session_note: "[[2026-04-15-demo-s1]]"\n---\n\n# Snap\n\n'
        "## Summary\nbody\n",
        encoding="utf-8",
    )
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30,
    )
    snap_issues = [i for i in issues if i.note_path == str(snap)]
    assert len(snap_issues) == 1
    assert snap_issues[0].check == "snapshot-orphan"
    assert snap_issues[0].extra.get("unresolved") is True
    assert "ambiguous" in snap_issues[0].reason
    assert sid in snap_issues[0].reason


def test_snapshot_broken_backlink_mixed_collision_and_unique_sids(tmp_path):
    """Issue #81: collision filter is per-sid — a scan with one
    colliding and one unique sid must ambiguate the colliding snapshot
    while still resolving the unique snapshot normally (no
    snapshot-broken-backlink if its wikilink matches the unique parent).
    """
    vault = tmp_path
    sess = vault / "claude-sessions"; sess.mkdir()
    sid_collide = "mix-collide-aaaa-bbbb-cccc-dddddddddddd"
    sid_unique = "mix-unique-1111-2222-3333-444444444444"
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
    unique_stem = "2026-04-17-demo-unique"
    (sess / f"{unique_stem}.md").write_text(
        f"---\ntype: claude-session\ndate: 2026-04-17\nsession_id: {sid_unique}\n"
        "project: demo\nstatus: summarized\n---\n\n# Unique\n",
        encoding="utf-8",
    )
    snap_c = sess / "2026-04-18-demo-collide-snap-120000.md"
    snap_c.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid_collide}\n"
        f'project: demo\ntrigger: compact\nstatus: summarized\n'
        f'source_session_note: "[[2026-04-15-demo-dup1]]"\n---\n\n# SnapC\n\n'
        "## Summary\nbody\n",
        encoding="utf-8",
    )
    snap_u = sess / "2026-04-18-demo-unique-snap-120000.md"
    snap_u.write_text(
        f"---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: {sid_unique}\n"
        f'project: demo\ntrigger: compact\nstatus: summarized\n'
        f'source_session_note: "[[{unique_stem}]]"\n---\n\n# SnapU\n\n'
        "## Summary\nbody\n",
        encoding="utf-8",
    )
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30,
    )
    # Colliding snapshot → ambiguous orphan, no broken-backlink
    snap_c_issues = [i for i in issues if i.note_path == str(snap_c)]
    assert len(snap_c_issues) == 1
    assert snap_c_issues[0].check == "snapshot-orphan"
    assert snap_c_issues[0].extra.get("unresolved") is True
    assert "ambiguous" in snap_c_issues[0].reason
    # Unique snapshot → no issues (wikilink matches parent stem)
    snap_u_issues = [i for i in issues if i.note_path == str(snap_u)]
    assert snap_u_issues == [], (
        f"unique-sid snapshot with correct backlink must produce no issues, got: {snap_u_issues}"
    )


def test_snapshot_orphan_empty_session_id_emits_specific_reason(tmp_path):
    """Parity with snapshot_migration.py §3: a snapshot with no
    session_id in frontmatter must get a specific reason, not the
    generic 'no session note matches this session_id' (which would
    interpolate an empty sid and confuse operators).
    """
    vault = tmp_path
    sess = vault / "claude-sessions"; sess.mkdir()
    snap = sess / "2026-04-18-demo-snap-120000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n# Snap\n",
        encoding="utf-8",
    )
    issues = snapshot_integrity.scan(
        str(vault), "claude-sessions", "claude-insights", 30,
    )
    snap_issues = [i for i in issues if i.note_path == str(snap)]
    # Expect exactly one snapshot-orphan with the specific empty-sid reason.
    orphans = [i for i in snap_issues if i.check == "snapshot-orphan"]
    assert len(orphans) == 1, f"expected one snapshot-orphan, got {orphans}"
    assert orphans[0].extra.get("unresolved") is True
    assert "no session_id" in orphans[0].reason, (
        f"reason must explicitly name the missing field, got: {orphans[0].reason!r}"
    )
    # The generic missing-parent reason must NOT be used (would interpolate empty sid).
    assert "no session note on disk matches" not in orphans[0].reason, (
        f"empty-sid must get specific reason, not the generic missing-parent reason, got: {orphans[0].reason!r}"
    )
