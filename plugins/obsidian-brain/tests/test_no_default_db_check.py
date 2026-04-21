"""Regression tests for scripts/ci-checks/no-default-db.py (GH #46 guard)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci-checks" / "no-default-db.py"


def _run(tests_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(tests_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_tests_dir_is_clean():
    """The current tests/ directory must pass the guard."""
    result = _run(REPO_ROOT / "tests")
    assert result.returncode == 0, (
        f"Real tests/ has violations:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.parametrize(
    "func_call,func_name",
    [
        ("vault_index.ensure_index(str(tmp_path), ['x'])", "ensure_index"),
        ("vault_index.rebuild_index(str(tmp_path), ['x'])", "rebuild_index"),
        (
            "open_item_dedup.deep_analysis_pipeline(\n"
            "        ['x'], '[]', 'out.json', str(tmp_path),\n"
            "        'claude-sessions', 'claude-insights')",
            "deep_analysis_pipeline",
        ),
    ],
)
def test_detects_bare_guarded_call(tmp_path, func_call, func_name):
    fixture = tmp_path / "test_bad.py"
    fixture.write_text(
        "import mod\n"
        "def test_bad(tmp_path):\n"
        f"    {func_call}\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert func_name in result.stdout
    assert "1 violation(s)" in result.stderr


def test_accepts_db_path_kwarg(tmp_path):
    fixture = tmp_path / "test_good.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_good(tmp_path):\n"
        "    vault_index.ensure_index(\n"
        "        str(tmp_path), ['claude-sessions'],\n"
        "        db_path=str(tmp_path / 'x.db'))\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_accepts_kwargs_expansion_but_warns(tmp_path):
    """Callers forwarding **kwargs can't be statically verified; allow with warning."""
    fixture = tmp_path / "test_kwargs.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_fwd(tmp_path, **extra):\n"
        "    vault_index.ensure_index(str(tmp_path), ['x'], **extra)\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "warning:" in result.stderr
    assert "**kwargs" in result.stderr


def test_noqa_suppresses_violation_single_line(tmp_path):
    fixture = tmp_path / "test_mocked.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_m(tmp_path):\n"
        "    vault_index.ensure_index(str(tmp_path), ['x'])  # noqa: no-default-db\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_noqa_suppresses_violation_multiline_closing_paren(tmp_path):
    """noqa marker on the closing paren line must suppress a multi-line call."""
    fixture = tmp_path / "test_multiline.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_m(tmp_path):\n"
        "    vault_index.ensure_index(\n"
        "        str(tmp_path),\n"
        "        ['x'],\n"
        "    )  # noqa: no-default-db\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, (
        f"Multi-line noqa should suppress:\n{result.stdout}\n{result.stderr}"
    )


def test_noqa_suppresses_violation_multiline_inner_line(tmp_path):
    """noqa marker on any line within the call span must suppress."""
    fixture = tmp_path / "test_multiline2.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_m(tmp_path):\n"
        "    vault_index.ensure_index(  # noqa: no-default-db\n"
        "        str(tmp_path),\n"
        "        ['x'],\n"
        "    )\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, (
        f"Inline-noqa should suppress:\n{result.stdout}\n{result.stderr}"
    )


def test_detects_violation_inside_class_method(tmp_path):
    """ast.walk must descend into class bodies and nested functions."""
    fixture = tmp_path / "test_nested.py"
    fixture.write_text(
        "import vault_index\n"
        "class TestThing:\n"
        "    def test_x(self, tmp_path):\n"
        "        with open('/dev/null'):\n"
        "            vault_index.ensure_index(str(tmp_path), ['x'])\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "ensure_index" in result.stdout


def test_counts_multiple_violations_in_one_file(tmp_path):
    fixture = tmp_path / "test_many.py"
    fixture.write_text(
        "import vault_index\n"
        "def test_a(tmp_path):\n"
        "    vault_index.ensure_index(str(tmp_path), ['x'])\n"
        "def test_b(tmp_path):\n"
        "    vault_index.rebuild_index(str(tmp_path), ['x'])\n"
        "def test_c(tmp_path):\n"
        "    vault_index.ensure_index(str(tmp_path), ['x'])\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert result.stdout.count("missing db_path=") == 3
    assert "3 violation(s)" in result.stderr


def test_ignores_non_target_functions(tmp_path):
    fixture = tmp_path / "test_other.py"
    fixture.write_text(
        "def some_helper(x): pass\n"
        "def test_x():\n"
        "    some_helper('x')\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0


def test_syntax_error_exits_two(tmp_path):
    """Broken Python source returns exit 2 (script malfunction), not exit 1 (violation)."""
    fixture = tmp_path / "test_broken.py"
    fixture.write_text("def x(:\n    pass\n")
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "SyntaxError" in result.stderr


def test_missing_tests_dir_exits_two(tmp_path):
    result = _run(tmp_path / "nonexistent")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_unreadable_file_exits_two(tmp_path):
    """Non-UTF-8 bytes in a test file surface as exit 2, not a bare traceback."""
    fixture = tmp_path / "test_binary.py"
    fixture.write_bytes(b"\xff\xfe\x00not valid utf-8 \xc3\x28")
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "cannot read" in result.stderr


def test_skips_pycache(tmp_path):
    """__pycache__ directories must be skipped during audit."""
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "test_compiled.py").write_text(
        "import x\n"
        "def test_y(tmp_path):\n"
        "    x.ensure_index(str(tmp_path), ['x'])\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0
