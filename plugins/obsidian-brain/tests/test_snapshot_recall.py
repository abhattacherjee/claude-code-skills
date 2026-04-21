from pathlib import Path

from hooks.obsidian_utils import build_context_brief, fetch_snapshot_summaries


def _fixture(path, type_, sid, date, project="demo", extras="", body="body"):
    path.write_text(
        f"---\ntype: {type_}\ndate: {date}\nsession_id: {sid}\n"
        f"project: {project}\nstatus: summarized\n{extras}---\n\n"
        f"# Title\n\n## Summary\n{body}\n",
        encoding="utf-8",
    )


def test_build_context_brief_filters_snapshots_from_top_level(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    ins = vault / "claude-insights"
    sess.mkdir(parents=True); ins.mkdir()
    _fixture(sess / "2026-04-18-demo-aaaa.md", "claude-session", "s1", "2026-04-18",
             extras="duration_minutes: 30\ngit_branch: develop\n", body="Session A ran through checklist.")
    _fixture(sess / "2026-04-18-demo-aaaa-snapshot-140000.md", "claude-snapshot", "s1",
             "2026-04-18", body="Pre-compact checkpoint.")
    out = build_context_brief(str(vault), "claude-sessions", "claude-insights", "demo")
    # Table row count: top-level line 1 (session A) — snapshot should not appear
    # as a top-level numbered row.
    assert "| 1 | 2026-04-18" in out
    assert "| 2 | 2026-04-18" not in out  # only 1 session => 1 row
    # Nested indented row present below the session
    assert "↳ 14:00:00" in out or "↳ 140000" in out


def test_fetch_snapshot_summaries_returns_ordered_items(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    _fixture(sess / "2026-04-18-demo-bbbb-snapshot-150000.md", "claude-snapshot",
             "s2", "2026-04-18", body="Later checkpoint.")
    _fixture(sess / "2026-04-18-demo-bbbb-snapshot-100000.md", "claude-snapshot",
             "s2", "2026-04-18", body="Earlier checkpoint.")
    items = fetch_snapshot_summaries(sess, "s2", "2026-04-18", "demo")
    assert len(items) == 2
    assert items[0]["hhmmss"] == "100000"
    assert items[1]["hhmmss"] == "150000"
    assert "Earlier" in items[0]["summary"]


def test_build_context_brief_emits_snapshot_count_in_load_manifest(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    ins = vault / "claude-insights"
    sess.mkdir(parents=True); ins.mkdir()
    _fixture(sess / "2026-04-18-demo-cccc.md", "claude-session", "s3", "2026-04-18",
             extras="duration_minutes: 45\ngit_branch: develop\n", body="Main session.")
    _fixture(sess / "2026-04-18-demo-cccc-snapshot-120000.md", "claude-snapshot",
             "s3", "2026-04-18", body="Checkpoint one.")
    _fixture(sess / "2026-04-18-demo-cccc-snapshot-150000.md", "claude-snapshot",
             "s3", "2026-04-18", body="Checkpoint two.")
    out = build_context_brief(str(vault), "claude-sessions", "claude-insights", "demo")
    assert "<<<OB_LOAD_MANIFEST>>>" in out
    assert "snapshot_count: 2" in out
    assert "snapshot: [120000]" in out
    assert "snapshot: [150000]" in out


def test_fetch_snapshot_summaries_missing_trigger_defaults_to_auto(tmp_path):
    """Regression for Copilot PR #43 round 2 finding: snapshots without a
    `trigger:` frontmatter field must default to 'auto', not 'compact'.
    Mislabeling in the /recall UI would misattribute legacy snapshots.
    """
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    # Snapshot without a `trigger:` field
    (sess / "2026-04-18-demo-ccc-snapshot-120000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s3\n"
        "project: demo\nstatus: summarized\n"
        'source_session_note: "[[2026-04-18-demo-ccc]]"\n'
        "---\n\n# T\n\n## Summary\nno trigger set\n",
        encoding="utf-8",
    )
    items = fetch_snapshot_summaries(sess, "s3", "2026-04-18", "demo")
    assert len(items) == 1
    assert items[0]["trigger"] == "auto", (
        f"missing trigger should default to 'auto', got {items[0]['trigger']!r}"
    )


def test_build_context_brief_no_snapshot_artifacts_when_session_has_none(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    ins = vault / "claude-insights"
    sess.mkdir(parents=True); ins.mkdir()
    _fixture(sess / "2026-04-18-demo-dddd.md", "claude-session", "s4", "2026-04-18",
             extras="duration_minutes: 20\ngit_branch: develop\n", body="Standalone session.")
    out = build_context_brief(str(vault), "claude-sessions", "claude-insights", "demo")
    assert "snapshot_count" not in out
    assert "↳" not in out
