"""Tests for scripts/test-dev-skill.sh — verify it syncs the right files.

The script is critical for local plugin testing: it copies the dev
working tree into the installed plugin cache so the next CC session
runs the dev code instead of the released version. Historically it
only copied hooks/ and skills/, leaving scripts/vault_doctor.py and
scripts/vault_doctor_checks/*.py stale — so newly-added vault_doctor
check modules wouldn't show up in /vault-doctor invocations even
after /dev-test install.

These tests exercise the install branch in an isolated HOME + REPO
so they don't touch the real ~/.claude/ cache.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test-dev-skill.sh"


def _stage_repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout the script can install from."""
    repo = tmp_path / "repo"
    (repo / "hooks").mkdir(parents=True)
    (repo / "hooks" / "obsidian_utils.py").write_text("# fake hook\n")

    (repo / "skills" / "test-skill").mkdir(parents=True)
    (repo / "skills" / "test-skill" / "SKILL.md").write_text("# fake skill\n")

    (repo / "scripts" / "vault_doctor_checks").mkdir(parents=True)
    (repo / "scripts" / "vault_doctor.py").write_text("# fake dispatcher\n")
    (repo / "scripts" / "vault_doctor_checks" / "__init__.py").write_text("")
    (repo / "scripts" / "vault_doctor_checks" / "snapshot_integrity.py").write_text(
        "# new check module from feature branch\n"
    )
    (repo / "scripts" / "vault_doctor_checks" / "snapshot_migration.py").write_text(
        "# new check module from feature branch\n"
    )

    # Copy the actual script into the staged repo so it can compute its own
    # REPO_ROOT correctly via $(dirname "$0")/..
    (repo / "scripts" / "test-dev-skill.sh").write_bytes(SCRIPT_PATH.read_bytes())
    (repo / "scripts" / "test-dev-skill.sh").chmod(0o755)
    return repo


def _stage_cache(tmp_path: Path) -> Path:
    """Create a fake $HOME/.claude/plugins/cache layout matching the released version."""
    home = tmp_path / "home"
    cache_base = home / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain"
    cache_dir = cache_base / "2.3.0"
    (cache_dir / "hooks").mkdir(parents=True)
    (cache_dir / "hooks" / "obsidian_utils.py").write_text("# released hook (will be overwritten)\n")
    (cache_dir / "skills" / "test-skill").mkdir(parents=True)
    (cache_dir / "skills" / "test-skill" / "SKILL.md").write_text("# released skill\n")
    (cache_dir / "scripts" / "vault_doctor_checks").mkdir(parents=True)
    (cache_dir / "scripts" / "vault_doctor.py").write_text("# released dispatcher\n")
    (cache_dir / "scripts" / "vault_doctor_checks" / "__init__.py").write_text("")
    (cache_dir / "scripts" / "vault_doctor_checks" / "source_sessions.py").write_text(
        "# released check that's still in repo\n"
    )
    return home


def _run_install(tmp_path: Path) -> subprocess.CompletedProcess:
    repo = _stage_repo(tmp_path)
    home = _stage_cache(tmp_path)
    env = {
        **os.environ,
        "HOME": str(home),
        # Defang the security-test invocation so it doesn't hit the real test suite.
        "PATH": os.environ.get("PATH", ""),
    }
    return subprocess.run(
        ["bash", str(repo / "scripts" / "test-dev-skill.sh"), "install"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_install_copies_hooks(tmp_path: Path) -> None:
    proc = _run_install(tmp_path)
    assert proc.returncode == 0, f"install failed: {proc.stderr}"
    cache_hook = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0" / "hooks" / "obsidian_utils.py"
    assert "# fake hook" in cache_hook.read_text(encoding="utf-8")


def test_install_copies_skills(tmp_path: Path) -> None:
    proc = _run_install(tmp_path)
    assert proc.returncode == 0
    cache_skill = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0" / "skills" / "test-skill" / "SKILL.md"
    assert "# fake skill" in cache_skill.read_text(encoding="utf-8")


def test_install_copies_vault_doctor_dispatcher(tmp_path: Path) -> None:
    """Regression: scripts/vault_doctor.py must be synced (was missing)."""
    proc = _run_install(tmp_path)
    assert proc.returncode == 0
    cache_vd = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0" / "scripts" / "vault_doctor.py"
    assert cache_vd.is_file()
    assert "# fake dispatcher" in cache_vd.read_text(encoding="utf-8")


def test_install_copies_new_check_modules(tmp_path: Path) -> None:
    """Regression: new vault_doctor check modules added on feature branches
    must show up in the cache so /vault-doctor --check <name> works without
    a release. This was the original symptom that exposed the bug."""
    proc = _run_install(tmp_path)
    assert proc.returncode == 0, f"install failed: {proc.stderr}"
    cache_checks = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0" / "scripts" / "vault_doctor_checks"
    for new_module in ("snapshot_integrity.py", "snapshot_migration.py"):
        target = cache_checks / new_module
        assert target.is_file(), f"{new_module} not synced to cache"
        assert "# new check module from feature branch" in target.read_text(encoding="utf-8")


def test_install_preserves_existing_check_modules(tmp_path: Path) -> None:
    """Existing modules in the cache must remain after install (not deleted by sync)."""
    proc = _run_install(tmp_path)
    assert proc.returncode == 0
    cache_checks = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0" / "scripts" / "vault_doctor_checks"
    # source_sessions.py was in the released cache. The repo doesn't have it
    # (we only staged snapshot_*), so it should still be there post-install
    # — sync must be additive/overwrite, never delete.
    assert (cache_checks / "source_sessions.py").is_file()


def test_install_creates_backup_before_writing(tmp_path: Path) -> None:
    """The install branch backs up the cache to <version>.bak before mutating."""
    proc = _run_install(tmp_path)
    assert proc.returncode == 0
    backup_dir = tmp_path / "home" / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0.bak"
    assert backup_dir.is_dir()
    # Backup retains the released hook content (not the fake repo content).
    backup_hook = backup_dir / "hooks" / "obsidian_utils.py"
    assert "# released hook" in backup_hook.read_text(encoding="utf-8")


def test_install_refuses_when_backup_already_exists(tmp_path: Path) -> None:
    """Safety: don't overwrite an existing backup — user must `restore` first."""
    repo = _stage_repo(tmp_path)
    home = _stage_cache(tmp_path)
    # Pre-create the backup
    backup = home / ".claude" / "plugins" / "cache" / "claude-code-skills" / "obsidian-brain" / "2.3.0.bak"
    backup.mkdir(parents=True)
    (backup / "marker").write_text("pre-existing")

    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "test-dev-skill.sh"), "install"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode != 0, "install should refuse when backup exists"
    assert "Backup already exists" in proc.stdout
    # Existing backup untouched
    assert (backup / "marker").read_text() == "pre-existing"
