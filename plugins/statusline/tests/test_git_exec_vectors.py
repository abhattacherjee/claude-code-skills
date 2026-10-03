"""Class sweep: no repo can make the statuslines' git calls run its code (#158).

One test per exec vector found in the sweep (see the README "Security" table). Each runs
the 3-tier statusline and a generated statusline with every git item, and asserts a marker
file the repo's code would create never appears. Each setup first proves, with a plain git
call, that the vector is real.
"""
import os
import subprocess
from pathlib import Path

import pytest

from sltest import REFERENCE
from test_statusline_security import generated, git, git_env, payload, run_script

OLD = ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "--no-optional-locks"]


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def run_both(tmp_path, home, repo, env, bash):
    script = generated(tmp_path, home, "git,git-sync,git-link", bash)
    return [run_script(s, payload(), repo, env, 200, bash) for s in (REFERENCE, script)]


def touch_cmd(marker: Path) -> str:
    return f"sh -c 'touch {marker}; cat'"


def test_submodule_filter_never_runs(tmp_path, home, bash):
    env = git_env(home)
    up = tmp_path / "subup"
    up.mkdir()
    git(up, "init", "-q", "-b", "main", env=env)
    (up / ".gitattributes").write_text("* filter=x\n")
    (up / "f").write_text("one\n")
    git(up, "add", ".", env=env)
    git(up, "commit", "-q", "-m", "i", env=env)
    sup = tmp_path / "super"
    sup.mkdir()
    git(sup, "init", "-q", "-b", "trunk", env=env)
    git(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(up), "sub", env=env)
    git(sup, "commit", "-q", "-m", "add sub", env=env)
    marker = tmp_path / "SUBFILTER"
    git(sup / "sub", "config", "filter.x.clean", touch_cmd(marker), env=env)
    (sup / "sub" / "f").write_text("two\n")
    # Probe: the pre-sweep flags still recurse into the submodule and run its filter.
    subprocess.run(OLD + ["status", "--porcelain"], cwd=str(sup), env=env, capture_output=True)
    assert marker.exists(), "repro is not real"
    marker.unlink()
    for r in run_both(tmp_path, home, sup, env, bash):
        assert r.returncode == 0 and "trunk" in r.stdout, r.stderr
    assert not marker.exists()


def partial_clone(tmp_path, env):
    up = tmp_path / "up"
    up.mkdir()
    git(up, "init", "-q", "-b", "main", env=env)
    git(up, "config", "uploadpack.allowfilter", "true", env=env)
    (up / "a").write_text("hello\n")
    git(up, "add", "a", env=env)
    git(up, "commit", "-q", "-m", "i", env=env)
    pc = tmp_path / "pc"
    git(tmp_path, "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{up}", str(pc), env=env)
    git(pc, "read-tree", "HEAD", env=env)          # index names blobs that are not local
    marker = tmp_path / "LAZYFETCH"
    git(pc, "config", "protocol.ext.allow", "always", env=env)
    git(pc, "remote", "set-url", "origin", f"ext::sh -c touch% {marker}", env=env)
    return pc, marker


def test_partial_clone_lazy_fetch_never_runs_a_transport(tmp_path, home, bash):
    env = git_env(home)
    pc, marker = partial_clone(tmp_path, env)
    subprocess.run(OLD + ["diff", "--numstat"], cwd=str(pc), env=env, capture_output=True)
    assert marker.exists(), "repro is not real"
    marker.unlink()
    for r in run_both(tmp_path, home, pc, env, bash):
        assert r.returncode == 0 and "main" in r.stdout, r.stderr
    assert not marker.exists()


def test_textconv_and_external_diff_never_run(tmp_path, home, bash):
    env = git_env(home)
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk", env=env)
    (repo / ".gitattributes").write_text("*.t diff=tc\n")
    (repo / "a.t").write_text("one\n")
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "i", env=env)
    marker = tmp_path / "DIFFDRIVER"
    git(repo, "config", "diff.tc.textconv", f"sh -c 'touch {marker}; cat \"$0\"'", env=env)
    git(repo, "config", "diff.external", f"sh -c 'touch {marker}'", env=env)
    (repo / "a.t").write_text("two\n")
    subprocess.run(["git", "diff"], cwd=str(repo), env=env, capture_output=True)
    assert marker.exists(), "repro is not real"
    marker.unlink()
    for r in run_both(tmp_path, home, repo, env, bash):
        assert r.returncode == 0 and "trunk" in r.stdout
    assert not marker.exists()


def test_index_hook_never_runs(tmp_path, home, bash):
    env = git_env(home)
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk", env=env)
    (repo / "a").write_text("one\n")
    git(repo, "add", "a", env=env)
    git(repo, "commit", "-q", "-m", "i", env=env)
    marker = tmp_path / "HOOK"
    hook = repo / ".git" / "hooks" / "post-index-change"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    (repo / "a").write_text("two\n")
    subprocess.run(["git", "status"], cwd=str(repo), env=env, capture_output=True)
    assert marker.exists(), "repro is not real"
    marker.unlink()
    for r in run_both(tmp_path, home, repo, env, bash):
        assert r.returncode == 0
    assert not marker.exists()


def test_ext_remote_url_never_runs(tmp_path, home, bash):
    env = git_env(home)
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk", env=env)
    git(repo, "commit", "-q", "--allow-empty", "-m", "i", env=env)
    marker = tmp_path / "EXTURL"
    git(repo, "config", "protocol.ext.allow", "always", env=env)
    git(repo, "remote", "add", "origin", f"ext::sh -c touch% {marker}", env=env)
    for r in run_both(tmp_path, home, repo, env, bash):
        assert r.returncode == 0
    assert not marker.exists()


def test_every_status_and_diff_call_carries_the_sweep_flags(tmp_path, home, bash):
    log = tmp_path / "git.log"
    shim = tmp_path / "shim"
    shim.mkdir()
    real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True).stdout.strip()
    (shim / "git").write_text(f'#!/bin/sh\necho "$GIT_NO_LAZY_FETCH $*" >> "{log}"\nexec "{real}" "$@"\n')
    (shim / "git").chmod(0o755)
    env = git_env(home)
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk", env=env)
    git(repo, "commit", "-q", "--allow-empty", "-m", "i", env=env)
    env["PATH"] = f"{shim}{os.pathsep}{env['PATH']}"
    run_both(tmp_path, home, repo, env, bash)
    calls = log.read_text().splitlines()
    assert any(" status " in c for c in calls) and any(" diff " in c for c in calls)
    for c in calls:
        assert c.startswith("1 --no-pager -c core.fsmonitor=false"), c
        if " status " in c:
            assert "--ignore-submodules=all" in c, c
        if " diff " in c:
            for flag in ("--ignore-submodules=all", "--no-textconv", "--no-ext-diff"):
                assert flag in c, c
