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
    (shim / "git").write_text(f'#!/bin/sh\necho "$GIT_NO_LAZY_FETCH $GIT_ALLOW_PROTOCOL $*" >> "{log}"\nexec "{real}" "$@"\n')
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
        assert c.startswith("1 none --no-pager -c core.fsmonitor=false"), c
        assert "-c protocol.allow=never" in c, c
        if " status " in c:
            assert "--ignore-submodules=all" in c, c
        if " diff " in c:
            for flag in ("--ignore-submodules=all", "--no-textconv", "--no-ext-diff"):
                assert flag in c, c


def old_git_copy(script: Path, dest: Path) -> Path:
    """The script as git < 2.44 would run it, with unsafe_repo bypassed: no
    GIT_NO_LAZY_FETCH, and unsafe_repo always says "safe"."""
    text = script.read_text()
    assert text.count("GIT_NO_LAZY_FETCH=1 ") == 1
    text = text.replace("GIT_NO_LAZY_FETCH=1 ", "")
    text = text.replace("\n_git() {", "\nunsafe_repo() { return 1; }\n_git() {", 1)
    # unsafe_repo is defined after _git; redefine it again after its own definition.
    i = text.index("unsafe_repo() {\n")
    j = text.index("\n}\n", i) + 3
    text = text[:j] + "unsafe_repo() { return 1; }\n" + text[j:]
    dest.write_text(text)
    return dest


@pytest.mark.parametrize("transport", ["ext", "ssh"])
def test_no_transport_starts_even_on_old_git_without_unsafe_repo(tmp_path, home, bash, transport):
    env = git_env(home)
    env.pop("GIT_NO_LAZY_FETCH", None)
    pc, marker = partial_clone(tmp_path, env)
    if transport == "ssh":
        # protocol.<name>.allow in the repo's config beats -c protocol.allow=never.
        git(pc, "config", "protocol.ssh.allow", "always", env=env)
        git(pc, "config", "core.sshCommand", f"sh -c 'touch {marker}' --", env=env)
        git(pc, "remote", "set-url", "origin", "ssh://host/x", env=env)
    probe = subprocess.run(["git", "-c", "protocol.allow=never", "diff", "--numstat"], cwd=str(pc),
                           env=env, capture_output=True)
    assert marker.exists(), "repro is not real: protocol.allow=never alone should not stop it"
    marker.unlink()
    gen = generated(tmp_path, home, "git", bash)
    for s in (old_git_copy(REFERENCE, tmp_path / "ref-old.sh"), old_git_copy(gen, tmp_path / "gen-old.sh")):
        r = run_script(s, payload(), pc, env, 200, bash)
        assert r.returncode == 0 and "main" in r.stdout, r.stderr
        assert not marker.exists(), s.name
