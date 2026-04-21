"""End-to-end integration test for /vault-doctor source-sessions flow."""

import calendar
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def test_end_to_end_scan_apply_verify(tmp_path):
    """Full flow: seed vault → scan → apply → verify fixes and backups."""
    # --- Build vault ---
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-insights").mkdir(parents=True)

    # --- JSONL home for project ---
    home = tmp_path
    cc_projects = home / ".claude" / "projects" / "-Users-foo-proj1"
    cc_projects.mkdir(parents=True)

    # Two sessions on different days
    a_start = calendar.timegm(time.strptime("2026-04-09 10:00", "%Y-%m-%d %H:%M"))
    b_start = calendar.timegm(time.strptime("2026-04-10 14:00", "%Y-%m-%d %H:%M"))

    (cc_projects / "sid-a.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": "2026-04-09T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    os.utime(cc_projects / "sid-a.jsonl", (a_start + 3600, a_start + 3600))
    (cc_projects / "sid-b.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": "2026-04-10T14:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    os.utime(cc_projects / "sid-b.jsonl", (b_start + 3600, b_start + 3600))

    # Session notes
    (vault / "claude-sessions" / "2026-04-09-proj1-aaaa.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-09\nsession_id: sid-a\nproject: proj1\nstatus: summarized\n---\n# s\n",
        encoding="utf-8",
    )
    (vault / "claude-sessions" / "2026-04-10-proj1-bbbb.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-10\nsession_id: sid-b\nproject: proj1\nstatus: summarized\n---\n# s\n",
        encoding="utf-8",
    )

    # Stale insight (captured in session B but stamped with session A)
    insight = vault / "claude-insights" / "2026-04-10-stale-e2e.md"
    insight.write_text(
        '---\n'
        'type: claude-insight\n'
        'date: 2026-04-10\n'
        'source_session: sid-a\n'
        'source_session_note: "[[2026-04-09-proj1-aaaa]]"\n'
        'project: proj1\n'
        'tags:\n'
        '  - claude/insight\n'
        '  - claude/project/proj1\n'
        '---\n'
        '\n'
        '# body unchanged\n'
        '\n'
        'paragraph with [[2026-04-09-proj1-aaaa]] in body\n',
        encoding="utf-8",
    )
    os.utime(insight, (b_start + 1800, b_start + 1800))
    original_text = insight.read_text(encoding="utf-8")
    original_body = original_text.split("---\n", 2)[-1]

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["OBSIDIAN_BRAIN_VAULT"] = str(vault)
    env["OBSIDIAN_BRAIN_SESSIONS_FOLDER"] = "claude-sessions"
    env["OBSIDIAN_BRAIN_INSIGHTS_FOLDER"] = "claude-insights"

    script = Path(__file__).parent.parent / "scripts" / "vault_doctor.py"

    # --- 1. Dry-run → exit 1, file untouched ---
    r = subprocess.run(
        [sys.executable, str(script), "--check", "source-sessions", "--days", "60",
         "--project", "proj1", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 1, f"dry-run exit: expected 1, got {r.returncode}: {r.stderr}"
    payload = json.loads(r.stdout)
    assert payload["total_issues"] == 1
    assert payload["issues"][0]["check"] == "source-sessions"
    assert payload["issues"][0]["project"] == "proj1"
    assert insight.read_text(encoding="utf-8") == original_text, "dry-run must not modify the file"

    # --- 2. Apply with --yes (non-interactive) ---
    r = subprocess.run(
        [sys.executable, str(script), "--check", "source-sessions", "--days", "60",
         "--project", "proj1", "--apply", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 1, f"apply exit: expected 1 (successful apply), got {r.returncode}: {r.stderr}"

    # --- 3. Verify: frontmatter patched, body byte-identical, backup exists ---
    patched = insight.read_text(encoding="utf-8")
    assert "source_session: sid-b" in patched
    assert 'source_session_note: "[[2026-04-10-proj1-bbbb]]"' in patched
    assert "claude/project/proj1" in patched
    assert "type: claude-insight" in patched

    patched_body = patched.split("---\n", 2)[-1]
    assert patched_body == original_body, "body must be byte-identical after apply"

    # Backup must exist under ~/.claude/obsidian-brain-doctor-backup/<timestamp>/proj1/
    backup_root = home / ".claude" / "obsidian-brain-doctor-backup"
    assert backup_root.exists(), f"backup root not created at {backup_root}"
    backups = list(backup_root.rglob("2026-04-10-stale-e2e.md"))
    assert backups, f"no backup found for the patched note under {backup_root}"
    backup_content = backups[0].read_text(encoding="utf-8")
    assert backup_content == original_text, "backup must match pre-patch content exactly"

    # --- 4. Re-scan → exit 0 (clean) ---
    r = subprocess.run(
        [sys.executable, str(script), "--check", "source-sessions", "--days", "60",
         "--project", "proj1", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"re-scan exit: expected 0 (clean), got {r.returncode}: {r.stderr}"
    assert json.loads(r.stdout)["total_issues"] == 0
