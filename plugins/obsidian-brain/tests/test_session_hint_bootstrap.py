"""Tests for bootstrap-file refresh in obsidian_session_hint hook."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Make the hooks module importable for in-process tests.
_HOOKS_DIR = str(Path(__file__).parent.parent / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)


def _hook_script_path() -> str:
    return str(Path(__file__).parent.parent / "hooks" / "obsidian_session_hint.py")


def _import_hook_module():
    """Import obsidian_session_hint fresh so env vars take effect."""
    if "obsidian_session_hint" in sys.modules:
        return importlib.reload(sys.modules["obsidian_session_hint"])
    return importlib.import_module("obsidian_session_hint")


def test_hook_writes_bootstrap_file(tmp_path):
    """Hook writes the authoritative session_id to the bootstrap file."""
    project_dir = tmp_path / "fake-project"
    project_dir.mkdir()
    secure_dir = tmp_path / ".claude" / "obsidian-brain"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    payload = {
        "cwd": str(project_dir),
        "session_id": "test-sid-aaaaaaaa",
    }
    result = subprocess.run(
        [sys.executable, _hook_script_path()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"hook exited {result.returncode}: {result.stderr}"
    bootstrap_path = secure_dir / "sid-fake-project"
    assert bootstrap_path.exists(), "bootstrap file was not written"
    assert bootstrap_path.read_text(encoding="utf-8").strip() == "test-sid-aaaaaaaa"


def test_hook_handles_missing_session_id(tmp_path):
    """Hook does not crash when stdin JSON omits session_id and does not write bootstrap."""
    project_dir = tmp_path / "proj-nosid"
    project_dir.mkdir()

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    payload = {"cwd": str(project_dir)}  # no session_id
    result = subprocess.run(
        [sys.executable, _hook_script_path()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"hook exited {result.returncode}: {result.stderr}"
    secure_dir = tmp_path / ".claude" / "obsidian-brain"
    bootstrap_path = secure_dir / "sid-proj-nosid"
    assert not bootstrap_path.exists(), "bootstrap should not be written without session_id"


def test_hook_writes_log_line(tmp_path):
    """Hook appends an audit line to ~/.claude/obsidian-brain-hook.log."""
    project_dir = tmp_path / "proj-log"
    project_dir.mkdir()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    payload = {"cwd": str(project_dir), "session_id": "log-sid-bbbb"}
    result = subprocess.run(
        [sys.executable, _hook_script_path()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"hook exited {result.returncode}: {result.stderr}"

    log_path = claude_dir / "obsidian-brain-hook.log"
    assert log_path.exists(), "hook log was not written"
    content = log_path.read_text(encoding="utf-8")
    assert "SessionStart" in content
    assert "proj-log" in content
    assert "log-sid-" in content
    assert "bootstrap_updated=true" in content


def test_hook_log_rotates_when_large(tmp_path):
    """Hook rotates the log file when it exceeds ~100 KB."""
    project_dir = tmp_path / "proj-rotate"
    project_dir.mkdir()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    log_path = claude_dir / "obsidian-brain-hook.log"
    log_path.write_text("x" * (150 * 1024), encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    payload = {"cwd": str(project_dir), "session_id": "rot-sid-cccc"}
    subprocess.run(
        [sys.executable, _hook_script_path()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    rotated = claude_dir / "obsidian-brain-hook.log.1"
    assert rotated.exists(), "log should have been rotated to .log.1"
    assert "rot-sid-" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# In-process unit tests for the helper functions (for coverage).
# ---------------------------------------------------------------------------


def test_bootstrap_prefix_default(monkeypatch):
    """Bootstrap prefix is fixed to the secure directory (env var override removed)."""
    monkeypatch.delenv("OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX", raising=False)
    import obsidian_utils
    expected = os.path.join(os.path.expanduser("~/.claude/obsidian-brain"), "sid-")
    assert obsidian_utils._bootstrap_prefix() == expected


def test_bootstrap_prefix_ignores_env_override(monkeypatch, tmp_path):
    """Env var OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX is no longer honored (C2)."""
    monkeypatch.setenv("OBSIDIAN_BRAIN_BOOTSTRAP_PREFIX", str(tmp_path / "pref-"))
    import obsidian_utils
    expected = os.path.join(os.path.expanduser("~/.claude/obsidian-brain"), "sid-")
    assert obsidian_utils._bootstrap_prefix() == expected


def test_write_bootstrap_atomic_success(monkeypatch, tmp_path):
    secure_dir = str(tmp_path / "secure")
    monkeypatch.setattr("obsidian_utils._SECURE_DIR", secure_dir)
    monkeypatch.setattr("obsidian_utils._BOOTSTRAP_PREFIX", os.path.join(secure_dir, "sid-"))
    mod = _import_hook_module()
    # Re-patch after reload since reload re-executes module-level code
    import obsidian_utils
    monkeypatch.setattr("obsidian_utils._SECURE_DIR", secure_dir)
    monkeypatch.setattr("obsidian_utils._BOOTSTRAP_PREFIX", os.path.join(secure_dir, "sid-"))
    os.makedirs(secure_dir, mode=0o700, exist_ok=True)
    assert mod._write_bootstrap_atomic("proj1", "sid-123") is True
    target = Path(secure_dir) / "sid-proj1"
    assert target.read_text(encoding="utf-8") == "sid-123"


def test_write_bootstrap_atomic_failure(monkeypatch, tmp_path, capsys):
    # Point to an unwritable location inside a file (not a dir) to force OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    secure_dir = str(blocker / "nested")
    monkeypatch.setattr("obsidian_utils._SECURE_DIR", secure_dir)
    monkeypatch.setattr("obsidian_utils._BOOTSTRAP_PREFIX", os.path.join(secure_dir, "sid-"))
    mod = _import_hook_module()
    import obsidian_utils
    monkeypatch.setattr("obsidian_utils._SECURE_DIR", secure_dir)
    monkeypatch.setattr("obsidian_utils._BOOTSTRAP_PREFIX", os.path.join(secure_dir, "sid-"))
    assert mod._write_bootstrap_atomic("proj2", "sid-456") is False
    err = capsys.readouterr().err
    assert "bootstrap write failed" in err or "ensure_secure_dir" in err.lower() or "not a directory" in err.lower()


def test_append_hook_log_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _import_hook_module()
    mod._append_hook_log("projA", "sid-abcdefgh", True)
    log_path = tmp_path / ".claude" / "obsidian-brain-hook.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "SessionStart" in content
    assert "project=projA" in content
    assert "sid=sid-abcd" in content  # truncated to 8 chars
    assert "bootstrap_updated=true" in content


def test_append_hook_log_false_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _import_hook_module()
    mod._append_hook_log("projB", "", False)
    log_path = tmp_path / ".claude" / "obsidian-brain-hook.log"
    content = log_path.read_text(encoding="utf-8")
    assert "sid=unknown" in content
    assert "bootstrap_updated=false" in content


def test_append_hook_log_rotates(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    log_path = claude_dir / "obsidian-brain-hook.log"
    log_path.write_text("y" * (150 * 1024), encoding="utf-8")
    mod = _import_hook_module()
    mod._append_hook_log("projC", "sid-rotate1", True)
    assert (claude_dir / "obsidian-brain-hook.log.1").exists()
    assert "projC" in log_path.read_text(encoding="utf-8")


def test_append_hook_log_handles_oserror(monkeypatch, tmp_path, capsys):
    # Point HOME at a non-writable file so os.makedirs fails.
    blocker = tmp_path / "notadir"
    blocker.write_text("blocker", encoding="utf-8")
    monkeypatch.setenv("HOME", str(blocker))
    mod = _import_hook_module()
    mod._append_hook_log("projD", "sid-xyz", False)
    err = capsys.readouterr().err
    assert "hook log append failed" in err
