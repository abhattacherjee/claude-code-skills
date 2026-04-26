"""Tests for scripts/vault_doctor.py and the check registry."""

import importlib
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))


def test_registry_lists_source_sessions_check():
    """The registry auto-discovers the source_sessions check module."""
    import vault_doctor_checks
    importlib.reload(vault_doctor_checks)
    names = vault_doctor_checks.list_checks()
    assert "source-sessions" in names


def test_issue_and_result_dataclasses_importable():
    """Shared Issue and Result types are importable from the registry."""
    from vault_doctor_checks import Issue, Result
    issue = Issue(
        check="source-sessions",
        note_path="/tmp/foo.md",
        project="testproj",
        current_source="[[old]]",
        proposed_source="[[new]]",
        reason="mtime falls inside different session window",
        confidence=0.95,
    )
    assert issue.check == "source-sessions"
    assert issue.confidence == 0.95
    assert issue.extra == {}  # default empty dict

    result = Result(
        check="source-sessions",
        note_path="/tmp/foo.md",
        status="applied",
        backup_path="/tmp/backup/foo.md",
        error=None,
    )
    assert result.status == "applied"
    assert result.backup_path == "/tmp/backup/foo.md"


def test_cli_dry_run_reports_issues(tmp_path):
    """vault_doctor.py --check source-sessions reports without applying."""
    import subprocess, json, sys, os, time, calendar
    from pathlib import Path

    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-insights").mkdir(parents=True)
    claude_home = tmp_path / ".claude" / "projects" / "-x-proj1"
    claude_home.mkdir(parents=True)

    # Session B widened to include 2026-04-10 midday (12:00) so the new
    # date-based capture_time matches it. (issue #93)
    b_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    (claude_home / "sid-b.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": "2026-04-10T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    os.utime(claude_home / "sid-b.jsonl", (b_start + 4 * 3600, b_start + 4 * 3600))

    (vault / "claude-sessions" / "2026-04-10-proj1-bbbb.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-10\nsession_id: sid-b\nproject: proj1\nstatus: summarized\n---\n# s\n",
        encoding="utf-8",
    )
    insight = vault / "claude-insights" / "2026-04-10-stale.md"
    insight.write_text(
        '---\ntype: claude-insight\ndate: 2026-04-10\nsource_session: sid-a\nsource_session_note: "[[2026-04-09-proj1-aaaa]]"\nproject: proj1\n---\n# x\n',
        encoding="utf-8",
    )
    os.utime(insight, (b_start + 1800, b_start + 1800))

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["OBSIDIAN_BRAIN_VAULT"] = str(vault)
    env["OBSIDIAN_BRAIN_SESSIONS_FOLDER"] = "claude-sessions"
    env["OBSIDIAN_BRAIN_INSIGHTS_FOLDER"] = "claude-insights"

    script = Path(__file__).parent.parent / "scripts" / "vault_doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check", "source-sessions", "--days", "60",
         "--project", "proj1", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1, f"expected exit 1 (issues found), got {result.returncode}: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["total_issues"] >= 1
    assert any(i["check"] == "source-sessions" for i in payload["issues"])
    # File was NOT modified (dry-run default)
    assert "source_session: sid-a" in insight.read_text(encoding="utf-8")


def test_cli_apply_with_yes(tmp_path):
    """vault_doctor.py --apply --yes patches the file non-interactively."""
    import subprocess, json, sys, os, time, calendar
    from pathlib import Path

    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-insights").mkdir(parents=True)
    claude_home = tmp_path / ".claude" / "projects" / "-x-proj1"
    claude_home.mkdir(parents=True)

    # Session B widened to include 2026-04-10 midday (12:00) so the new
    # date-based capture_time matches it. (issue #93)
    b_start = calendar.timegm(time.strptime("2026-04-10 10:00", "%Y-%m-%d %H:%M"))
    (claude_home / "sid-b.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": "2026-04-10T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    os.utime(claude_home / "sid-b.jsonl", (b_start + 4 * 3600, b_start + 4 * 3600))

    (vault / "claude-sessions" / "2026-04-10-proj1-bbbb.md").write_text(
        "---\ntype: claude-session\ndate: 2026-04-10\nsession_id: sid-b\nproject: proj1\nstatus: summarized\n---\n# s\n",
        encoding="utf-8",
    )
    insight = vault / "claude-insights" / "2026-04-10-apply.md"
    insight.write_text(
        '---\ntype: claude-insight\ndate: 2026-04-10\nsource_session: sid-a\nsource_session_note: "[[2026-04-09-proj1-aaaa]]"\nproject: proj1\n---\n# x\n',
        encoding="utf-8",
    )
    os.utime(insight, (b_start + 1800, b_start + 1800))

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["OBSIDIAN_BRAIN_VAULT"] = str(vault)
    env["OBSIDIAN_BRAIN_SESSIONS_FOLDER"] = "claude-sessions"
    env["OBSIDIAN_BRAIN_INSIGHTS_FOLDER"] = "claude-insights"

    script = Path(__file__).parent.parent / "scripts" / "vault_doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check", "source-sessions", "--days", "60",
         "--project", "proj1", "--apply", "--yes"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1, f"expected exit 1 after successful apply, got {result.returncode}: {result.stderr}"
    patched = insight.read_text(encoding="utf-8")
    assert "source_session: sid-b" in patched
    assert 'source_session_note: "[[2026-04-10-proj1-bbbb]]"' in patched


def test_cli_unknown_check_errors(tmp_path):
    """Unknown --check name returns exit code 3."""
    import subprocess, sys, os
    from pathlib import Path

    env = os.environ.copy()
    env["OBSIDIAN_BRAIN_VAULT"] = str(tmp_path)

    script = Path(__file__).parent.parent / "scripts" / "vault_doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check", "nonexistent-check", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 3, f"expected exit 3, got {result.returncode}"


def test_registry_lists_spurious_wikilinks_check():
    """The registry auto-discovers the spurious_wikilinks check module."""
    import vault_doctor_checks
    importlib.reload(vault_doctor_checks)
    names = vault_doctor_checks.list_checks()
    assert "spurious-wikilinks" in names


def test_spurious_wikilinks_scan_detects_bash_conditionals(tmp_path):
    """scan() finds unescaped [[ in conversation lines."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-sessions" / "2026-04-12-proj-abcd.md").write_text(
        "---\ntype: claude-session\nproject: proj\n---\n"
        "# Session\n"
        '**User:** if [[ $BRANCH == feature/* ]]; then echo yes; fi\n'
        "**Assistant:** ok\n",
        encoding="utf-8",
    )
    from vault_doctor_checks import spurious_wikilinks
    issues = spurious_wikilinks.scan(str(vault), "claude-sessions", "claude-insights", 9999)
    assert len(issues) == 1
    assert issues[0].project == "proj"
    assert "1 line(s)" in issues[0].current_source


def test_spurious_wikilinks_scan_ignores_escaped(tmp_path):
    """scan() does not flag already-escaped \\[\\[."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-sessions" / "2026-04-12-proj-abcd.md").write_text(
        "---\ntype: claude-session\nproject: proj\n---\n"
        "# Session\n"
        r'**User:** if \[\[ $BRANCH == feature/* ]]; then echo yes; fi' + "\n",
        encoding="utf-8",
    )
    from vault_doctor_checks import spurious_wikilinks
    issues = spurious_wikilinks.scan(str(vault), "claude-sessions", "claude-insights", 9999)
    assert len(issues) == 0


def test_spurious_wikilinks_scan_ignores_non_conversation_lines(tmp_path):
    """scan() does not flag [[ in non-conversation lines (e.g., frontmatter wikilinks)."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    (vault / "claude-sessions" / "2026-04-12-proj-abcd.md").write_text(
        '---\ntype: claude-session\nproject: proj\nsource_session_note: "[[2026-04-12-proj-1234]]"\n---\n'
        "# Session\n"
        "Normal text with no bash.\n",
        encoding="utf-8",
    )
    from vault_doctor_checks import spurious_wikilinks
    issues = spurious_wikilinks.scan(str(vault), "claude-sessions", "claude-insights", 9999)
    assert len(issues) == 0


def test_spurious_wikilinks_apply_escapes_and_backs_up(tmp_path):
    """apply() escapes [[ and creates a backup."""
    vault = tmp_path / "vault"
    (vault / "claude-sessions").mkdir(parents=True)
    note = vault / "claude-sessions" / "2026-04-12-proj-abcd.md"
    note.write_text(
        "---\ntype: claude-session\nproject: proj\n---\n"
        "# Session\n"
        '**User:** if [[ $X == y ]]; then echo yes; fi\n'
        "**Assistant:** sure\n",
        encoding="utf-8",
    )

    from vault_doctor_checks import spurious_wikilinks
    issues = spurious_wikilinks.scan(str(vault), "claude-sessions", "claude-insights", 9999)
    assert len(issues) == 1

    backup_root = str(tmp_path / "backups")
    results = spurious_wikilinks.apply(issues, backup_root)
    assert len(results) == 1
    assert results[0].status == "applied"
    assert results[0].backup_path is not None

    patched = note.read_text(encoding="utf-8")
    assert "[[" not in patched.split("# Session")[1]
    assert r"\[\[" in patched

    # Backup contains original
    backup_content = Path(results[0].backup_path).read_text(encoding="utf-8")
    assert "[[" in backup_content


def test_cli_missing_vault_errors(tmp_path, monkeypatch):
    """Missing vault config → exit 3."""
    import subprocess, sys, os
    from pathlib import Path

    env = os.environ.copy()
    env.pop("OBSIDIAN_BRAIN_VAULT", None)
    # Point HOME at tmp_path so load_config() can't find a real config file.
    # Run cwd from tmp_path so the per-project session cache in /tmp doesn't
    # collide with a cache entry from the real obsidian-brain project.
    env["HOME"] = str(tmp_path)
    isolated_cwd = tmp_path / "isolated-project-xyz"
    isolated_cwd.mkdir()

    script = Path(__file__).parent.parent / "scripts" / "vault_doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(isolated_cwd),
    )
    assert result.returncode == 3, f"expected exit 3, got {result.returncode}: {result.stderr}"
