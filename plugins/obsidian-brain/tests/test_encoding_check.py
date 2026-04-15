"""Tests for vault_doctor encoding-corruption check."""

import json
import os
from pathlib import Path

import pytest

# Add scripts/ to path for vault_doctor_checks imports
import sys
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SCRIPTS_DIR))

from vault_doctor_checks.encoding_corruption import scan, apply, NAME


def _write_note(path, frontmatter: dict, body: str = ""):
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


class TestEncodingCorruptionScan:
    def test_clean_note_not_flagged(self, tmp_vault):
        """Valid UTF-8 note produces no issues."""
        sess = tmp_vault / "claude-sessions"
        _write_note(sess / "2026-04-13-test-0001.md",
            {"date": "2026-04-13", "project": "p", "type": "claude-session"},
            "# Clean note\nAll valid UTF-8.")
        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues) == 0

    def test_binary_note_flagged(self, tmp_vault):
        """Note with invalid UTF-8 bytes is flagged."""
        sess = tmp_vault / "claude-sessions"
        note = sess / "2026-04-13-corrupt-0001.md"
        content = "---\ndate: 2026-04-13\nproject: p\n---\n\n# Corrupt\nSome text."
        note.write_bytes(content.encode("utf-8") + b"\xff\xfe\x00\x80")

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues) == 1
        assert issues[0].check == NAME
        assert "invalid byte" in issues[0].current_source.lower() or "invalid" in issues[0].reason.lower()

    def test_scans_both_folders(self, tmp_vault):
        """Scan checks both sessions and insights folders."""
        ins = tmp_vault / "claude-insights"
        note = ins / "2026-04-13-insight-0001.md"
        content = "---\ndate: 2026-04-13\nproject: p\n---\n\n# Bad insight"
        note.write_bytes(content.encode("utf-8") + b"\xff")

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues) == 1

    def test_project_filter(self, tmp_vault):
        """Project filter excludes non-matching notes."""
        sess = tmp_vault / "claude-sessions"
        note_a = sess / "2026-04-13-proj-a-0001.md"
        note_b = sess / "2026-04-13-proj-b-0001.md"
        bad = b"---\ndate: 2026-04-13\nproject: p\n---\n\nbad\xff"
        note_a.write_bytes(bad)
        note_b.write_bytes(bad)

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999, project="proj-a")
        assert len(issues) == 1
        assert "proj-a" in issues[0].note_path


class TestEncodingCorruptionApply:
    def test_apply_replaces_bad_bytes(self, tmp_vault, tmp_path):
        """Apply re-encodes the note, replacing invalid bytes with U+FFFD."""
        sess = tmp_vault / "claude-sessions"
        note = sess / "2026-04-13-corrupt-0001.md"
        original = "---\ndate: 2026-04-13\n---\n\n# Test\nGood text."
        note.write_bytes(original.encode("utf-8") + b"\xff\xfe")

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues) == 1

        backup_root = str(tmp_path / "backups")
        results = apply(issues, backup_root)
        assert len(results) == 1
        assert results[0].status == "applied"
        assert results[0].backup_path is not None

        # Re-read — should be valid UTF-8 now
        fixed = note.read_text(encoding="utf-8")
        assert "Good text." in fixed
        assert "\ufffd" in fixed  # replacement character present

        # Backup should contain original bytes
        backup_bytes = Path(results[0].backup_path).read_bytes()
        assert b"\xff\xfe" in backup_bytes

    def test_apply_creates_backup(self, tmp_vault, tmp_path):
        """Apply creates backup before modifying."""
        sess = tmp_vault / "claude-sessions"
        note = sess / "2026-04-13-bak-0001.md"
        note.write_bytes(b"---\ndate: 2026-04-13\n---\n\nbad\xff")

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        backup_root = str(tmp_path / "backups")
        results = apply(issues, backup_root)

        assert os.path.isfile(results[0].backup_path)

    def test_rescan_after_apply_clean(self, tmp_vault, tmp_path):
        """After apply, rescan finds no issues."""
        sess = tmp_vault / "claude-sessions"
        note = sess / "2026-04-13-fix-0001.md"
        note.write_bytes(b"---\ndate: 2026-04-13\n---\n\ntext\xff\xfe")

        issues = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues) == 1

        apply(issues, str(tmp_path / "backups"))

        issues_after = scan(str(tmp_vault), "claude-sessions", "claude-insights", 9999)
        assert len(issues_after) == 0
