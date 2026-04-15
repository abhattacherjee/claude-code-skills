"""Tests for collect_vault_corpus() — vault data collection for /emerge."""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import obsidian_utils


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(path, frontmatter: dict, body: str = ""):
    """Write a vault note with YAML frontmatter and optional body."""
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _today_str():
    return date.today().isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# CORPUS_01: happy path — multi-project, 5 notes, 2 projects
# ---------------------------------------------------------------------------


class TestCorpusHappyPath:
    def test_happy_path_multi_project(self, tmp_vault):
        """CORPUS_01: 5 session notes across 2 projects → all included."""
        sessions = tmp_vault / "claude-sessions"
        for i in range(3):
            _write_note(
                sessions / f"{_today_str()}-alpha-{i:04x}.md",
                {
                    "type": "claude-session",
                    "date": _today_str(),
                    "project": "alpha",
                    "status": "summarized",
                    "tags": ["claude/session", "claude/project/alpha"],
                },
                body=(
                    "## Summary\n"
                    f"Did thing {i} in alpha.\n\n"
                    "## Key Decisions\n"
                    "- Chose pattern A.\n\n"
                    "## Errors Encountered\n"
                    "None.\n\n"
                    "## Open Questions / Next Steps\n"
                    "- [ ] Follow up on alpha\n"
                ),
            )
        for i in range(2):
            _write_note(
                sessions / f"{_today_str()}-beta-{i:04x}.md",
                {
                    "type": "claude-session",
                    "date": _today_str(),
                    "project": "beta",
                    "status": "summarized",
                    "tags": ["claude/session", "claude/project/beta"],
                },
                body=(
                    "## Summary\n"
                    f"Did thing {i} in beta.\n\n"
                    "## Key Decisions\n"
                    "- Chose pattern B.\n\n"
                    "## Errors Encountered\n"
                    "None.\n\n"
                    "## Open Questions / Next Steps\n"
                    "- [ ] Follow up on beta\n"
                ),
            )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 5
        projects = {n["project"] for n in result["notes"]}
        assert projects == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# CORPUS_02: date filtering excludes old notes
# ---------------------------------------------------------------------------


