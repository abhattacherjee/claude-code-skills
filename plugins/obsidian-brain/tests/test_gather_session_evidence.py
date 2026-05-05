"""Tests for obsidian_utils.gather_session_evidence().

Spec: docs/superpowers/specs/2026-05-03-issue-122-retro-evidence-base-design.md
Issue: https://github.com/abhattacherjee/obsidian-brain/issues/122
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

import obsidian_utils


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def test_gather_session_evidence_unknown_sid_returns_empty(tmp_vault: Path) -> None:
    """session_id == 'unknown' must return all-empty lists with no I/O attempted."""
    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="unknown",
        project="obsidian-brain",
    )
    assert bundle["session_id"] == "unknown"
    assert bundle["snapshots"] == []
    assert bundle["insights"] == []
    assert bundle["decisions"] == []
    assert bundle["error_fixes"] == []
    assert bundle["discovery_errors"] == []


SNAPSHOT_TEMPLATE = """\
---
type: claude-snapshot
session_id: {sid}
project: {project}
date: 2026-05-03
trigger: {trigger}
---

# Context Snapshot: {project}

## Summary
Snapshot body for testing — hhmmss {hhmmss}.
"""


def _make_snapshot(
    sessions_dir: Path,
    *,
    sid: str,
    project: str = "obsidian-brain",
    hhmmss: str = "100000",
    trigger: str = "auto",
    project_slug: str | None = None,
) -> Path:
    slug = project_slug or project
    path = sessions_dir / f"2026-05-03-{slug}-aaaa-snapshot-{hhmmss}.md"
    _write(path, SNAPSHOT_TEMPLATE.format(sid=sid, project=project, hhmmss=hhmmss, trigger=trigger))
    return path


def test_gather_session_evidence_snapshots_happy_path(tmp_vault: Path) -> None:
    sessions_dir = tmp_vault / "claude-sessions"
    snap_a = _make_snapshot(sessions_dir, sid="SID-A", hhmmss="100000")
    snap_b = _make_snapshot(sessions_dir, sid="SID-A", hhmmss="200000")

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    paths = [s["path"] for s in bundle["snapshots"]]
    assert paths == [str(snap_a), str(snap_b)]
    assert bundle["snapshots"][0]["hhmmss"] == "100000"
    assert bundle["snapshots"][0]["trigger"] == "auto"
    assert "Snapshot body for testing" in bundle["snapshots"][0]["body"]
    assert bundle["discovery_errors"] == []


def test_gather_session_evidence_snapshots_sorted_ascending_by_hhmmss(tmp_vault: Path) -> None:
    """Even if the filesystem returns snapshots in reverse order, helper sorts ascending."""
    sessions_dir = tmp_vault / "claude-sessions"
    _make_snapshot(sessions_dir, sid="SID-A", hhmmss="200000")
    _make_snapshot(sessions_dir, sid="SID-A", hhmmss="100000")

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    hhmmss_seq = [s["hhmmss"] for s in bundle["snapshots"]]
    assert hhmmss_seq == ["100000", "200000"]


def test_gather_session_evidence_snapshots_filter_other_project(tmp_vault: Path) -> None:
    """Snapshots whose frontmatter project differs are excluded."""
    sessions_dir = tmp_vault / "claude-sessions"
    own = _make_snapshot(sessions_dir, sid="SID-A", hhmmss="100000", project="obsidian-brain")
    _make_snapshot(
        sessions_dir,
        sid="SID-A",
        hhmmss="200000",
        project="other-project",
        project_slug="other-project",
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    paths = [s["path"] for s in bundle["snapshots"]]
    assert paths == [str(own)]


INSIGHT_TEMPLATE = """\
---
type: {note_type}
source_session: {sid}
project: obsidian-brain
date: 2026-05-03
---

# {title}

