"""Repo-controlled filter drivers never run from the statuslines (#158, I8 follow-up).

`git config --local` does not follow include.path and ignores worktree config, so the
check reads every filter.* key with --includes --show-scope and treats any scope other
than global or system as repo-controlled. If git config itself fails, counts are skipped.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

from sltest import REFERENCE
from test_statusline_security import generated, git, git_env, payload, run_script


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def tracked_repo(root: Path, env) -> Path:
    """A repo on branch 'trunk' whose committed file f is filtered by attribute x."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "trunk", env=env)
    (repo / ".gitattributes").write_text("* filter=x\n")
    (repo / "f").write_text("one\n")
    git(repo, "add", "f", ".gitattributes", env=env)
    git(repo, "commit", "-q", "-m", "init", env=env)
    return repo


def evil_filter(root: Path):
    marker = root / "FILTER-RAN"
    return marker, f"sh -c 'touch {marker}; cat'"


def modify_and_probe(repo: Path, marker: Path, env):
    """Modify the tracked file, and prove a plain git status really runs the filter."""
    (repo / "f").write_text("two\n")
    subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), env=env, capture_output=True)
    assert marker.exists(), "repro is not real: plain git status did not run the filter"
    marker.unlink()


def scripts(tmp_path, home, bash):
    return [REFERENCE, generated(tmp_path, home, "git", bash)]


def run_all(tmp_path, home, repo, env, bash):
    return [run_script(s, payload(), repo, env, 200, bash) for s in scripts(tmp_path, home, bash)]


def test_filter_reached_through_include_path_never_runs(tmp_path, home, bash):
    env = git_env(home)
    repo = tracked_repo(tmp_path, env)
    marker, cmd = evil_filter(tmp_path)
    inc = tmp_path / "elsewhere.cfg"
    # Quoted: an unquoted ';' would start a comment in a git config file.
    inc.write_text(f'[filter "x"]\n\tclean = "{cmd}"\n')
    git(repo, "config", "include.path", str(inc), env=env)
    local = subprocess.run(["git", "config", "--local", "--get-regexp", r"^filter\."], cwd=str(repo),
                           env=env, capture_output=True, text=True).stdout
    assert local == ""                       # the old check saw nothing
    modify_and_probe(repo, marker, env)
    for r in run_all(tmp_path, home, repo, env, bash):
        assert r.returncode == 0 and "trunk" in r.stdout, r.stderr
        assert "~1" not in r.stdout
    assert not marker.exists()


def test_worktree_scope_filter_never_runs(tmp_path, home, bash):
    env = git_env(home)
    repo = tracked_repo(tmp_path, env)
    marker, cmd = evil_filter(tmp_path)
    git(repo, "config", "extensions.worktreeConfig", "true", env=env)
    git(repo, "config", "--worktree", "filter.x.clean", cmd, env=env)
    modify_and_probe(repo, marker, env)
    for r in run_all(tmp_path, home, repo, env, bash):
        assert r.returncode == 0 and "trunk" in r.stdout, r.stderr
    assert not marker.exists()


def test_global_filter_only_keeps_counts(tmp_path, home, bash):
    env = git_env(home)
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text('[filter "x"]\n\tclean = cat\n')
    env["GIT_CONFIG_GLOBAL"] = str(gcfg)
    repo = tracked_repo(tmp_path, env)
    (repo / "f").write_text("two\n")
    ref, gen = run_all(tmp_path, home, repo, env, bash)
    assert "~1" in ref.stdout, ref.stdout
    assert "~1" in gen.stdout, gen.stdout


def test_failing_git_config_skips_counts(tmp_path, home, bash):
    env = git_env(home)
    repo = tracked_repo(tmp_path, env)
    (repo / "f").write_text("two\n")
    real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True,
                          env=env).stdout.strip()
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text(f'#!/bin/sh\ncase " $* " in *" config "*) exit 128;; esac\n'
                              f'exec "{real}" "$@"\n')
    (shim / "git").chmod(0o755)
    env["PATH"] = f"{shim}{os.pathsep}{env['PATH']}"
    for r in run_all(tmp_path, home, repo, env, bash):
        assert r.returncode == 0 and "trunk" in r.stdout, r.stderr
        assert "~1" not in r.stdout, r.stdout