class TestCorpusDateFilter:
    def test_old_notes_excluded(self, tmp_vault):
        """CORPUS_02: notes older than `days` are excluded."""
        sessions = tmp_vault / "claude-sessions"
        # Recent note
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body="## Summary\nRecent work.\n",
        )
        # Old note (60 days ago)
        old_date = _days_ago(60)
        _write_note(
            sessions / f"{old_date}-proj-0002.md",
            {
                "type": "claude-session",
                "date": old_date,
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body="## Summary\nOld work.\n",
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 1
        assert result["notes"][0]["summary"].startswith("Recent work")


# ---------------------------------------------------------------------------
# CORPUS_03: unsummarized note fallback
# ---------------------------------------------------------------------------


class TestCorpusUnsummarizedFallback:
    def test_unsummarized_uses_raw_conversation(self, tmp_vault):
        """CORPUS_03: AI summary unavailable → fall back to raw conversation."""
        sessions = tmp_vault / "claude-sessions"
        raw_text = "User asked about deployment. " * 30  # >500 chars total
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "auto-logged",
                "tags": ["claude/session"],
            },
            body=(
                "## Summary\n"
                "Session in **proj** (15.0 min). "
                "AI summary unavailable — raw extraction below.\n\n"
                "## Conversation (raw)\n"
                f"{raw_text}\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 1
        note = result["notes"][0]
        # Should use raw conversation fallback, capped at 500 chars
        assert len(note["summary"]) <= 500
        assert "User asked about deployment" in note["summary"]


# ---------------------------------------------------------------------------
# CORPUS_04: empty vault returns zero
# ---------------------------------------------------------------------------


class TestCorpusEmptyVault:
    def test_empty_vault(self, tmp_vault):
        """CORPUS_04: empty vault → note_count 0, empty notes list."""
        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 0
        assert result["notes"] == []


# ---------------------------------------------------------------------------
# CORPUS_06: missing date frontmatter → skipped
# ---------------------------------------------------------------------------


class TestCorpusMissingDate:
    def test_missing_date_skipped(self, tmp_vault):
        """CORPUS_06: note without date in frontmatter is skipped."""
        sessions = tmp_vault / "claude-sessions"
        # Note with date
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body="## Summary\nWith date.\n",
        )
        # Note without date
        _write_note(
            sessions / f"{_today_str()}-proj-0002.md",
            {
                "type": "claude-session",
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body="## Summary\nNo date.\n",
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 1


# ---------------------------------------------------------------------------
# CORPUS_12: symlink outside vault → excluded (path containment)
# ---------------------------------------------------------------------------


class TestCorpusSymlinkContainment:
    def test_symlink_outside_vault_excluded(self, tmp_vault):
        """CORPUS_12: symlink pointing outside vault is excluded."""
        import tempfile

        sessions = tmp_vault / "claude-sessions"
        # Create a real note inside vault
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body="## Summary\nLegit note.\n",
        )
        # Create a note in a truly separate temp directory (outside vault)
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_note = Path(outside_dir) / "evil.md"
            _write_note(
                outside_note,
                {
                    "type": "claude-session",
                    "date": _today_str(),
                    "project": "evil",
                    "status": "summarized",
                    "tags": ["claude/session"],
                },
                body="## Summary\nEvil content.\n",
            )
            symlink = sessions / f"{_today_str()}-evil-0001.md"
            symlink.symlink_to(outside_note)

            result = json.loads(
                obsidian_utils.collect_vault_corpus(
                    str(tmp_vault), "claude-sessions", "claude-insights", days=7
                )
            )
            assert result["note_count"] == 1
            assert result["notes"][0]["project"] == "proj"


# ---------------------------------------------------------------------------
# CORPUS_13: JSON output has required keys
# ---------------------------------------------------------------------------


class TestCorpusJsonStructure:
    def test_json_has_required_keys(self, tmp_vault):
        """CORPUS_13: output JSON has all required top-level and per-note keys."""
        sessions = tmp_vault / "claude-sessions"
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session", "claude/topic/testing"],
            },
            body=(
                "## Summary\nDid testing.\n\n"
                "## Key Decisions\n"
                "- Decision one.\n\n"
                "## Errors Encountered\n"
                "- Fix for bug X.\n\n"
                "## Open Questions / Next Steps\n"
                "- [ ] Next thing\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )

        # Top-level keys
        assert "date_range" in result
        assert "note_count" in result
        assert "notes" in result

        # Per-note keys
        note = result["notes"][0]
        required_keys = {
            "file",
            "type",
            "date",
            "project",
            "tags",
            "summary",
            "decisions",
            "errors",
            "open_items",
        }
        assert required_keys.issubset(set(note.keys()))


# ---------------------------------------------------------------------------
# CORPUS_14: date_range format
# ---------------------------------------------------------------------------


class TestCorpusDateRange:
    def test_date_range_format(self, tmp_vault):
        """CORPUS_14: date_range is 'YYYY-MM-DD to YYYY-MM-DD'."""
        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        dr = result["date_range"]
        parts = dr.split(" to ")
        assert len(parts) == 2
        # Validate ISO format
        for part in parts:
            date.fromisoformat(part)


# ---------------------------------------------------------------------------
# CORPUS_15: section parsing — decisions (3 bullets → 3 items)
# ---------------------------------------------------------------------------


class TestCorpusSectionDecisions:
    def test_three_decision_bullets(self, tmp_vault):
        """CORPUS_15: 3 decision bullets → 3 items in decisions list."""
        sessions = tmp_vault / "claude-sessions"
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body=(
                "## Summary\nSome work.\n\n"
                "## Key Decisions\n"
                "- Decision A.\n"
                "- Decision B.\n"
                "- Decision C.\n\n"
                "## Errors Encountered\n"
                "None.\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        note = result["notes"][0]
        assert len(note["decisions"]) == 3
        assert "Decision A." in note["decisions"][0]


# ---------------------------------------------------------------------------
# CORPUS_16: section parsing — open items (2 checkboxes → 2 items)
# ---------------------------------------------------------------------------


class TestCorpusSectionOpenItems:
    def test_two_checkbox_items(self, tmp_vault):
        """CORPUS_16: 2 checkbox items → 2 open_items."""
        sessions = tmp_vault / "claude-sessions"
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body=(
                "## Summary\nSome work.\n\n"
                "## Key Decisions\n"
                "- One decision.\n\n"
                "## Errors Encountered\n"
                "None.\n\n"
                "## Open Questions / Next Steps\n"
                "- [ ] Item one\n"
                "- [ ] Item two\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        note = result["notes"][0]
        assert len(note["open_items"]) == 2


# ---------------------------------------------------------------------------
# CORPUS_17: errors "None." → empty list
# ---------------------------------------------------------------------------


class TestCorpusSectionErrorsNone:
    def test_errors_none_becomes_empty_list(self, tmp_vault):
        """CORPUS_17: 'None.' in errors section → empty errors list."""
        sessions = tmp_vault / "claude-sessions"
        _write_note(
            sessions / f"{_today_str()}-proj-0001.md",
            {
                "type": "claude-session",
                "date": _today_str(),
                "project": "proj",
                "status": "summarized",
                "tags": ["claude/session"],
            },
            body=(
                "## Summary\nSome work.\n\n"
                "## Key Decisions\n"
                "- One decision.\n\n"
                "## Errors Encountered\n"
                "None.\n\n"
                "## Open Questions / Next Steps\n"
                "- [ ] Item one\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        note = result["notes"][0]
        assert note["errors"] == []


# ---------------------------------------------------------------------------
# CORPUS_18: insights folder scanned
# ---------------------------------------------------------------------------


class TestCorpusInsightsFolder:
    def test_insights_included(self, tmp_vault):
        """CORPUS_18: notes in insights folder are also collected."""
        insights = tmp_vault / "claude-insights"
        _write_note(
            insights / f"{_today_str()}-insight-0001.md",
            {
                "type": "claude-insight",
                "date": _today_str(),
                "project": "proj",
                "tags": ["claude/insight", "claude/topic/testing"],
            },
            body=(
                "## Summary\n"
                "Discovered that tests should run before commits.\n"
            ),
        )

        result = json.loads(
            obsidian_utils.collect_vault_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", days=7
            )
        )
        assert result["note_count"] == 1
        assert result["notes"][0]["type"] == "claude-insight"


# ---------------------------------------------------------------------------
# upgrade_and_collect_corpus tests
# ---------------------------------------------------------------------------


class TestUpgradeAndCollectCorpus:
    def test_writes_corpus_to_output_path(self, tmp_vault, tmp_path):
        """Corpus JSON written to specified output path."""
        sess = tmp_vault / "claude-sessions"
        _write_note(sess / f"{_today_str()}-t-0001.md",
            {"date": _today_str(), "project": "p", "type": "claude-session", "status": "summarized"},
            "# T\n\n## Summary\nTest.")
        output = tmp_path / "corpus.json"
        status = obsidian_utils.upgrade_and_collect_corpus(
            str(tmp_vault), "claude-sessions", "claude-insights", 30, str(output))
        assert status.startswith("OK:")
        assert output.exists()
        corpus = json.loads(output.read_text())
        assert corpus["stats"]["total_notes"] == 1

    def test_empty_vault_returns_empty_status(self, tmp_vault, tmp_path):
        """Empty vault returns EMPTY status."""
        output = tmp_path / "corpus.json"
        status = obsidian_utils.upgrade_and_collect_corpus(
            str(tmp_vault), "claude-sessions", "claude-insights", 30, str(output))
        assert status == "EMPTY:0:0:0"

    def test_status_line_format(self, tmp_vault, tmp_path):
        """Status line is OK:<total>:<upgraded>:<failed>."""
        sess = tmp_vault / "claude-sessions"
        for i in range(3):
            _write_note(sess / f"{_today_str()}-t-{i:04x}.md",
                {"date": _today_str(), "project": "p", "type": "claude-session", "status": "summarized"},
                f"# T{i}\n\n## Summary\nTest {i}.")
        output = tmp_path / "corpus.json"
        status = obsidian_utils.upgrade_and_collect_corpus(
            str(tmp_vault), "claude-sessions", "claude-insights", 30, str(output))
        parts = status.split(":")
        assert parts[0] == "OK"
        assert parts[1] == "3"  # total
        assert parts[2] == "0"  # upgraded (none were auto-logged)
        assert parts[3] == "0"  # failed


class TestUpgradeErrorLogging:
    def test_failed_upgrade_logged_to_stderr(self, tmp_vault, tmp_path, capsys):
        """upgrade_and_collect_corpus logs failed upgrade to stderr."""
        sess = tmp_vault / "claude-sessions"
        # Write an auto-logged note that will trigger upgrade
        _write_note(sess / f"{_today_str()}-fail-0001.md",
            {"date": _today_str(), "project": "p", "type": "claude-session", "status": "auto-logged"},
            "# Fail\n\n## Summary\nAI summary unavailable")
        output = tmp_path / "corpus.json"
        # Mock upgrade to raise
        with patch("obsidian_utils.upgrade_unsummarized_note", side_effect=RuntimeError("haiku timeout")):
            status = obsidian_utils.upgrade_and_collect_corpus(
                str(tmp_vault), "claude-sessions", "claude-insights", 30, str(output))
        assert ":1" in status  # 1 failed
        captured = capsys.readouterr()
        assert "haiku timeout" in captured.err