{body}
"""


def _make_insight(
    insights_dir: Path,
    *,
    filename: str,
    note_type: str,
    sid: str,
    title: str = "Test Title",
    body: str = "Test body content.",
) -> Path:
    path = insights_dir / filename
    _write(path, INSIGHT_TEMPLATE.format(note_type=note_type, sid=sid, title=title, body=body))
    return path


def test_gather_session_evidence_partitions_by_type(tmp_vault: Path) -> None:
    insights_dir = tmp_vault / "claude-insights"
    ins = _make_insight(
        insights_dir,
        filename="2026-05-03-finding-aaaa.md",
        note_type="claude-insight",
        sid="SID-A",
        title="An insight",
    )
    dec = _make_insight(
        insights_dir,
        filename="2026-05-03-decision-bbbb-decision.md",
        note_type="claude-decision",
        sid="SID-A",
        title="A decision",
    )
    err = _make_insight(
        insights_dir,
        filename="2026-05-03-bug-cccc-error-fix.md",
        note_type="claude-error-fix",
        sid="SID-A",
        title="An error fix",
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    assert [i["path"] for i in bundle["insights"]] == [str(ins)]
    assert [d["path"] for d in bundle["decisions"]] == [str(dec)]
    assert [e["path"] for e in bundle["error_fixes"]] == [str(err)]
    assert bundle["insights"][0]["title"] == "An insight"
    assert "Test body content." in bundle["insights"][0]["body"]


def test_gather_session_evidence_filters_decoys(tmp_vault: Path) -> None:
    """Notes belonging to other sessions or types must not leak into the bundle."""
    insights_dir = tmp_vault / "claude-insights"
    own = _make_insight(
        insights_dir,
        filename="2026-05-03-mine-aaaa.md",
        note_type="claude-insight",
        sid="SID-A",
    )
    _make_insight(  # other session — must be excluded
        insights_dir,
        filename="2026-05-03-theirs-bbbb.md",
        note_type="claude-insight",
        sid="SID-B",
    )
    _make_insight(  # ignored type (e.g. retro from prior session) — must be excluded
        insights_dir,
        filename="2026-05-03-old-retro-cccc.md",
        note_type="claude-retro",
        sid="SID-A",
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    assert [i["path"] for i in bundle["insights"]] == [str(own)]
    assert bundle["decisions"] == []
    assert bundle["error_fixes"] == []


def test_gather_session_evidence_unreadable_file_in_discovery_errors(
    tmp_vault: Path,
) -> None:
    """A file we can't read appears in discovery_errors but doesn't break the bundle."""
    insights_dir = tmp_vault / "claude-insights"
    good = _make_insight(
        insights_dir,
        filename="2026-05-03-good-aaaa.md",
        note_type="claude-insight",
        sid="SID-A",
    )
    bad = _make_insight(
        insights_dir,
        filename="2026-05-03-bad-bbbb.md",
        note_type="claude-insight",
        sid="SID-A",
    )

    # Make the body read fail by chmod'ing the file unreadable. The frontmatter
    # read in read_note_metadata() will also fail, which routes through the
    # OSError branch in the discovery loop. We use 0o000 rather than removing
    # the file so the glob still finds it.
    if os.geteuid() == 0:
        pytest.skip("chmod-based unreadable test does not work for root")
    os.chmod(bad, 0o000)
    try:
        bundle = obsidian_utils.gather_session_evidence(
            vault_path=str(tmp_vault),
            sessions_folder="claude-sessions",
            insights_folder="claude-insights",
            session_id="SID-A",
            project="obsidian-brain",
        )
    finally:
        os.chmod(bad, 0o600)  # restore so pytest tmp_path teardown can delete

    assert [i["path"] for i in bundle["insights"]] == [str(good)]
    assert any("bad-bbbb" in err for err in bundle["discovery_errors"])


def test_gather_session_evidence_empty_when_no_matches(tmp_vault: Path) -> None:
    """Vault dirs exist but contain no notes matching the session — clean empty bundle."""
    # Populate with a note belonging to a different session
    insights_dir = tmp_vault / "claude-insights"
    _make_insight(
        insights_dir,
        filename="2026-05-03-other-aaaa.md",
        note_type="claude-insight",
        sid="SID-OTHER",
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-Z",
        project="obsidian-brain",
    )

    assert bundle["session_id"] == "SID-Z"
    assert bundle["snapshots"] == []
    assert bundle["insights"] == []
    assert bundle["decisions"] == []
    assert bundle["error_fixes"] == []
    assert bundle["discovery_errors"] == []


def test_gather_session_evidence_missing_folders_no_crash(tmp_path: Path) -> None:
    """Missing sessions or insights folder must not crash — just return empty lists."""
    # Case A: only claude-insights exists, sessions folder absent
    only_insights = tmp_path / "case-a"
    only_insights.mkdir()
    (only_insights / "claude-insights").mkdir()

    bundle_a = obsidian_utils.gather_session_evidence(
        vault_path=str(only_insights),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )
    assert bundle_a["snapshots"] == []
    assert bundle_a["discovery_errors"] == []

    # Case B: only claude-sessions exists, insights folder absent
    only_sessions = tmp_path / "case-b"
    only_sessions.mkdir()
    (only_sessions / "claude-sessions").mkdir()

    bundle_b = obsidian_utils.gather_session_evidence(
        vault_path=str(only_sessions),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )
    assert bundle_b["insights"] == []
    assert bundle_b["decisions"] == []
    assert bundle_b["error_fixes"] == []
    assert bundle_b["discovery_errors"] == []


def test_gather_session_evidence_unknown_type_isolated(tmp_vault: Path) -> None:
    """A note in insights_folder with wrong type (e.g. claude-snapshot) is silently skipped."""
    insights_dir = tmp_vault / "claude-insights"
    _make_insight(
        insights_dir,
        filename="2026-05-03-misrouted-aaaa.md",
        note_type="claude-snapshot",  # wrong type for insights folder
        sid="SID-A",
        title="Misrouted Snapshot",
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    assert bundle["insights"] == []
    assert bundle["decisions"] == []
    assert bundle["error_fixes"] == []
    assert bundle["discovery_errors"] == []


# ---------------------------------------------------------------------------
# Test 11 — cross-midnight snapshot discovery
# ---------------------------------------------------------------------------

_SNAPSHOT_TEMPLATE_DATED = """\
---
type: claude-snapshot
session_id: {sid}
project: {project}
date: {date}
trigger: auto
---

