import json
from pathlib import Path
from unittest.mock import patch

from hooks.obsidian_utils import find_unsummarized_notes, upgrade_unsummarized_note, _augment_session_input_with_snapshots


def _fixture(sess_dir: Path, name: str, type_: str, status: str, session_id: str, body: str = ""):
    p = sess_dir / name
    p.write_text(
        f"---\ntype: {type_}\ndate: 2026-04-18\nsession_id: {session_id}\n"
        f"project: demo\nstatus: {status}\n---\n\n# {name}\n\n{body}",
        encoding="utf-8",
    )


def _fixture_no_type(sess_dir: Path, name: str, status: str, session_id: str):
    p = sess_dir / name
    p.write_text(
        f"---\ndate: 2026-04-18\nsession_id: {session_id}\n"
        f"project: demo\nstatus: {status}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_find_unsummarized_picks_up_snapshots(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    _fixture(sess, "2026-04-18-demo-aaaa-snapshot-140000.md", "claude-snapshot", "auto-logged", "s1")
    _fixture(sess, "2026-04-18-demo-aaaa.md", "claude-session", "auto-logged", "s1")

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    paths = result["unsummarized"]
    names = [Path(p).name for p in paths]
    assert any("snapshot-140000" in n for n in names)
    assert any(n == "2026-04-18-demo-aaaa.md" for n in names)


def test_find_unsummarized_skips_summarized_snapshots(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    _fixture(sess, "2026-04-18-demo-bbbb-snapshot-100000.md", "claude-snapshot", "summarized", "s2")

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    assert result["unsummarized"] == []


def test_find_unsummarized_orders_snapshots_before_parent(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    _fixture(sess, "2026-04-18-demo-cccc.md", "claude-session", "auto-logged", "s3")
    _fixture(sess, "2026-04-18-demo-cccc-snapshot-120000.md", "claude-snapshot", "auto-logged", "s3")
    _fixture(sess, "2026-04-18-demo-cccc-snapshot-090000.md", "claude-snapshot", "auto-logged", "s3")

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    names = [Path(p).name for p in result["unsummarized"]]
    # Snapshots before parent within the same session_id group
    assert names.index("2026-04-18-demo-cccc-snapshot-090000.md") < names.index("2026-04-18-demo-cccc.md")
    assert names.index("2026-04-18-demo-cccc-snapshot-120000.md") < names.index("2026-04-18-demo-cccc.md")


def test_find_unsummarized_rejects_non_session_non_snapshot_types(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    _fixture(sess, "2026-04-18-demo-dddd.md", "claude-session", "auto-logged", "s4")
    _fixture(sess, "2026-04-18-demo-dddd-insight.md", "claude-insight", "auto-logged", "s4")

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    names = [Path(p).name for p in result["unsummarized"]]
    assert "2026-04-18-demo-dddd.md" in names
    assert "2026-04-18-demo-dddd-insight.md" not in names


def test_find_unsummarized_keeps_legacy_notes_without_type_field(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    _fixture_no_type(sess, "2026-04-18-demo-eeee-legacy.md", "auto-logged", "s5")

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    names = [Path(p).name for p in result["unsummarized"]]
    assert "2026-04-18-demo-eeee-legacy.md" in names


def test_augment_defaults_missing_trigger_to_auto(tmp_path):
    """Regression for Copilot PR #43 round 2 finding: a snapshot without a
    `trigger:` frontmatter field emits `trigger=auto` in the augmented
    input, not `trigger=compact` — so the session summarizer isn't fed a
    misleading label.
    """
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    # No trigger field; summary is real so the block lands
    (sess / "2026-04-18-demo-zz-snapshot-140000.md").write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: sz\n"
        "project: demo\nstatus: summarized\n"
        'source_session_note: "[[2026-04-18-demo-zz]]"\n'
        "---\n\n# T\n\n## Summary\nreal summary body\n",
        encoding="utf-8",
    )
    out = _augment_session_input_with_snapshots(
        "transcript tail",
        sessions_folder_path=sess,
        session_id="sz",
        date="2026-04-18",
        project="demo",
    )
    assert "[snapshot 14:00:00, trigger=auto]" in out or \
           "[snapshot 140000, trigger=auto]" in out
    assert "trigger=compact" not in out


def test_find_unsummarized_orders_snapshot_before_parent_with_quoted_type(tmp_path):
    """Regression for Copilot PR #43 round 2 finding: `_bias_key` reads the
    `type:` frontmatter value without stripping quotes. A snapshot that uses
    valid YAML quoting (`type: "claude-snapshot"`) previously sorted AFTER
    its parent because the raw quoted string != 'claude-snapshot'.
    """
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    parent = sess / "2026-04-18-demo-qqqq.md"
    parent.write_text(
        '---\ntype: "claude-session"\ndate: 2026-04-18\nsession_id: sq\n'
        'project: demo\nstatus: auto-logged\n---\n\n# Parent\n',
        encoding="utf-8",
    )
    # Double-quoted and single-quoted snapshot type declarations
    snap_double = sess / "2026-04-18-demo-qqqq-snapshot-100000.md"
    snap_double.write_text(
        '---\ntype: "claude-snapshot"\ndate: 2026-04-18\nsession_id: sq\n'
        'project: demo\nstatus: auto-logged\n---\n\n# Snap DQ\n',
        encoding="utf-8",
    )
    snap_single = sess / "2026-04-18-demo-qqqq-snapshot-110000.md"
    snap_single.write_text(
        "---\ntype: 'claude-snapshot'\ndate: 2026-04-18\nsession_id: sq\n"
        "project: demo\nstatus: auto-logged\n---\n\n# Snap SQ\n",
        encoding="utf-8",
    )

    result = json.loads(find_unsummarized_notes(str(vault), "claude-sessions", "demo"))
    names = [Path(p).name for p in result["unsummarized"]]
    # Both snapshots must sort before the parent (quote-stripping lets the
    # type check see 'claude-snapshot' rather than '"claude-snapshot"').
    assert names.index(snap_double.name) < names.index(parent.name)
    assert names.index(snap_single.name) < names.index(parent.name)


def test_snapshot_routes_through_snapshot_prompt(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    snap_path = sess / "2026-04-18-demo-dddd-snapshot-140000.md"
    snap_path.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s4\n"
        "project: demo\ntrigger: compact\nstatus: auto-logged\n---\n\n"
        "# Context Snapshot: demo\n\n## What was happening\nWorking on X.\n\n"
        "## Last messages (raw)\n**User:** hi\n**Assistant:** hello\n",
        encoding="utf-8",
    )

    calls = []

    def fake_snapshot_summary(*args, **kwargs):
        calls.append(("snapshot", args, kwargs))
        return (
            "## Summary\nIn-flight work on X interrupted by /compact.\n\n"
            "## Key context that may be lost (summary)\n- Open decision: approach A vs B\n"
        )

    def fake_session_summary(*args, **kwargs):
        calls.append(("session", args, kwargs))
        return "## Summary\nshould-not-be-used\n"

    with patch("hooks.obsidian_utils.generate_snapshot_summary", fake_snapshot_summary), \
         patch("hooks.obsidian_utils.generate_summary", fake_session_summary):
        result = upgrade_unsummarized_note(str(snap_path), str(vault), "claude-sessions", "demo")

    assert not result.startswith("Failed"), result
    types_called = [c[0] for c in calls]
    assert types_called == ["snapshot"]
    # File now contains the snapshot-shaped summary
    assert "## Key context that may be lost (summary)" in snap_path.read_text(encoding="utf-8")


def test_session_routes_through_session_prompt(tmp_path):
    vault = tmp_path / "v"
    sess = vault / "claude-sessions"
    sess.mkdir(parents=True)
    sess_path = sess / "2026-04-18-demo-eeee.md"
    sess_path.write_text(
        "---\ntype: claude-session\ndate: 2026-04-18\nsession_id: s5\n"
        "project: demo\nstatus: auto-logged\n---\n\n"
        "# Session\n\n## Conversation (raw)\n"
        "**User:** hi\n**Assistant:** hello\n",
        encoding="utf-8",
    )

    calls = []

    def fake_snapshot_summary(*args, **kwargs):
        calls.append(("snapshot", args, kwargs))
        return "## Summary\nshould-not-be-used\n"

    def fake_session_summary(*args, **kwargs):
        calls.append(("session", args, kwargs))
        return (
            "## Summary\nSession work.\n\n## Key Decisions\n- None noted.\n\n"
            "## Changes Made\n- None noted.\n\n## Errors Encountered\n- None.\n\n"
            "## Open Questions / Next Steps\n- [ ] None.\n\n## Importance\n5\n"
        )

    with patch("hooks.obsidian_utils.generate_snapshot_summary", fake_snapshot_summary), \
         patch("hooks.obsidian_utils.generate_summary", fake_session_summary):
        result = upgrade_unsummarized_note(str(sess_path), str(vault), "claude-sessions", "demo")

    assert not result.startswith("Failed"), result
    types_called = [c[0] for c in calls]
    assert types_called == ["session"]


def test_augment_prepends_upgraded_snapshot_summaries(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    snap = sess / "2026-04-18-demo-eeee-snapshot-143000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s5\n"
        "project: demo\ntrigger: compact\nstatus: summarized\n---\n\n"
        "# Context Snapshot: demo\n\n"
        "## Summary\nMid-session decision on approach B.\n\n"
        "## Key context that may be lost (summary)\n- Open question about scalability.\n\n"
        "## Last messages (raw)\n**User:** earlier stuff\n",
        encoding="utf-8",
    )
    result = _augment_session_input_with_snapshots(
        transcript="current tail messages",
        sessions_folder_path=sess,
        session_id="s5",
        date="2026-04-18",
        project="demo",
    )
    assert "===== EARLIER IN THIS SESSION" in result
    assert "Mid-session decision on approach B." in result
    assert "current tail messages" in result
    # Summary section preferred over raw body
    assert "earlier stuff" not in result
    # Trigger annotation present
    assert "trigger=compact" in result


def test_augment_returns_transcript_unchanged_when_no_snapshots(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    result = _augment_session_input_with_snapshots(
        "original", sess, "no-matches", "2026-04-18", "demo",
    )
    assert result == "original"


def test_augment_falls_back_to_raw_when_snapshot_not_yet_upgraded(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    snap = sess / "2026-04-18-demo-ffff-snapshot-090000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s6\n"
        "project: demo\ntrigger: clear\nstatus: auto-logged\n---\n\n"
        "# Context Snapshot: demo\n\n## What was happening\nRaw work in progress.\n",
        encoding="utf-8",
    )
    result = _augment_session_input_with_snapshots(
        "tail", sess, "s6", "2026-04-18", "demo",
    )
    assert "Raw work in progress." in result


def test_augment_omits_current_tail_banner_when_transcript_empty(tmp_path):
    sess = tmp_path / "claude-sessions"
    sess.mkdir()
    snap = sess / "2026-04-18-demo-gggg-snapshot-110000.md"
    snap.write_text(
        "---\ntype: claude-snapshot\ndate: 2026-04-18\nsession_id: s7\n"
        "project: demo\ntrigger: compact\nstatus: summarized\n---\n\n"
        "## Summary\nSome mid-session work.\n",
        encoding="utf-8",
    )
    result = _augment_session_input_with_snapshots(
        "", sess, "s7", "2026-04-18", "demo",
    )
    assert "===== EARLIER IN THIS SESSION" in result
    assert "Some mid-session work." in result
    # No dangling tail banner when transcript is empty (preamble mode)
    assert "CURRENT TAIL" not in result
