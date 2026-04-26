"""Tests for the source_sessions vault_doctor check module."""

import calendar
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import vault_doctor_checks.source_sessions as ss  # noqa: E402 (must follow sys.path setup)


@pytest.fixture
def doctor_vault(tmp_path):
    """Tmp vault layout with folders + JSONL home for session matching."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-insights").mkdir(parents=True)
    (vault / "claude-decisions").mkdir(parents=True)
    (vault / "claude-error-fixes").mkdir(parents=True)
    (vault / "claude-retros").mkdir(parents=True)
    claude_home = tmp_path / ".claude" / "projects" / "-Users-foo-proj1"
    claude_home.mkdir(parents=True)
    return {
        "vault": vault,
        "home": tmp_path,
        "jsonl_dir": claude_home,
        "project": "proj1",
    }


def _write_jsonl(path: Path, first_ts: str, last_ts_mtime: float) -> None:
    """Write a minimal JSONL with two entries and set mtime to last_ts_mtime."""
    payload = [
        {"type": "user", "timestamp": first_ts},
        {"type": "assistant", "timestamp": first_ts},
    ]
    path.write_text("\n".join(json.dumps(p) for p in payload) + "\n", encoding="utf-8")
    os.utime(path, (last_ts_mtime, last_ts_mtime))


def _write_session_note(dir_path: Path, date: str, project: str, sid: str, hash_: str) -> Path:
    note = dir_path / f"{date}-{project}-{hash_}.md"
    note.write_text(
        f"---\n"
        f"type: claude-session\n"
        f"date: {date}\n"
        f"session_id: {sid}\n"
        f"project: {project}\n"
        f"status: summarized\n"
        f"---\n"
        f"# Session\n## Summary\nstub\n",
        encoding="utf-8",
    )
    return note


def _write_insight(dir_path: Path, date: str, slug: str, project: str, src_sid: str,
                   src_note_basename: str, mtime: float) -> Path:
    note = dir_path / f"{date}-{slug}.md"
    note.write_text(
        f"---\n"
        f"type: claude-insight\n"
        f"date: {date}\n"
        f"source_session: {src_sid}\n"
        f'source_session_note: "[[{src_note_basename}]]"\n'
        f"project: {project}\n"
        f"tags:\n"
        f"  - claude/insight\n"
        f"  - claude/project/{project}\n"
        f"---\n"
        f"# Test insight\n",
        encoding="utf-8",
    )
    os.utime(note, (mtime, mtime))
    return note


def test_scan_flags_insight_stamped_to_wrong_session(doctor_vault, monkeypatch):
    """Insight mtime falls in session-B window but references session-A → stale."""
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    # Session A: 2026-04-09 10:00–11:00
    a_start = calendar.timegm(time.strptime("2026-04-09 10:00", "%Y-%m-%d %H:%M"))
    a_end = a_start + 3600
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-09T10:00:00Z", a_end)
    _write_session_note(v / "claude-sessions", "2026-04-09", "proj1", "sid-a", "aaaa")

    # Session B: 2026-04-10 10:00–14:00 (window must contain midday for the
    # date-based capture_time match under the fix for issue #93)
    b_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    b_end = b_start + 4 * 3600
    _write_jsonl(jsonl_dir / "sid-b.jsonl", "2026-04-10T10:00:00Z", b_end)
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-b", "bbbb")

    # Insight captured 2026-04-10 10:30 but wrongly stamped with sid-a
    insight_mtime = b_start + 1800
    _write_insight(
        v / "claude-insights",
        "2026-04-10",
        "stale-insight-0001",
        "proj1",
        "sid-a",
        "2026-04-09-proj1-aaaa",
        insight_mtime,
    )

    issues = check.scan(
        str(v), "claude-sessions", "claude-insights", days=60, project="proj1"
    )
    assert len(issues) == 1
    iss = issues[0]
    assert "stale-insight-0001" in iss.note_path
    assert iss.current_source == "[[2026-04-09-proj1-aaaa]]"
    assert iss.proposed_source == "[[2026-04-10-proj1-bbbb]]"
    assert iss.project == "proj1"
    assert iss.extra.get("proposed_sid") == "sid-b"


def test_scan_ignores_correct_insight(doctor_vault, monkeypatch):
    """Insight mtime matches its referenced session window → not flagged."""
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    a_start = calendar.timegm(time.strptime("2026-04-10 14:00", "%Y-%m-%d %H:%M"))
    a_end = a_start + 3600
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-10T14:00:00Z", a_end)
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-a", "aaaa")

    _write_insight(
        v / "claude-insights",
        "2026-04-10",
        "good-insight",
        "proj1",
        "sid-a",
        "2026-04-10-proj1-aaaa",
        a_start + 1800,
    )

    issues = check.scan(str(v), "claude-sessions", "claude-insights", days=60, project="proj1")
    assert issues == []


def test_scan_honors_days_window(doctor_vault, monkeypatch):
    """Notes older than `days` are not scanned."""
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    old_ts = time.time() - 30 * 86400
    _write_jsonl(jsonl_dir / "sid-old.jsonl", "2026-03-12T10:00:00Z", old_ts + 3600)
    _write_session_note(v / "claude-sessions", "2026-03-12", "proj1", "sid-old", "0aaa")
    _write_insight(
        v / "claude-insights",
        "2026-03-12",
        "ancient-insight",
        "proj1",
        "wrong-sid",
        "2026-03-12-proj1-0aaa",
        old_ts + 1800,
    )

    issues = check.scan(str(v), "claude-sessions", "claude-insights", days=7, project="proj1")
    assert issues == []  # outside 7-day window — this test specifically validates that boundary


def test_scan_marks_unresolved_when_no_window_matches(doctor_vault, monkeypatch):
    """Insight whose date has no overlapping session window → UNRESOLVED.

    Under day-overlap matching, the matcher finds any session whose JSONL
    window touches the note's calendar day. To produce an unresolved case we
    need the only session to be on a *different* calendar day so no overlap
    exists at all.
    """
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    # Session on 2026-04-09 only — no session on 2026-04-10
    a_start = calendar.timegm(time.strptime("2026-04-09 10:00", "%Y-%m-%d %H:%M"))
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-09T10:00:00Z", a_start + 3600)
    _write_session_note(v / "claude-sessions", "2026-04-09", "proj1", "sid-a", "aaaa")

    # Insight dated 2026-04-10 — day-overlap finds no session whose window
    # touches 2026-04-10, so the result is unresolved.
    gap_mtime = calendar.timegm(time.strptime("2026-04-10 20:00", "%Y-%m-%d %H:%M"))
    _write_insight(
        v / "claude-insights",
        "2026-04-10",
        "gap-insight",
        "proj1",
        "wrong-sid",  # doesn't match any session
        "2026-04-10-proj1-wrong",
        gap_mtime,
    )

    issues = check.scan(str(v), "claude-sessions", "claude-insights", days=60, project="proj1")
    assert len(issues) == 1, f"expected exactly 1 unresolved issue, got {len(issues)}"
    iss = issues[0]
    assert iss.extra.get("unresolved") is True
    assert iss.confidence == 0.0
    assert iss.proposed_source == ""
    assert "gap-insight" in iss.note_path


def test_apply_rewrites_only_source_session_fields(doctor_vault, tmp_path, monkeypatch):
    """After apply, only source_session/source_session_note change; body+tags preserved."""
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    a_start = calendar.timegm(time.strptime("2026-04-09 10:00", "%Y-%m-%d %H:%M"))
    # Session B widened to include 2026-04-10 midday (12:00) so the new
    # date-based capture_time matches it. (issue #93)
    b_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-09T10:00:00Z", a_start + 3600)
    _write_jsonl(jsonl_dir / "sid-b.jsonl", "2026-04-10T10:00:00Z", b_start + 4 * 3600)
    _write_session_note(v / "claude-sessions", "2026-04-09", "proj1", "sid-a", "aaaa")
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-b", "bbbb")

    # Build an insight with extra tags and body content we want preserved
    note = v / "claude-insights" / "2026-04-10-rewrite-me.md"
    note.write_text(
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-10\n"
        "source_session: sid-a\n"
        'source_session_note: "[[2026-04-09-proj1-aaaa]]"\n'
        "project: proj1\n"
        "tags:\n"
        "  - claude/insight\n"
        "  - claude/project/proj1\n"
        "  - claude/topic/foo\n"
        "---\n"
        "\n"
        "# My insight\n"
        "\n"
        "Body line 1\n"
        "Body line 2 with [[2026-04-09-proj1-aaaa]] reference in body\n",
        encoding="utf-8",
    )
    os.utime(note, (b_start + 1800, b_start + 1800))

    # Capture the original body for byte-identity comparison
    original_text = note.read_text(encoding="utf-8")
    original_body = original_text.split("---\n", 2)[-1]

    issues = check.scan(
        str(v), "claude-sessions", "claude-insights", days=60, project="proj1"
    )
    assert len(issues) == 1, f"expected 1 issue, got {len(issues)}"

    backup_root = tmp_path / "backups"
    results = check.apply(issues, str(backup_root))

    assert len(results) == 1
    assert results[0].status == "applied"
    assert results[0].backup_path is not None
    assert Path(results[0].backup_path).exists()

    patched = note.read_text(encoding="utf-8")
    # Frontmatter targets rewritten
    assert "source_session: sid-b" in patched
    assert 'source_session_note: "[[2026-04-10-proj1-bbbb]]"' in patched
    # Untouched frontmatter preserved
    assert "claude/topic/foo" in patched
    assert "type: claude-insight" in patched
    assert "tags:\n  - claude/insight" in patched
    # Body byte-identical
    patched_body = patched.split("---\n", 2)[-1]
    assert patched_body == original_body, "body must be byte-identical after frontmatter rewrite"
    # Backup file matches the pre-patch content
    assert Path(results[0].backup_path).read_text(encoding="utf-8") == original_text


def test_apply_skips_unresolved(doctor_vault, tmp_path):
    """Issues marked unresolved are skipped, never rewritten."""
    import vault_doctor_checks.source_sessions as check
    from vault_doctor_checks import Issue

    v = doctor_vault["vault"]
    note = v / "claude-insights" / "2026-04-10-unresolved.md"
    original = (
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-10\n"
        "source_session: gone-sid\n"
        'source_session_note: "[[does-not-exist]]"\n'
        "project: proj1\n"
        "---\n"
        "# unresolved\n"
    )
    note.write_text(original, encoding="utf-8")

    issue = Issue(
        check="source-sessions",
        note_path=str(note),
        project="proj1",
        current_source="[[does-not-exist]]",
        proposed_source="",
        reason="no window",
        confidence=0.0,
        extra={"unresolved": True},
    )

    backup_root = tmp_path / "backups"
    results = check.apply([issue], str(backup_root))
    assert len(results) == 1
    assert results[0].status == "unresolved"
    assert results[0].backup_path is None
    # File must be byte-identical
    assert note.read_text(encoding="utf-8") == original


def test_apply_errors_on_missing_proposed_sid(doctor_vault, tmp_path):
    """Issue with no proposed_sid returns status=error, file untouched."""
    import vault_doctor_checks.source_sessions as check
    from vault_doctor_checks import Issue

    v = doctor_vault["vault"]
    note = v / "claude-insights" / "2026-04-10-noprop.md"
    original = "---\ntype: claude-insight\nproject: proj1\nsource_session: x\n---\n# x\n"
    note.write_text(original, encoding="utf-8")

    issue = Issue(
        check="source-sessions",
        note_path=str(note),
        project="proj1",
        current_source="[[foo]]",
        proposed_source="[[bar]]",  # proposed basename exists but extra['proposed_sid'] is missing
        reason="test",
        confidence=0.95,
        extra={},  # no proposed_sid
    )

    backup_root = tmp_path / "backups"
    results = check.apply([issue], str(backup_root))
    assert results[0].status == "error"
    assert "proposed_sid" in (results[0].error or "")
    assert note.read_text(encoding="utf-8") == original


def test_parse_date_midpoint_valid_date_returns_noon_utc():
    ts = ss._parse_date_midpoint("2026-04-21")
    assert ts is not None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (
        2026, 4, 21, 12, 0, 0,
    )


def test_parse_date_midpoint_empty_returns_none():
    assert ss._parse_date_midpoint("") is None


def test_parse_date_midpoint_malformed_returns_none():
    assert ss._parse_date_midpoint("not-a-date") is None
    assert ss._parse_date_midpoint("2026-13-99") is None


@pytest.mark.parametrize(
    "bad_date",
    [
        "2025-02-29",  # not a leap year
        "2026-13-01",  # invalid month
        "2026-04-31",  # April has 30 days
        "",            # empty
        "not-a-date",  # garbage
        "2026/04/21",  # wrong separator
        "20260421",    # no separators
    ],
)
def test_parse_date_midpoint_negative_edges_return_none(bad_date):
    """T5: invalid date strings must return None so capture-time signal
    falls back to the next preference rather than fabricating a timestamp."""
    assert ss._parse_date_midpoint(bad_date) is None


def test_scan_latest_start_wins_on_boundary_tie(doctor_vault, monkeypatch):
    """When two session windows both contain capture_time, latest first_ts wins."""
    import vault_doctor_checks.source_sessions as check

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    # Session A: 10:00 - 14:05 (mtime)
    a_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    a_mtime = calendar.timegm(time.strptime("2026-04-10 14:05", "%Y-%m-%d %H:%M"))
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-10T10:00:00Z", a_mtime)
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-a", "aaaa")

    # Session B: 14:00 - 15:00 (mtime) — overlaps session A from 14:00-14:05
    b_start = calendar.timegm(time.strptime("2026-04-10 14:00", "%Y-%m-%d %H:%M"))
    b_mtime = b_start + 3600
    _write_jsonl(jsonl_dir / "sid-b.jsonl", "2026-04-10T14:00:00Z", b_mtime)
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-b", "bbbb")

    # Insight captured at 14:02 — inside BOTH windows.
    # We inject created_at so _capture_time uses the precise sub-day timestamp
    # (date: midday = 12:00, which only falls in A; we need 14:02 in both).
    insight_mtime = calendar.timegm(time.strptime("2026-04-10 14:02", "%Y-%m-%d %H:%M"))
    insight_path = _write_insight(
        v / "claude-insights",
        "2026-04-10",
        "boundary-tie-insight",
        "proj1",
        "sid-a",  # currently (wrongly) stamped with the older session
        "2026-04-10-proj1-aaaa",
        insight_mtime,
    )
    # Inject created_at so _capture_time resolves to 14:02 (inside both windows)
    # rather than midday-12:00 (which only falls in session A). (issue #93)
    text = insight_path.read_text(encoding="utf-8")
    text = text.replace("type: claude-insight\n",
                        "type: claude-insight\ncreated_at: 2026-04-10T14:02:00Z\n")
    insight_path.write_text(text, encoding="utf-8")
    os.utime(insight_path, (insight_mtime, insight_mtime))  # restore mtime after write

    issues = check.scan(
        str(v), "claude-sessions", "claude-insights", days=60, project="proj1"
    )
    assert len(issues) == 1
    # Latest first_ts wins: sid-b (started at 14:00) beats sid-a (started at 10:00)
    assert issues[0].extra.get("proposed_sid") == "sid-b"
    assert issues[0].proposed_source == "[[2026-04-10-proj1-bbbb]]"


def test_jsonl_window_returns_none_when_all_lines_unparseable(tmp_path):
    """Fully corrupt JSONL returns None, not a fabricated window."""
    import vault_doctor_checks.source_sessions as check

    bad = tmp_path / "corrupt.jsonl"
    bad.write_text("this is not json\nthis either\n", encoding="utf-8")
    assert check._jsonl_window(str(bad)) is None


def test_jsonl_window_falls_back_when_parsed_but_no_timestamps(tmp_path):
    """JSONL with valid JSON but no timestamp field → mtime-3600 fallback."""
    import vault_doctor_checks.source_sessions as check
    import json
    import os

    jsonl = tmp_path / "no-ts.jsonl"
    jsonl.write_text(
        json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "assistant"}) + "\n",
        encoding="utf-8",
    )
    mtime = 1700000000.0
    os.utime(jsonl, (mtime, mtime))
    window = check._jsonl_window(str(jsonl))
    assert window is not None
    first_ts, last_ts = window
    assert last_ts == mtime
    assert first_ts == mtime - 3600


def test_jsonl_dir_for_project_picks_newest_worktree(tmp_path, monkeypatch):
    """Two .claude/projects/*proj1 dirs exist (path encoding variants) → newest-mtime wins."""
    import vault_doctor_checks.source_sessions as check
    import os
    import time as _time

    # Both dirs end with "proj1" so the `*proj1` glob matches both. Simulates
    # two encoded path variants for the same project name (e.g. after a user
    # moved the checkout between machines or worktrees).
    older = tmp_path / ".claude" / "projects" / "-Users-foo-proj1"
    newer = tmp_path / ".claude" / "projects" / "-Users-bar-worktrees-proj1"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    os.utime(older, (_time.time() - 3600, _time.time() - 3600))
    os.utime(newer, (_time.time() - 60, _time.time() - 60))

    monkeypatch.setenv("HOME", str(tmp_path))
    result = check._jsonl_dir_for_project("proj1")
    assert result is not None
    assert str(result).endswith("-Users-bar-worktrees-proj1"), (
        f"expected newer dir, got {result}"
    )


def test_apply_preserves_note_mtime(doctor_vault, tmp_path, monkeypatch):
    """After apply, the patched note's mtime equals its pre-apply mtime.

    scan() uses mtime for the --days cutoff filter. If apply updated mtime
    to 'now', notes written long ago could accidentally re-enter the scan
    window after being fixed. Preserving mtime prevents that drift.
    """
    import vault_doctor_checks.source_sessions as check
    import os

    v = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    monkeypatch.setenv("HOME", str(home))

    import calendar, time
    a_start = calendar.timegm(time.strptime("2026-04-09 10:00", "%Y-%m-%d %H:%M"))
    # Session B widened to include 2026-04-10 midday (12:00) so the new
    # date-based capture_time matches it. (issue #93)
    b_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-09T10:00:00Z", a_start + 3600)
    _write_jsonl(jsonl_dir / "sid-b.jsonl", "2026-04-10T10:00:00Z", b_start + 4 * 3600)
    _write_session_note(v / "claude-sessions", "2026-04-09", "proj1", "sid-a", "aaaa")
    _write_session_note(v / "claude-sessions", "2026-04-10", "proj1", "sid-b", "bbbb")

    original_mtime = b_start + 1800  # 2026-04-10 10:30
    _write_insight(
        v / "claude-insights",
        "2026-04-10",
        "mtime-preserve",
        "proj1",
        "sid-a",
        "2026-04-09-proj1-aaaa",
        original_mtime,
    )

    issues = check.scan(
        str(v), "claude-sessions", "claude-insights", days=60, project="proj1"
    )
    assert len(issues) == 1

    backup_root = tmp_path / "backups"
    results = check.apply(issues, str(backup_root))
    assert results[0].status == "applied"

    # Critical: mtime must be preserved
    note_path = issues[0].note_path
    new_mtime = os.path.getmtime(note_path)
    assert abs(new_mtime - original_mtime) < 1.0, (
        f"mtime not preserved: original={original_mtime}, new={new_mtime}"
    )

    # And a re-scan with the patched note should find nothing (proves the
    # self-reinforcing bug is not reintroduced)
    rescan_issues = check.scan(
        str(v), "claude-sessions", "claude-insights", days=60, project="proj1"
    )
    assert rescan_issues == [], f"re-scan should be clean, got: {rescan_issues}"


def test_jsonl_dir_for_project_deterministic_same_mtime_tiebreak(tmp_path, monkeypatch):
    """Two dirs with identical mtimes: winner is deterministic across runs."""
    import vault_doctor_checks.source_sessions as check
    import os

    dir_a = tmp_path / ".claude" / "projects" / "-aaa-proj1"
    dir_b = tmp_path / ".claude" / "projects" / "-bbb-proj1"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    now = 1700000000.0
    os.utime(dir_a, (now, now))
    os.utime(dir_b, (now, now))

    monkeypatch.setenv("HOME", str(tmp_path))

    # Both runs should return the same winner
    result1 = check._jsonl_dir_for_project("proj1")
    result2 = check._jsonl_dir_for_project("proj1")
    assert result1 is not None
    assert result1 == result2, f"non-deterministic: {result1} vs {result2}"


def test_jsonl_dir_for_project_underscore_to_hyphen_fallback(tmp_path, monkeypatch):
    """Project with underscores matches CC dir with hyphens."""
    import vault_doctor_checks.source_sessions as check

    cc_dir = tmp_path / ".claude" / "projects" / "-Users-foo-my-project"
    cc_dir.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(tmp_path))
    result = check._jsonl_dir_for_project("my_project")
    assert result is not None, "Expected hyphen fallback to match"
    assert str(result).endswith("-Users-foo-my-project")


def test_list_session_notes_matches_across_underscore_hyphen(tmp_path):
    """_list_session_notes matches session notes regardless of _ vs - in project name."""
    import vault_doctor_checks.source_sessions as check

    sessions_dir = tmp_path / "claude-sessions"
    sessions_dir.mkdir()
    # Session note has project: personal-ws (hyphen)
    note = sessions_dir / "2026-04-13-test-session.md"
    note.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-13\n"
        "project: personal-ws\n"
        "session_id: abc123\n"
        "---\n\n# Test\n",
        encoding="utf-8",
    )

    # Query with underscore variant — should still match
    result = check._list_session_notes(sessions_dir, "personal_ws")
    assert "abc123" in result, (
        f"Expected session note to match despite _ vs - difference, got keys: {list(result.keys())}"
    )


def test_apply_rejects_path_traversal_in_project_name(doctor_vault, tmp_path):
    """An issue with a malicious project name cannot write outside backup_root."""
    import vault_doctor_checks.source_sessions as check
    from vault_doctor_checks import Issue

    v = doctor_vault["vault"]
    note = v / "claude-insights" / "2026-04-10-malicious.md"
    note.write_text(
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-10\n"
        "source_session: sid-a\n"
        'source_session_note: "[[old]]"\n'
        "project: ../../../etc\n"
        "---\n"
        "# x\n",
        encoding="utf-8",
    )

    issue = Issue(
        check="source-sessions",
        note_path=str(note),
        project="../../../etc",  # malicious
        current_source="[[old]]",
        proposed_source="[[new]]",
        reason="test",
        confidence=0.95,
        extra={"proposed_sid": "sid-b"},
    )

    backup_root = tmp_path / "backups"
    results = check.apply([issue], str(backup_root))

    # Backup must go under a sanitized slug inside backup_root, never outside
    assert len(results) == 1
    if results[0].status == "applied":
        # If it succeeded, the backup path must still be under backup_root
        bp = Path(results[0].backup_path).resolve()
        br = Path(backup_root).resolve()
        assert br in bp.parents, (
            f"backup escaped root: {bp} not under {br}"
        )
    elif results[0].status == "error":
        # Acceptable — sanitizer or defensive check rejected it.
        pass
    else:
        assert False, f"unexpected status: {results[0].status}"


def test_safe_project_slug_sanitizes_dots_and_separators():
    """_safe_project_slug strips path-traversal payloads."""
    import vault_doctor_checks.source_sessions as check

    result = check._safe_project_slug("../../../etc")
    assert "/" not in result
    assert ".." not in result

    result = check._safe_project_slug("foo/bar")
    assert "/" not in result

    assert check._safe_project_slug("") == "unknown"
    assert check._safe_project_slug("...") == "unknown"
    assert check._safe_project_slug("valid-name_1") == "valid-name_1"


def test_capture_time_prefers_created_at(tmp_path):
    note = tmp_path / "2026-01-01-foo.md"
    note.write_text("body")
    fm = {"created_at": "2026-04-21T14:33:02+00:00", "date": "2026-03-15"}
    ts, conf, signal = ss._capture_time(note, fm)
    assert (conf, signal) == (1.0, "created_at")
    expected = datetime.fromisoformat("2026-04-21T14:33:02+00:00").timestamp()
    assert abs(ts - expected) < 0.001


def test_capture_time_falls_back_to_date(tmp_path):
    note = tmp_path / "1999-12-31-foo.md"
    note.write_text("body")
    fm = {"date": "2026-04-21"}
    ts, conf, signal = ss._capture_time(note, fm)
    assert (conf, signal) == (0.9, "date")
    expected = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    assert abs(ts - expected) < 0.001


def test_capture_time_falls_back_to_filename(tmp_path):
    note = tmp_path / "2026-04-21-foo-bar.md"
    note.write_text("body")
    fm = {}
    ts, conf, signal = ss._capture_time(note, fm)
    assert (conf, signal) == (0.85, "filename")
    expected = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    assert abs(ts - expected) < 0.001


def test_capture_time_falls_back_to_mtime(tmp_path):
    note = tmp_path / "no-date-prefix.md"
    note.write_text("body")
    fixed_mtime = 1_700_000_000.0
    os.utime(note, (fixed_mtime, fixed_mtime))
    fm = {}
    ts, conf, signal = ss._capture_time(note, fm)
    assert (conf, signal) == (0.5, "mtime")
    assert abs(ts - fixed_mtime) < 0.001


def test_capture_time_malformed_date_falls_through(tmp_path):
    """Malformed date in frontmatter must not block the chain."""
    note = tmp_path / "2026-04-21-foo.md"
    note.write_text("body")
    fm = {"date": "garbage"}
    ts, conf, signal = ss._capture_time(note, fm)
    assert (conf, signal) == (0.85, "filename")


def test_scan_ignores_mtime_when_date_present(doctor_vault, monkeypatch):
    """A note whose mtime drifted into a later session's window must NOT be flagged
    when its frontmatter date and filename prefix point to the original session's day."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    day_a = "2026-04-21"
    day_b = "2026-04-22"
    sid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    sid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    # Session A: 2026-04-21, 10:00–18:00 UTC
    ts_a_start = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc).timestamp()
    ts_a_end = datetime(2026, 4, 21, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_a}.jsonl",
                 datetime.fromtimestamp(ts_a_start, tz=timezone.utc).isoformat(),
                 ts_a_end)

    # Session B: 2026-04-22, 09:00–17:00 UTC
    ts_b_start = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc).timestamp()
    ts_b_end = datetime(2026, 4, 22, 17, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_b}.jsonl",
                 datetime.fromtimestamp(ts_b_start, tz=timezone.utc).isoformat(),
                 ts_b_end)

    sess_a = _write_session_note(vault / "claude-sessions", day_a, project, sid_a, "1111")
    sess_b = _write_session_note(vault / "claude-sessions", day_b, project, sid_b, "2222")

    # Insight written on day A but mtime drifted to day B (e.g., /check-items touched it)
    insight = _write_insight(
        vault / "claude-insights",
        day_a,
        "real-capture-day-a",
        project,
        sid_a,
        sess_a.stem,
        ts_b_start + 3600,  # mtime fell into session B's window
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,  # large window so test stays valid as wall-clock advances
        project=project,
    )
    paths = [i.note_path for i in issues]
    assert str(insight) not in paths, (
        "regression: drifted mtime caused false-positive flag despite date: pointing to session A"
    )


def test_scan_emits_capture_signal_and_confidence(doctor_vault, monkeypatch):
    """Issue.extra must include capture_signal and capture_confidence so the
    skill report can flag low-confidence matches to the operator."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    day = "2026-04-22"
    sid_correct = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    sid_wrong = "wwwwwwww-wwww-wwww-wwww-wwwwwwwwwwww"

    ts_start = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc).timestamp()
    ts_end = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_correct}.jsonl",
                 datetime.fromtimestamp(ts_start, tz=timezone.utc).isoformat(),
                 ts_end)
    # A different session whose window will be the *current* (wrong) source
    other_start = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc).timestamp()
    other_end = datetime(2026, 4, 20, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_wrong}.jsonl",
                 datetime.fromtimestamp(other_start, tz=timezone.utc).isoformat(),
                 other_end)

    sess_correct = _write_session_note(vault / "claude-sessions", day, project, sid_correct, "1234")
    _write_session_note(vault / "claude-sessions", "2026-04-20", project, sid_wrong, "5678")

    insight = _write_insight(
        vault / "claude-insights",
        date=day,
        slug="signal-test",
        project=project,
        src_sid=sid_wrong,
        src_note_basename=f"2026-04-20-{project}-5678",
        mtime=ts_start + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight)]
    assert len(flagged) == 1, "expected the wrong-source note to be flagged"
    assert flagged[0].extra.get("capture_signal") == "date"
    assert flagged[0].extra.get("capture_confidence") == 0.9
    assert flagged[0].extra.get("proposed_sid") == sid_correct


def test_scan_unresolved_reason_uses_capture_time(doctor_vault, monkeypatch):
    """Unresolved-branch reason string must mention capture_time (not mtime)
    and surface signal/conf in extra. (issue #93)"""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    # One session, but its window is far from any plausible capture-time of the
    # insight. Insight's source_session does not match any session in the index,
    # so the unresolved branch fires.
    sid_only = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    s_start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc).timestamp()
    s_end = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_only}.jsonl",
                 datetime.fromtimestamp(s_start, tz=timezone.utc).isoformat(),
                 s_end)
    _write_session_note(vault / "claude-sessions", "2026-01-01", project, sid_only, "ffff")

    # Note dated far from any session, source_session not in idx
    insight_mtime = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc).timestamp()
    _write_insight(
        vault / "claude-insights",
        date="2026-04-22",
        slug="unresolved-signal",
        project=project,
        src_sid="not-a-real-sid",
        src_note_basename="2026-04-22-bogus",
        mtime=insight_mtime,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    unresolved = [i for i in issues if i.extra.get("unresolved") is True]
    assert len(unresolved) == 1, f"expected 1 unresolved issue, got {len(unresolved)}"
    iss = unresolved[0]
    assert "capture_time" in iss.reason, f"reason should mention capture_time: {iss.reason!r}"
    assert "mtime" not in iss.reason, f"reason should not mention mtime: {iss.reason!r}"
    assert iss.extra.get("capture_signal") == "date"
    assert iss.extra.get("capture_confidence") == 0.9


def test_scan_trusts_current_source_when_same_day(doctor_vault, monkeypatch):
    """If the existing source_session resolves to a same-day session note in
    the index, the check must NOT re-match — even when the matcher would
    otherwise propose a different same-day session."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    day = "2026-04-22"
    # Two same-day sessions, arranged so capture_time at 12:00 UTC (date midday)
    # falls only inside Y. Without early-exit the matcher would propose Y;
    # with early-exit, current source X is trusted.
    sid_x = "11111111-1111-1111-1111-111111111111"
    sid_y = "22222222-2222-2222-2222-222222222222"

    # Session X: 2026-04-22 09:00–11:00 (current source — does NOT contain 12:00)
    x_start = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc).timestamp()
    x_end = datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_x}.jsonl",
                 datetime.fromtimestamp(x_start, tz=timezone.utc).isoformat(),
                 x_end)

    # Session Y: 2026-04-22 12:00–18:00 (contains 12:00 — matcher would pick this)
    y_start = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc).timestamp()
    y_end = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_y}.jsonl",
                 datetime.fromtimestamp(y_start, tz=timezone.utc).isoformat(),
                 y_end)

    sess_x = _write_session_note(vault / "claude-sessions", day, project, sid_x, "xxxx")
    _write_session_note(vault / "claude-sessions", day, project, sid_y, "yyyy")

    # Insight whose date: is day; source_session points at X (correct). With
    # capture_time at 12:00 UTC the matcher would otherwise propose Y. mtime
    # is irrelevant for this test (the new check no longer uses it for
    # matching) but we set it to a known value for stability.
    insight = _write_insight(
        vault / "claude-insights",
        date=day,
        slug="trust-x",
        project=project,
        src_sid=sid_x,
        src_note_basename=sess_x.stem,
        mtime=y_start + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    paths = [i.note_path for i in issues]
    assert str(insight) not in paths, (
        "regression: same-day source was second-guessed by the matcher"
    )


def test_scan_created_at_bypasses_early_exit(doctor_vault, monkeypatch):
    """Pin test for the capture_signal != 'created_at' carve-out in Phase 1b
    early-exit (issue #93). A note with created_at AND a same-day current
    source MUST still be validated by the matcher; the early-exit must NOT
    short-circuit just because date strings agree.

    If this test goes silent (passes when it shouldn't), the carve-out has
    been removed and high-precision created_at notes are being trusted on
    same-day SID match alone — masking actual corruption."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    day = "2026-04-22"
    sid_x = "33333333-3333-3333-3333-333333333333"
    sid_y = "44444444-4444-4444-4444-444444444444"

    # Two same-day sessions, NON-overlapping.
    # Session X: 09:00–11:00 (current source — INCORRECT for the note).
    # Session Y: 14:00–16:00 (the note's actual created_at falls here).
    x_start = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc).timestamp()
    x_end = datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_x}.jsonl",
                 datetime.fromtimestamp(x_start, tz=timezone.utc).isoformat(),
                 x_end)

    y_start = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc).timestamp()
    y_end = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_y}.jsonl",
                 datetime.fromtimestamp(y_start, tz=timezone.utc).isoformat(),
                 y_end)

    sess_x = _write_session_note(vault / "claude-sessions", day, project, sid_x, "3333")
    sess_y = _write_session_note(vault / "claude-sessions", day, project, sid_y, "4444")

    # Insight: source_session is X (same day, would satisfy date-equality early-exit
    # if signal were date/filename), but created_at = 14:30 falls in Y's window.
    # The matcher MUST be allowed to run and propose Y. Early-exit must NOT fire.
    insight_path = vault / "claude-insights" / f"{day}-pin-carveout.md"
    insight_path.write_text(
        f"---\n"
        f"type: claude-insight\n"
        f"date: {day}\n"
        f"created_at: 2026-04-22T14:30:00+00:00\n"
        f"source_session: {sid_x}\n"
        f'source_session_note: "[[{sess_x.stem}]]"\n'
        f"project: {project}\n"
        f"tags:\n"
        f"  - claude/insight\n"
        f"  - claude/project/{project}\n"
        f"---\n"
        f"# pin\n",
        encoding="utf-8",
    )
    # Set mtime to a known stable value (irrelevant for matching now)
    import os as _os
    _os.utime(insight_path, (y_start + 1800, y_start + 1800))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight_path)]
    assert len(flagged) == 1, (
        "carve-out regression: created_at note with same-day current source "
        "was not re-validated by matcher (early-exit fired when it should not)"
    )
    iss = flagged[0]
    assert iss.extra.get("capture_signal") == "created_at"
    assert iss.extra.get("proposed_sid") == sid_y, (
        f"matcher should propose Y (where created_at falls), got {iss.extra.get('proposed_sid')!r}"
    )


def test_scan_uuid_first_lookup_across_projects(doctor_vault, monkeypatch):
    """Phase 1b looks up source_session UUID across all projects, not just
    the note's declared project. Insight notes from a worktree-launched skill
    may have project=A while their actual source session has project=A--worktree-slug.
    The UUID is globally unique; the cross-project lookup must trust it."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    project = doctor_vault["project"]  # "proj1"
    monkeypatch.setenv("HOME", str(home))

    # Create a worktree-style adjacent project's JSONL dir
    worktree_jsonl_dir = home / ".claude" / "projects" / "-Users-foo-proj1--worktree"
    worktree_jsonl_dir.mkdir(parents=True)

    sid_w = "77777777-7777-7777-7777-777777777777"
    w_first = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc).timestamp()
    w_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(worktree_jsonl_dir / f"{sid_w}.jsonl",
                 datetime.fromtimestamp(w_first, tz=timezone.utc).isoformat(),
                 w_last)

    # Session note records project=proj1--worktree (the worktree's name)
    sess = vault / "claude-sessions" / "2026-04-22-proj1-worktree-7777.md"
    sess.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-22\n"
        f"session_id: {sid_w}\n"
        "project: proj1--worktree\n"
        "status: summarized\n"
        "---\n"
        "# Session\n## Summary\nstub\n",
        encoding="utf-8",
    )

    # Insight has project=proj1 (declared from main-repo cwd) but its source
    # session was in a worktree (project=proj1--worktree). Without UUID-first
    # cross-project lookup, this would be flagged as stale.
    insight = _write_insight(
        vault / "claude-insights",
        date="2026-04-22",
        slug="cross-project-uuid",
        project=project,  # "proj1"
        src_sid=sid_w,
        src_note_basename=sess.stem,
        mtime=w_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    paths = [i.note_path for i in issues]
    assert str(insight) not in paths, (
        "regression: cross-project UUID resolution failed; insight flagged "
        "despite source UUID resolving to a real session note"
    )


def test_scan_basename_only_repair_when_uuid_resolves(doctor_vault, monkeypatch):
    """When the source_session UUID resolves correctly but the basename in
    source_session_note is stale (e.g., un-truncated worktree slug vs
    truncated actual filename), propose a basename-only repair. UUID stays."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid = "88888888-8888-8888-8888-888888888888"
    s_first = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc).timestamp()
    s_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid}.jsonl",
                 datetime.fromtimestamp(s_first, tz=timezone.utc).isoformat(),
                 s_last)

    # Session note exists with truncated basename
    sess = _write_session_note(vault / "claude-sessions", "2026-04-22", project, sid, "8888")

    # Insight records a STALE (un-truncated) basename in source_session_note
    insight_path = vault / "claude-insights" / "2026-04-22-basename-repair.md"
    stale_basename = "2026-04-22-proj1-some-very-long-original-name-that-was-truncated-8888"
    insight_path.write_text(
        f"---\n"
        f"type: claude-insight\n"
        f"date: 2026-04-22\n"
        f"source_session: {sid}\n"
        f'source_session_note: "[[{stale_basename}]]"\n'
        f"project: {project}\n"
        f"---\n# stub\n",
        encoding="utf-8",
    )
    import os as _os
    _os.utime(insight_path, (s_first + 1800, s_first + 1800))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight_path)]
    assert len(flagged) == 1, "expected basename-mismatch flag"
    iss = flagged[0]
    assert iss.extra.get("basename_only") is True
    assert iss.extra.get("proposed_sid") == sid  # UUID unchanged
    assert sess.stem in iss.proposed_source  # actual basename in proposal
    assert iss.confidence >= 0.95


def test_scan_caps_date_signal_confidence(doctor_vault, monkeypatch):
    """Matcher-proposed flags using only date/filename signals must be capped
    at confidence <= 0.6 -- multi-session days collapse onto noon-UTC and
    produce uniform-but-wrong proposals."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa11"
    sid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb11"

    a_first = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc).timestamp()
    a_last = datetime(2026, 4, 21, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_a}.jsonl",
                 datetime.fromtimestamp(a_first, tz=timezone.utc).isoformat(),
                 a_last)
    b_first = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc).timestamp()
    b_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_b}.jsonl",
                 datetime.fromtimestamp(b_first, tz=timezone.utc).isoformat(),
                 b_last)

    _write_session_note(vault / "claude-sessions", "2026-04-21", project, sid_a, "1111")
    _write_session_note(vault / "claude-sessions", "2026-04-22", project, sid_b, "2222")

    # Insight on day B (sole same-day session) but source_session points to
    # day-A session whose UUID does NOT resolve (no entry in idx for proj1)
    bogus_sid = "00000000-0000-0000-0000-000000000000"
    _write_insight(
        vault / "claude-insights",
        date="2026-04-22",
        slug="conf-cap",
        project=project,
        src_sid=bogus_sid,
        src_note_basename="2026-04-22-bogus",
        mtime=b_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if "conf-cap" in i.note_path and not i.extra.get("unresolved")]
    assert len(flagged) == 1
    assert flagged[0].confidence <= 0.6


@pytest.mark.parametrize("n_flags", [2, 3, 5])
def test_scan_convergence_guard_lowers_confidence(doctor_vault, monkeypatch, n_flags):
    """When N>=2 flags in a project converge on the same proposed session,
    confidence drops to <= 0.4 and convergence_warning is set, with
    convergence_count == N (review T3)."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    # One real session whose window contains noon on the day notes claim
    sid_real = "cccccccc-cccc-cccc-cccc-cccccccccc11"
    r_first = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc).timestamp()
    r_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_real}.jsonl",
                 datetime.fromtimestamp(r_first, tz=timezone.utc).isoformat(),
                 r_last)
    _write_session_note(vault / "claude-sessions", "2026-04-22", project, sid_real, "real")

    # N insights with bogus UUIDs that don't resolve -> matcher proposes sid_real for all
    for n in range(n_flags):
        slug = f"converge-{n+1}"
        # Distinct bogus UUIDs ensure the global SID index doesn't resolve them,
        # which forces the day-overlap matcher to propose sid_real for each.
        bogus = f"{n+1:08d}-1111-1111-1111-{n+1:012d}"
        _write_insight(
            vault / "claude-insights",
            date="2026-04-22",
            slug=slug,
            project=project,
            src_sid=bogus,
            src_note_basename="2026-04-22-bogus",
            mtime=r_first + 1800,
        )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if "converge" in i.note_path and i.extra.get("proposed_sid") == sid_real]
    assert len(flagged) == n_flags, f"expected {n_flags} convergence flags, got {len(flagged)}"
    for i in flagged:
        assert i.extra.get("convergence_warning") is True, (
            f"expected convergence_warning on {i.note_path}"
        )
        assert i.extra.get("convergence_count") == n_flags
        assert i.confidence <= 0.4


def test_scan_trusts_cross_midnight_source(doctor_vault, monkeypatch):
    """Phase 1b extension (issue #93): a session that started the night before
    note.date and ran into note.date is the legitimate cross-midnight case.
    The current source must be trusted even though session_note.date != note.date."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]

    monkeypatch.setenv("HOME", str(home))

    # Cross-midnight session: started 2026-04-20 22:00, ended 2026-04-21 03:00
    sid_x = "55555555-5555-5555-5555-555555555555"
    x_first = datetime(2026, 4, 20, 22, 0, tzinfo=timezone.utc).timestamp()
    x_last = datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_x}.jsonl",
                 datetime.fromtimestamp(x_first, tz=timezone.utc).isoformat(),
                 x_last)

    # Another session, same project, fully within 2026-04-21 daytime
    sid_y = "66666666-6666-6666-6666-666666666666"
    y_first = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc).timestamp()
    y_last = datetime(2026, 4, 21, 14, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_y}.jsonl",
                 datetime.fromtimestamp(y_first, tz=timezone.utc).isoformat(),
                 y_last)

    # Session note for X has date 2026-04-20 (its first-entry day)
    sess_x = _write_session_note(vault / "claude-sessions", "2026-04-20", project, sid_x, "5555")
    sess_y = _write_session_note(vault / "claude-sessions", "2026-04-21", project, sid_y, "6666")

    # Insight dated 2026-04-21 (calendar day of capture), source_session = X
    # (the session that crossed midnight). Without the JSONL-overlap extension,
    # session.date "2026-04-20" != note.date "2026-04-21" → Phase 1b doesn't fire,
    # matcher proposes Y → false positive.
    insight = _write_insight(
        vault / "claude-insights",
        date="2026-04-21",
        slug="cross-midnight-trust",
        project=project,
        src_sid=sid_x,
        src_note_basename=sess_x.stem,
        mtime=y_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    paths = [i.note_path for i in issues]
    assert str(insight) not in paths, (
        "regression: cross-midnight session_note.date=note.date-1 not trusted "
        "(session window overlaps note's calendar day → should be trusted)"
    )


# ---------------------------------------------------------------------------
# T5e Fix 1 — snapshot type filter
# ---------------------------------------------------------------------------

def test_list_all_session_notes_filters_out_snapshots(doctor_vault):
    """Snapshot notes share session_id with parents; only sessions get indexed."""
    vault = doctor_vault["vault"]
    sessions = vault / "claude-sessions"
    sid = "11111111-1111-1111-1111-111111111111"

    # Parent session note
    parent = sessions / "2026-04-21-proj1-1111.md"
    parent.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-21\n"
        f"session_id: {sid}\n"
        "project: proj1\n"
        "---\n# session\n",
        encoding="utf-8",
    )
    # Snapshot note with the same SID — must NOT clobber parent in idx
    snap = sessions / "2026-04-21-proj1-1111-snapshot-131103.md"
    snap.write_text(
        "---\n"
        "type: claude-snapshot\n"
        "date: 2026-04-21\n"
        f"session_id: {sid}\n"
        "project: proj1\n"
        "---\n# snap\n",
        encoding="utf-8",
    )

    idx = ss._list_all_session_notes(sessions)
    assert sid in idx
    assert idx[sid]["basename"] == "2026-04-21-proj1-1111", (
        f"snapshot clobbered parent: got {idx[sid]['basename']!r}"
    )


def test_list_session_notes_filters_out_snapshots(doctor_vault):
    """Project-scoped variant must also skip snapshot type."""
    vault = doctor_vault["vault"]
    sessions = vault / "claude-sessions"
    sid = "22222222-2222-2222-2222-222222222222"

    parent = sessions / "2026-04-21-proj1-2222.md"
    parent.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-21\n"
        f"session_id: {sid}\n"
        "project: proj1\n"
        "---\n# session\n",
        encoding="utf-8",
    )
    snap = sessions / "2026-04-21-proj1-2222-snapshot-090000.md"
    snap.write_text(
        "---\n"
        "type: claude-snapshot\n"
        "date: 2026-04-21\n"
        f"session_id: {sid}\n"
        "project: proj1\n"
        "---\n# snap\n",
        encoding="utf-8",
    )

    idx = ss._list_session_notes(sessions, "proj1")
    assert idx[sid]["basename"] == "2026-04-21-proj1-2222"


def test_list_all_session_notes_warns_and_keeps_first_on_duplicate_sid(
    tmp_path, capsys
):
    """Copilot R5: when two session notes share the same session_id (a known
    possible vault state — vault-import collision, rename gone wrong, etc.),
    the helper iterates in sorted order so the winner is deterministic and
    emits a stderr warning instead of silently overwriting.
    """
    sessions = tmp_path / "claude-sessions"
    sessions.mkdir()
    sid = "deadbeef-dead-beef-dead-deadbeefdead"
    # Note A sorts before Note B lexically — A should win.
    (sessions / "2026-04-26-aaa-proj1-collide.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-26\n"
        f"session_id: {sid}\nproject: proj1\nstatus: summarized\n---\n# A\n",
        encoding="utf-8",
    )
    (sessions / "2026-04-26-bbb-proj1-collide.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-26\n"
        f"session_id: {sid}\nproject: proj1\nstatus: summarized\n---\n# B\n",
        encoding="utf-8",
    )
    capsys.readouterr()  # drain
    idx = ss._list_all_session_notes(sessions)
    assert sid in idx
    assert idx[sid]["basename"] == "2026-04-26-aaa-proj1-collide", (
        f"sorted-order winner should be the lexically-first file, got {idx[sid]['basename']}"
    )
    captured = capsys.readouterr()
    assert "duplicate session_id" in captured.err
    assert "deadbeef" in captured.err  # short SID prefix
    assert "rename one to disambiguate" in captured.err


def test_list_session_notes_warns_and_keeps_first_on_duplicate_sid(
    tmp_path, capsys
):
    """Copilot R5: parity-symmetry — _list_session_notes must also iterate
    deterministically and warn on duplicate SIDs."""
    sessions = tmp_path / "claude-sessions"
    sessions.mkdir()
    sid = "feedface-feed-face-feed-feedfacefeed"
    (sessions / "2026-04-26-bbb-projP-collide.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-26\n"
        f"session_id: {sid}\nproject: projP\nstatus: summarized\n---\n# B\n",
        encoding="utf-8",
    )
    (sessions / "2026-04-26-aaa-projP-collide.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-26\n"
        f"session_id: {sid}\nproject: projP\nstatus: summarized\n---\n# A\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    idx = ss._list_session_notes(sessions, "projP")
    assert idx[sid]["basename"] == "2026-04-26-aaa-projP-collide"
    captured = capsys.readouterr()
    assert "duplicate session_id" in captured.err


# ---------------------------------------------------------------------------
# T5e Fix 2 — trust UUID when JSONL exists but session note is missing
# ---------------------------------------------------------------------------

def test_scan_trusts_uuid_when_jsonl_exists_but_note_missing(doctor_vault, monkeypatch):
    """When source_session UUID has a real JSONL but no session note, the
    UUID is still authoritative — refuse to propose a different-session
    rewrite. (Reference: issue #93 + #98 interaction.)"""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid_orphan = "33333333-3333-3333-3333-333333333333"
    o_first = datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc).timestamp()
    o_last = datetime(2026, 4, 22, 22, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_orphan}.jsonl",
                 datetime.fromtimestamp(o_first, tz=timezone.utc).isoformat(),
                 o_last)
    # NOTE: No session note written for sid_orphan — simulates SessionEnd hook miss

    # A different real session whose window also overlaps the day —
    # without the fix, the matcher would propose this as the "correct" target.
    sid_distractor = "44444444-4444-4444-4444-444444444444"
    d_first = datetime(2026, 4, 22, 12, 30, tzinfo=timezone.utc).timestamp()
    d_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_distractor}.jsonl",
                 datetime.fromtimestamp(d_first, tz=timezone.utc).isoformat(),
                 d_last)
    _write_session_note(vault / "claude-sessions", "2026-04-22", project, sid_distractor, "dist")

    # Insight whose source_session is the orphan UUID
    insight = _write_insight(
        vault / "claude-insights",
        date="2026-04-22",
        slug="orphan-uuid-trust",
        project=project,
        src_sid=sid_orphan,
        src_note_basename="2026-04-22-proj1-orph",
        mtime=o_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight)]
    assert len(flagged) == 1, (
        f"expected exactly 1 issue for orphan-UUID insight, got {len(flagged)}"
    )
    assert flagged[0].extra.get("unresolved") is True
    assert flagged[0].extra.get("missing_session_note") is True
    assert flagged[0].extra.get("proposed_sid") != sid_distractor, (
        "regression: must not propose a different session when source UUID "
        "had a real JSONL (just missing session note)"
    )


# ---------------------------------------------------------------------------
# T5e Fix 3 — day-overlap matcher for date-precision signals
# ---------------------------------------------------------------------------

def test_scan_day_overlap_picks_morning_session(doctor_vault, monkeypatch):
    """Sessions that ended before noon UTC must still be candidates for
    notes whose date matches the calendar day. Old noon-anchor matcher
    excluded them; day-overlap matcher includes them by overlap size."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    # Morning session: 08:00 → 11:05 UTC (ended before noon)
    sid_morning = "55555555-5555-5555-5555-555555555555"
    m_first = datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc).timestamp()
    m_last = datetime(2026, 4, 24, 11, 5, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_morning}.jsonl",
                 datetime.fromtimestamp(m_first, tz=timezone.utc).isoformat(),
                 m_last)
    sess_m = _write_session_note(vault / "claude-sessions", "2026-04-24", project, sid_morning, "morn")

    # Noon-anchored session: 12:30 → 14:00 — what the old matcher would have picked
    sid_noon = "66666666-6666-6666-6666-666666666666"
    n_first = datetime(2026, 4, 24, 12, 30, tzinfo=timezone.utc).timestamp()
    n_last = datetime(2026, 4, 24, 14, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(jsonl_dir / f"{sid_noon}.jsonl",
                 datetime.fromtimestamp(n_first, tz=timezone.utc).isoformat(),
                 n_last)
    _write_session_note(vault / "claude-sessions", "2026-04-24", project, sid_noon, "noon")

    # Insight on 2026-04-24 with a non-resolving source_session UUID and no
    # JSONL anywhere — falls through to the matcher. Morning session has
    # the larger overlap (185 minutes vs 90 minutes), so day-overlap picks it.
    insight = _write_insight(
        vault / "claude-insights",
        date="2026-04-24",
        slug="morning-session",
        project=project,
        src_sid="00000000-0000-0000-0000-000000000099",
        src_note_basename="2026-04-24-bogus",
        mtime=m_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight) and not i.extra.get("unresolved")]
    assert len(flagged) == 1, (
        f"expected exactly one non-unresolved issue for {insight}, got {len(flagged)}: {flagged}"
    )
    # Day-overlap matcher should pick the morning session (larger overlap)
    assert flagged[0].extra.get("proposed_sid") == sid_morning, (
        f"day-overlap matcher should prefer morning session ({sid_morning}) "
        f"over noon session ({sid_noon}); got {flagged[0].extra.get('proposed_sid')}"
    )


def test_scan_caps_mtime_signal_confidence_below_convergence_floor(doctor_vault, monkeypatch):
    """When capture_signal falls all the way to mtime (no created_at, no date
    frontmatter, no YYYY-MM-DD filename prefix), the proposed-rewrite confidence
    must be capped at <=0.3 — below the convergence floor of 0.4 — so an
    operator never auto-applies an mtime-only proposal (review C2)."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    # Two sessions on different days so the date-overlap matcher returns a
    # different session than the one currently referenced.
    a_start = calendar.timegm(time.strptime("2026-04-15 10:00", "%Y-%m-%d %H:%M"))
    a_end = a_start + 3600
    _write_jsonl(jsonl_dir / "sid-a.jsonl", "2026-04-15T10:00:00Z", a_end)
    _write_session_note(vault / "claude-sessions", "2026-04-15", project, "sid-a", "aaaa")

    b_start = calendar.timegm(time.strptime("2026-04-16 10:00", "%Y-%m-%d %H:%M"))
    b_end = b_start + 4 * 3600
    _write_jsonl(jsonl_dir / "sid-b.jsonl", "2026-04-16T10:00:00Z", b_end)
    _write_session_note(vault / "claude-sessions", "2026-04-16", project, "sid-b", "bbbb")

    # Insight with NO created_at, NO date frontmatter, NO YYYY-MM-DD filename
    # prefix → mtime is the only available signal. Filename intentionally
    # avoids the date prefix.
    insight = vault / "claude-insights" / "no-date-prefix-mtime-only.md"
    insight.write_text(
        "---\n"
        "type: claude-insight\n"
        f"source_session: sid-a\n"
        f'source_session_note: "[[2026-04-15-{project}-aaaa]]"\n'
        f"project: {project}\n"
        "tags:\n"
        "  - claude/insight\n"
        f"  - claude/project/{project}\n"
        "---\n"
        "# body\n",
        encoding="utf-8",
    )
    # Set mtime inside session B's window so the matcher proposes sid-b.
    insight_mtime = b_start + 1800
    os.utime(insight, (insight_mtime, insight_mtime))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [
        i for i in issues
        if i.note_path == str(insight)
        and not i.extra.get("unresolved")
        and not i.extra.get("basename_only")
    ]
    assert len(flagged) == 1, (
        f"expected 1 stale flag for mtime-signal insight, got {len(flagged)}: "
        f"{[(i.confidence, i.extra) for i in flagged]}"
    )
    assert flagged[0].extra.get("capture_signal") == "mtime", (
        f"test setup error: expected mtime signal, got {flagged[0].extra.get('capture_signal')}"
    )
    assert flagged[0].confidence <= 0.3, (
        f"mtime-signal confidence must be <=0.3, got {flagged[0].confidence}"
    )


def test_scan_emits_unresolved_when_jsonl_exists_but_session_note_missing(
    doctor_vault, monkeypatch
):
    """When source_session UUID has a real JSONL but no vault session note,
    emit an unresolved diagnostic Issue surfacing the coverage gap. UUID
    remains authoritative — never propose a different-session rewrite
    (review C3)."""
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid_orphan = "55555555-5555-5555-5555-555555555555"
    o_first = datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc).timestamp()
    o_last = datetime(2026, 4, 22, 22, 0, tzinfo=timezone.utc).timestamp()
    orphan_jsonl = jsonl_dir / f"{sid_orphan}.jsonl"
    _write_jsonl(
        orphan_jsonl,
        datetime.fromtimestamp(o_first, tz=timezone.utc).isoformat(),
        o_last,
    )
    # NOTE: deliberately NO session note for sid_orphan — coverage gap.

    insight = _write_insight(
        vault / "claude-insights",
        date="2026-04-22",
        slug="orphan-uuid-c3",
        project=project,
        src_sid=sid_orphan,
        src_note_basename="2026-04-22-proj1-orph",
        mtime=o_first + 1800,
    )

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(insight)]
    assert len(flagged) == 1, (
        f"expected exactly 1 issue for orphan-UUID insight, got {len(flagged)}"
    )
    issue = flagged[0]
    assert issue.extra.get("unresolved") is True
    assert issue.extra.get("missing_session_note") is True
    assert issue.extra.get("jsonl_path") == str(orphan_jsonl)
    assert issue.confidence == 0.0


def test_list_all_session_notes_warns_on_malformed_frontmatter(tmp_path, capsys):
    """A `.md` file that opens with `---` but whose frontmatter fails to parse
    should be skipped AND warned about on stderr — operators need a signal
    that something is wrong with that note (review C5)."""
    sessions_dir = tmp_path / "claude-sessions"
    sessions_dir.mkdir()
    bad = sessions_dir / "2026-04-22-malformed.md"
    # Frontmatter block opens with --- but has no closing --- on its own line:
    # _parse_frontmatter regex returns {} (no match), and the file starts with
    # "---", so the malformed-warning branch fires.
    bad.write_text("---\nfoo: bar\nno closing block here\n", encoding="utf-8")

    out = ss._list_all_session_notes(sessions_dir)
    captured = capsys.readouterr()
    assert out == {}, f"expected empty dict for malformed-only dir, got {out}"
    assert "[vault_doctor] malformed frontmatter, skipped:" in captured.err
    assert "2026-04-22-malformed.md" in captured.err


def test_phase_1b_fallback_via_find_jsonl_anywhere(tmp_path, monkeypatch):
    """Phase 1b's session-window lookup must fall back to _find_jsonl_anywhere
    when the session-note's worktree-suffixed `project:` does not resolve via
    `_jsonl_dir_for_project`. Without the fix, the date matcher proposes a
    different (canonical-project) session as a stale rewrite (review I4)."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-insights").mkdir(parents=True)

    # Single canonical project dir under HOME=tmp_path. Both JSONLs live here
    # (worktrees share parent-repo CC project dir), but the session-NOTE for
    # sid_correct claims a worktree-suffixed `project:` value that won't
    # resolve via _jsonl_dir_for_project.
    canonical_dir = tmp_path / ".claude" / "projects" / "-Users-foo-obsidian-brain"
    canonical_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Day used for note + sessions
    day_start = calendar.timegm(time.strptime("2026-04-20 00:00", "%Y-%m-%d %H:%M"))

    # sid_correct: window covers most of the day; session note claims
    # worktree-suffixed project name
    sid_correct = "11111111-1111-1111-1111-111111111111"
    correct_first = day_start + 9 * 3600
    correct_last = day_start + 18 * 3600
    _write_jsonl(
        canonical_dir / f"{sid_correct}.jsonl",
        datetime.fromtimestamp(correct_first, tz=timezone.utc).isoformat(),
        correct_last,
    )
    correct_note = vault / "claude-sessions" / "2026-04-20-obsidian-brain-corr.md"
    correct_note.write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-20\n"
        f"session_id: {sid_correct}\n"
        # Worktree-suffixed project — _jsonl_dir_for_project misses this.
        "project: obsidian-brain--issue-81-slug\n"
        "status: summarized\n"
        "---\n# s\n",
        encoding="utf-8",
    )

    # sid_wrong: also on 2026-04-20; session note claims canonical project.
    # Without the fix, the date matcher (operating in canonical project's idx)
    # picks this as the "correct" target, producing a stale-flag false positive.
    sid_wrong = "22222222-2222-2222-2222-222222222222"
    wrong_first = day_start + 8 * 3600
    wrong_last = day_start + 19 * 3600
    _write_jsonl(
        canonical_dir / f"{sid_wrong}.jsonl",
        datetime.fromtimestamp(wrong_first, tz=timezone.utc).isoformat(),
        wrong_last,
    )
    (vault / "claude-sessions" / "2026-04-20-obsidian-brain-wrng.md").write_text(
        "---\n"
        "type: claude-session\n"
        "date: 2026-04-20\n"
        f"session_id: {sid_wrong}\n"
        "project: obsidian-brain\n"
        "status: summarized\n"
        "---\n# s\n",
        encoding="utf-8",
    )

    # Insight: project=obsidian-brain (canonical), source_session=sid_correct,
    # source_session_note=basename of sid_correct's note.
    insight = vault / "claude-insights" / "2026-04-20-i4-fallback.md"
    insight.write_text(
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-20\n"
        f"source_session: {sid_correct}\n"
        'source_session_note: "[[2026-04-20-obsidian-brain-corr]]"\n'
        "project: obsidian-brain\n"
        "tags:\n"
        "  - claude/insight\n"
        "  - claude/project/obsidian-brain\n"
        "---\n# body\n",
        encoding="utf-8",
    )
    insight_mtime = day_start + 12 * 3600
    os.utime(insight, (insight_mtime, insight_mtime))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project="obsidian-brain",
    )
    flagged_stale = [
        i for i in issues
        if i.note_path == str(insight)
        and not i.extra.get("unresolved")
        and not i.extra.get("basename_only")
    ]
    assert flagged_stale == [], (
        f"Phase 1b fallback failed: matcher proposed a wrong-session rewrite "
        f"despite sid_correct having a real JSONL. Flagged: "
        f"{[(i.proposed_source, i.extra) for i in flagged_stale]}"
    )


def test_find_jsonl_anywhere_returns_first_lexicographic_match(tmp_path, monkeypatch):
    """T1: _find_jsonl_anywhere globs across all CC project dirs and returns
    the first match by sorted order. UUIDs are globally unique, but if the
    same SID file appears under two project dirs (e.g., a worktree that was
    later moved or test fixtures), the result must be deterministic across
    runs — sorted() ensures identical-input → identical-output."""
    proj_a = tmp_path / ".claude" / "projects" / "-Users-foo-projA"
    proj_b = tmp_path / ".claude" / "projects" / "-Users-foo-projB"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    sid = "11111111-1111-1111-1111-111111111111"
    (proj_a / f"{sid}.jsonl").write_text("{}\n", encoding="utf-8")
    (proj_b / f"{sid}.jsonl").write_text("{}\n", encoding="utf-8")

    found = ss._find_jsonl_anywhere(sid)
    assert found is not None
    # sorted() returns lexicographically-first match — projA before projB
    assert "projA" in str(found), f"expected projA winner, got {found}"

    # Stability across repeated calls: sorted() is a total order on str
    found2 = ss._find_jsonl_anywhere(sid)
    assert found == found2


def test_find_jsonl_anywhere_returns_none_when_missing(tmp_path, monkeypatch):
    """T1: _find_jsonl_anywhere returns None when no project dir contains
    a JSONL with the given SID."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude" / "projects" / "-Users-foo-projX").mkdir(parents=True)
    assert ss._find_jsonl_anywhere("99999999-9999-9999-9999-999999999999") is None


def test_find_jsonl_anywhere_uses_cache(tmp_path, monkeypatch):
    """Copilot R3: per-scan cache amortizes glob cost when scan() looks up the
    same UUID multiple times across notes (or both Phase 1b paths)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "deadbeef-dead-beef-dead-deadbeefdead"
    cc = tmp_path / ".claude" / "projects" / "-Users-foo-projC"
    cc.mkdir(parents=True)
    (cc / f"{sid}.jsonl").write_text("{}\n")

    cache: dict[str, ss.Path | None] = {}
    first = ss._find_jsonl_anywhere(sid, cache=cache)
    assert first is not None
    assert sid in cache and cache[sid] == first

    # Now break globbing — if cache works, lookup still succeeds.
    monkeypatch.setattr(ss.glob, "glob", lambda pattern: [])
    second = ss._find_jsonl_anywhere(sid, cache=cache)
    assert second == first, "cache hit must short-circuit the glob"

    # Negative cache: a missing SID is also memoized.
    miss_sid = "11111111-1111-1111-1111-111111111111"
    missed = ss._find_jsonl_anywhere(miss_sid, cache=cache)
    assert missed is None
    assert miss_sid in cache and cache[miss_sid] is None


def test_scan_reason_text_branches_by_signal(doctor_vault, monkeypatch):
    """Copilot R3: day-precision matches (date/filename signal) describe a
    calendar-day overlap; created_at matches describe a point-in-window match.
    Reason strings must reflect the actual matcher used.
    """
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    # date-signal: insight has frontmatter `date:` only. Day-overlap matcher fires.
    sid_date_target = "33333333-3333-3333-3333-333333333333"
    d_first = datetime(2026, 4, 22, 8, 0, tzinfo=timezone.utc).timestamp()
    d_last = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(
        jsonl_dir / f"{sid_date_target}.jsonl",
        datetime.fromtimestamp(d_first, tz=timezone.utc).isoformat(),
        d_last,
    )
    _write_session_note(
        vault / "claude-sessions", "2026-04-22", project, sid_date_target, "dtgt"
    )

    insight_date = vault / "claude-insights" / "2026-04-22-date-signal.md"
    insight_date.write_text(
        "---\n"
        "type: claude-insight\n"
        "date: 2026-04-22\n"
        "source_session: 00000000-0000-0000-0000-000000000088\n"
        'source_session_note: "[[bogus]]"\n'
        f"project: {project}\n"
        "tags:\n"
        f"  - claude/insight\n"
        "---\n# d\n",
        encoding="utf-8",
    )
    os.utime(insight_date, (d_first + 3600, d_first + 3600))

    # created_at-signal: insight has frontmatter `created_at:`. Point matcher fires.
    sid_ca_target = "44444444-4444-4444-4444-444444444444"
    c_first = datetime(2026, 4, 23, 9, 0, tzinfo=timezone.utc).timestamp()
    c_last = datetime(2026, 4, 23, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(
        jsonl_dir / f"{sid_ca_target}.jsonl",
        datetime.fromtimestamp(c_first, tz=timezone.utc).isoformat(),
        c_last,
    )
    _write_session_note(
        vault / "claude-sessions", "2026-04-23", project, sid_ca_target, "ctgt"
    )

    insight_ca = vault / "claude-insights" / "2026-04-23-ca-signal.md"
    insight_ca.write_text(
        "---\n"
        "type: claude-insight\n"
        "created_at: 2026-04-23T10:30:00+00:00\n"
        "source_session: 00000000-0000-0000-0000-000000000077\n"
        'source_session_note: "[[bogus]]"\n'
        f"project: {project}\n"
        "tags:\n"
        f"  - claude/insight\n"
        "---\n# c\n",
        encoding="utf-8",
    )
    os.utime(insight_ca, (c_first + 1800, c_first + 1800))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )

    date_issue = next(i for i in issues if i.note_path == str(insight_date))
    assert "calendar day" in date_issue.reason, (
        f"date-signal reason should describe calendar-day overlap, got: {date_issue.reason}"
    )
    assert "overlaps session" in date_issue.reason

    ca_issue = next(i for i in issues if i.note_path == str(insight_ca))
    assert "capture_time" in ca_issue.reason, (
        f"created_at-signal reason should describe capture_time, got: {ca_issue.reason}"
    )
    assert "matches session" in ca_issue.reason and "window" in ca_issue.reason


def test_scan_reason_text_for_mtime_fallback_uses_point_in_window(
    doctor_vault, monkeypatch
):
    """Copilot R4-1: when capture_signal is 'mtime' AND there's no fm.date
    AND no YYYY-MM-DD filename prefix, scan() falls through to the point-in-
    window matcher (not day-overlap). Reason text must say 'capture_time
    matches session window' not 'calendar day overlaps session window'.
    """
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid_target = "55555555-5555-5555-5555-555555555555"
    t_first = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc).timestamp()
    t_last = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(
        jsonl_dir / f"{sid_target}.jsonl",
        datetime.fromtimestamp(t_first, tz=timezone.utc).isoformat(),
        t_last,
    )
    _write_session_note(
        vault / "claude-sessions", "2026-04-24", project, sid_target, "tgt5"
    )

    # Note with NO created_at, NO date frontmatter, NO YYYY-MM-DD filename prefix.
    # Filename is intentionally non-date-prefixed.
    note = vault / "claude-insights" / "mtime-only-no-date-no-filename.md"
    note.write_text(
        "---\n"
        "type: claude-insight\n"
        "source_session: 00000000-0000-0000-0000-000000000055\n"
        'source_session_note: "[[bogus]]"\n'
        f"project: {project}\n"
        "tags:\n"
        f"  - claude/insight\n"
        "---\n# m\n",
        encoding="utf-8",
    )
    os.utime(note, (t_first + 1800, t_first + 1800))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    flagged = [i for i in issues if i.note_path == str(note)]
    assert flagged, "mtime-only note should flag (mtime falls inside window)"
    issue = flagged[0]
    assert issue.extra.get("capture_signal") == "mtime"
    assert "capture_time" in issue.reason, (
        f"mtime fallback uses point-in-window matcher; reason should say "
        f"'capture_time' not 'calendar day'. Got: {issue.reason}"
    )
    assert "calendar day" not in issue.reason, (
        f"mtime-fallback reason must not claim calendar-day overlap. Got: {issue.reason}"
    )


def test_convergence_guard_excludes_created_at_signal(doctor_vault, monkeypatch):
    """Copilot R4-2: created_at signal uses point-in-window matching with
    sub-day precision. Two legitimate stale insights from the same session
    sharing a proposal target is normal — not heuristic collapse — so they
    must NOT be capped to 0.4 by the convergence guard.
    """
    vault = doctor_vault["vault"]
    home = doctor_vault["home"]
    jsonl_dir = doctor_vault["jsonl_dir"]
    project = doctor_vault["project"]
    monkeypatch.setenv("HOME", str(home))

    sid_target = "66666666-6666-6666-6666-666666666666"
    t_first = datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc).timestamp()
    t_last = datetime(2026, 4, 25, 18, 0, tzinfo=timezone.utc).timestamp()
    _write_jsonl(
        jsonl_dir / f"{sid_target}.jsonl",
        datetime.fromtimestamp(t_first, tz=timezone.utc).isoformat(),
        t_last,
    )
    _write_session_note(
        vault / "claude-sessions", "2026-04-25", project, sid_target, "tgt6"
    )

    # Two insights with created_at signal both stale-pointing at a missing UUID.
    # Both will be matched to sid_target (point-in-window). Without the R4-2
    # fix, the convergence guard would cap both to 0.4 — a false positive.
    for slug, ts in (("alpha", "2026-04-25T10:00:00+00:00"),
                     ("beta", "2026-04-25T11:30:00+00:00")):
        n = vault / "claude-insights" / f"created-at-conv-{slug}.md"
        n.write_text(
            "---\n"
            "type: claude-insight\n"
            f"created_at: {ts}\n"
            "source_session: 00000000-0000-0000-0000-000000000066\n"
            'source_session_note: "[[bogus]]"\n'
            f"project: {project}\n"
            "tags:\n"
            f"  - claude/insight\n"
            "---\n# x\n",
            encoding="utf-8",
        )
        os.utime(n, (t_first + 3600, t_first + 3600))

    issues = ss.scan(
        vault_path=str(vault),
        sessions_folder="claude-sessions",
        insights_folder="claude-insights",
        days=10000,
        project=project,
    )
    created_at_flags = [
        i for i in issues
        if i.extra.get("capture_signal") == "created_at"
        and i.extra.get("proposed_sid") == sid_target
    ]
    assert len(created_at_flags) == 2, (
        f"expected exactly 2 created_at flags converging on {sid_target}, "
        f"got {len(created_at_flags)}"
    )
    for issue in created_at_flags:
        assert issue.confidence == 0.95, (
            f"created_at-signal flag must keep its 0.95 confidence — "
            f"convergence guard should not cap created_at. Got: {issue.confidence}"
        )
        assert not issue.extra.get("convergence_warning"), (
            f"convergence_warning must be False for created_at flags. "
            f"Got: {issue.extra}"
        )
