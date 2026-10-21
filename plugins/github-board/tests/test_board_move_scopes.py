"""board-move.sh: an unreadable token-scope line is a warning; a listed scope without project is exit 3."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gbtest import install_fake_gh

MOVE = (Path(__file__).resolve().parent.parent / "skills" / "move-card" / "scripts"
        / "board-move.sh")

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def _run(tmp_path, auth_out, *args):
    routes = [{"match": ["auth", "status"], "stdout": auth_out},
              {"match": ["graphql"], "stderr": "stop here", "rc": 1}]
    env = dict(os.environ, **install_fake_gh(tmp_path / "bin", routes, tmp_path / "gh.log"))
    return subprocess.run(["bash", str(MOVE), "--list-status", "--repo", "o/r", *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_no_scopes_line_warns_and_continues(tmp_path):
    done = _run(tmp_path, "github.com\n  - Logged in to github.com account x (GH_TOKEN)\n")
    assert done.returncode != 3, done.stderr
    assert "could not read OAuth scopes" in done.stderr


def test_scopes_none_warns_and_continues(tmp_path):
    done = _run(tmp_path, "  - Token scopes: none\n")
    assert done.returncode != 3, done.stderr


def test_listed_scopes_without_project_still_exit_3(tmp_path):
    done = _run(tmp_path, "  - Token scopes: 'repo', 'read:org'\n")
    assert done.returncode == 3
    assert "lacks a GitHub Projects scope" in done.stderr