# Context Snapshot: {project}

## Summary
Snapshot body for cross-midnight test — hhmmss {hhmmss}.
"""


def _make_snapshot_dated(
    sessions_dir: Path,
    *,
    sid: str,
    date: str,
    hhmmss: str,
    project: str = "obsidian-brain",
) -> Path:
    """Like _make_snapshot but allows arbitrary date prefix in the filename."""
    slug = project
    path = sessions_dir / f"{date}-{slug}-aaaa-snapshot-{hhmmss}.md"
    _write(
        path,
        _SNAPSHOT_TEMPLATE_DATED.format(
            sid=sid, project=project, date=date, hhmmss=hhmmss
        ),
    )
    return path


def test_gather_session_evidence_cross_midnight_snapshots(tmp_vault: Path) -> None:
    """Cross-midnight sessions: snapshots on two YYYY-MM-DD prefixes are both found.

    gather_session_evidence passes date=None to find_snapshots_for_session so
    discovery is date-agnostic; frontmatter matching excludes decoys.
    Regression for Copilot R2 fix #122.
    """
    sessions_dir = tmp_vault / "claude-sessions"
    # Snapshot written at 23:50 on day N (the earlier date)
    snap_day_n = _make_snapshot_dated(
        sessions_dir, sid="SID-X", date="2026-05-03", hhmmss="235000"
    )
    # Snapshot written at 00:10 on day N+1 (after midnight, same session)
    snap_day_n1 = _make_snapshot_dated(
        sessions_dir, sid="SID-X", date="2026-05-04", hhmmss="001000"
    )

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-X",
        project="obsidian-brain",
    )

    assert len(bundle["snapshots"]) == 2, (
        "Both cross-midnight snapshots must appear; date-agnostic discovery expected"
    )
    # Sorted by stem (YYYY-MM-DD-...): "2026-05-03-..." < "2026-05-04-..."
    # so day N (235000) sorts before day N+1 (001000) — chronologically correct.
    hhmmss_seq = [s["hhmmss"] for s in bundle["snapshots"]]
    assert hhmmss_seq == ["235000", "001000"]
    assert bundle["discovery_errors"] == []


# ---------------------------------------------------------------------------
# Test 12 — pre-spec snapshot sorts first
# ---------------------------------------------------------------------------


def test_gather_session_evidence_pre_spec_snapshot_sorts_first(tmp_vault: Path) -> None:
    """Pre-spec snapshots (no -HHMMSS suffix, hhmmss='??????') must sort before
    post-spec ones per find_snapshots_for_session docstring contract.

    The composite sort key `(0 if '??????' else 1, hhmmss)` enforces this.
    Regression for Copilot R2 fix #122.
    """
    sessions_dir = tmp_vault / "claude-sessions"
    # Pre-spec snapshot — filename has no -HHMMSS suffix
    legacy = sessions_dir / "2026-05-03-obsidian-brain-aaaa-snapshot.md"
    _write(
        legacy,
        """\
        ---
        type: claude-snapshot
        session_id: SID-A
        project: obsidian-brain
        date: 2026-05-03
        trigger: auto
        ---

        # Snapshot

        ## Summary
        Pre-spec snapshot body.
        """,
    )
    # Modern post-spec snapshot — has -HHMMSS suffix
    _make_snapshot(sessions_dir, sid="SID-A", hhmmss="100000")

    bundle = obsidian_utils.gather_session_evidence(
        vault_path=str(tmp_vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        session_id="SID-A",
        project="obsidian-brain",
    )

    assert len(bundle["snapshots"]) == 2
    hhmmss_seq = [s["hhmmss"] for s in bundle["snapshots"]]
    assert hhmmss_seq == ["??????", "100000"], (
        "Pre-spec snapshot ('??????') must sort before post-spec ones"
    )
