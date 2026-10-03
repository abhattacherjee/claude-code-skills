"""Security fixes in the scripts the plugin ships (#158, review findings 1-4).

1. create's git cache lives in ${XDG_CACHE_HOME:-~/.cache}/claude-statusline/ (mode 700),
   one file per working directory, never followed through a symlink; not a shared /tmp file.
2. Values printed with echo -e are stripped of control characters and backslashes, and the
   OSC 8 link is emitted only for http(s) remotes.
3. install's statusline uses constant printf formats ('%' in a name prints as '%') and
   strips control characters from the directory, branch and model.
4. Both run git with core.fsmonitor and the untracked cache off and without optional locks,
   so a repo's config cannot run a program on every prompt through them.

The 3-tier statusline's output is compared byte for byte against golden output recorded
from the script before these fixes (tests/fixtures/statusline-golden.json), so the fixes
keep its behaviour for ordinary input.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from sltest import GENERATE, MARKER, REFERENCE

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "statusline-golden.json"
ESC = "\x1b"

MODELS = ["Opus 4.6", "Claude Sonnet 4.5 (1M context)"]
DIRS = ["/tmp/my-project", "/x/a-very-long-directory-name-for-testing"]
PCTS = [0, 42.5, 67, 93]
COLS = [30, 45, 80, 200]
REPOS = ["none", "develop-clean", "long-dirty-ahead"]


def git_env(home: Path) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CLAUDE"))}
    e.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
             GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
             XDG_CACHE_HOME=str(home / ".cache"), TMPDIR=str(home))
    e.pop("TMUX", None)
    e.pop("COLUMNS", None)
    return e


def git(cwd, *args, env):
    subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True, capture_output=True)


def make_repos(root: Path, env) -> dict:
    """Three working dirs: no git, a clean 'develop' with no upstream, and a long dirty
    branch one commit ahead of its upstream."""
    out = {"none": root / "plain"}
    out["none"].mkdir(parents=True)
    a = root / "develop"
    a.mkdir()
    git(a, "init", "-q", "-b", "develop", env=env)
    git(a, "commit", "-q", "--allow-empty", "-m", "init", env=env)
    out["develop-clean"] = a
    up = root / "upstream"
    up.mkdir()
    git(up, "init", "-q", "-b", "main", env=env)
    git(up, "commit", "-q", "--allow-empty", "-m", "init", env=env)
    b = root / "clone"
    git(root, "clone", "-q", str(up), str(b), env=env)
    git(b, "checkout", "-q", "-b", "feature/story-11.13-prompt-dedup-restructure", "--track", "origin/main", env=env)
    git(b, "commit", "-q", "--allow-empty", "-m", "ahead", env=env)
    (b / "dirty1").write_text("x")
    (b / "dirty2").write_text("y")
    out["long-dirty-ahead"] = b
    return out


def run_script(script: Path, payload: dict, cwd: Path, env, cols=None, bash="bash"):
    e = dict(env)
    if cols is not None:
        e["COLUMNS"] = str(cols)
    return subprocess.run([bash, str(script)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(cwd), env=e, timeout=30)


def payload(model="Opus 4.6", d="/tmp/my-project", pct=42):
    return {"model": {"display_name": model}, "workspace": {"current_dir": d},
            "context_window": {"used_percentage": pct}}


def cases():
    for repo in REPOS:
        for cols in COLS:
            for i, pct in enumerate(PCTS):
                yield repo, cols, MODELS[i % 2], DIRS[(i // 2) % 2], pct


def case_key(repo, cols, model, d, pct):
    return f"{repo}|{cols}|{model}|{d}|{pct}"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def repos(tmp_path, home):
    return make_repos(tmp_path / "repos", git_env(home))


# ── 3: constant formats, same bytes as before for ordinary input ────────────

def test_three_tier_output_matches_the_golden_bytes(home, repos, bash):
    golden = json.loads(GOLDEN.read_text())
    env = git_env(home)
    got = {}
    for repo, cols, model, d, pct in cases():
        r = run_script(REFERENCE, payload(model, d, pct), repos[repo], env, cols, bash)
        assert r.returncode == 0, r.stderr
        got[case_key(repo, cols, model, d, pct)] = r.stdout
    assert len(golden) == len(got) == 48
    assert got == golden


@pytest.mark.parametrize("cols", [45, 200])     # below 40 columns the directory is not shown
def test_percent_in_a_directory_name_is_printed_as_is(home, repos, bash, cols):
    r = run_script(REFERENCE, payload(d="/x/100%done %s %n"), repos["none"], git_env(home), cols, bash)
    assert r.returncode == 0
    assert "100%done %s %n" in r.stdout


@pytest.mark.parametrize("cols", [30, 45, 200])
def test_control_characters_are_stripped_from_model_and_dir(home, repos, bash, cols):
    evil = "Op\x1b]0;pwned\x07us\\033[5m"
    r = run_script(REFERENCE, payload(model=evil, d="/x/d\x1b[2Jir"), repos["none"], git_env(home), cols, bash)
    assert r.returncode == 0
    assert "\x07" not in r.stdout
    assert f"{ESC}]0" not in r.stdout and f"{ESC}[2J" not in r.stdout and f"{ESC}[5m" not in r.stdout
    assert "Op" in r.stdout


@pytest.mark.parametrize("name", ["my project", "it's here", 'say "hi"'])
def test_directory_names_with_spaces_and_quotes_are_shown_whole(home, repos, bash, name):
    r = run_script(REFERENCE, payload(d=f"/x/{name}"), repos["none"], git_env(home), 200, bash)
    assert r.returncode == 0
    assert name in r.stdout


# ── 4: git cannot run a repo's fsmonitor hook ───────────────────────────────

def hostile_repo(root: Path, env) -> tuple:
    repo = root / "hostile"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main", env=env)
    git(repo, "commit", "-q", "--allow-empty", "-m", "init", env=env)
    (repo / "f").write_text("x")
    pwned = root / "PWNED"
    hook = root / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{pwned}'\nexit 1\n")
    hook.chmod(0o755)
    git(repo, "config", "core.fsmonitor", str(hook), env=env)
    # The probe: plain git status does run the hook (so the test can see a regression).
    subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), env=env, capture_output=True)
    assert pwned.exists()
    pwned.unlink()
    return repo, pwned


def test_three_tier_statusline_does_not_run_fsmonitor(tmp_path, home, bash):
    env = git_env(home)
    repo, pwned = hostile_repo(tmp_path, env)
    r = run_script(REFERENCE, payload(), repo, env, 200, bash)
    assert r.returncode == 0 and "main" in r.stdout
    assert not pwned.exists()


def generated(tmp_path, home, items, bash="bash"):
    out = tmp_path / "gen.sh"
    env = git_env(home)
    r = subprocess.run([bash, str(GENERATE), "--items", items, "--output", str(out)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    return out


def test_generated_git_items_do_not_run_fsmonitor(tmp_path, home, bash):
    env = git_env(home)
    repo, pwned = hostile_repo(tmp_path, env)
    script = generated(tmp_path, home, "model,git,git-sync,git-link", bash)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert r.returncode == 0 and "main" in r.stdout
    assert not pwned.exists()


def test_every_git_call_is_hardened(tmp_path, home, repos, bash):
    # A git on PATH that logs each argv, then runs the real git.
    log = tmp_path / "git.log"
    shim = tmp_path / "shim"
    shim.mkdir()
    real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True).stdout.strip()
    (shim / "git").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
    (shim / "git").chmod(0o755)
    env = git_env(home)
    env["PATH"] = f"{shim}{os.pathsep}{env['PATH']}"
    script = generated(tmp_path, home, "git,git-sync,git-link", bash)
    for s in (REFERENCE, script):
        assert run_script(s, payload(), repos["long-dirty-ahead"], env, 200, bash).returncode == 0
    calls = log.read_text().splitlines()
    assert len(calls) >= 10
    for c in calls:
        assert c.startswith("-c core.fsmonitor=false -c core.untrackedCache=false --no-optional-locks "), c


# ── 1: the git cache ────────────────────────────────────────────────────────

def test_generated_script_has_no_tmp_paths(tmp_path, home):
    script = generated(tmp_path, home, "git,git-sync")
    assert "/tmp" not in script.read_text()


def test_git_cache_is_private_and_per_directory(tmp_path, home, repos, bash):
    env = git_env(home)
    script = generated(tmp_path, home, "git", bash)
    a = run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    b = run_script(script, payload(), repos["long-dirty-ahead"], env, bash=bash)
    assert "develop" in a.stdout
    assert "feature/story-11.13-prompt-dedup-restructure" in b.stdout   # not develop's cache
    cache = home / ".cache" / "claude-statusline"
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    assert len(list(cache.iterdir())) == 2


def test_git_cache_symlink_is_never_followed(tmp_path, home, repos, bash):
    env = git_env(home)
    script = generated(tmp_path, home, "git", bash)
    run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    cache = home / ".cache" / "claude-statusline"
    [entry] = list(cache.iterdir())
    victim = tmp_path / "victim"
    victim.write_text("keep me\n")
    entry.unlink()
    entry.symlink_to(victim)
    r = run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    assert "develop" in r.stdout
    assert victim.read_text() == "keep me\n" and entry.is_symlink()


def test_git_cache_dir_symlink_is_never_followed(tmp_path, home, repos, bash):
    env = git_env(home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / ".cache").mkdir()
    (home / ".cache" / "claude-statusline").symlink_to(elsewhere)
    script = generated(tmp_path, home, "git", bash)
    r = run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    assert "develop" in r.stdout
    assert list(elsewhere.iterdir()) == []


# ── 2: escape injection in create's output ──────────────────────────────────

def test_generated_output_strips_control_characters(tmp_path, home, repos, bash):
    env = git_env(home)
    script = generated(tmp_path, home, "model,dir,session-id,style,agent,worktree", bash)
    p = payload(model="Op\x1b]0;pwned\x07us", d="/x/d\\033[2Jir")
    p.update(session_id="ab\x1b[5mcdefgh", output_style={"name": "s\\a"},
             agent={"name": "ag\x1b[8m"}, worktree={"name": "w\x07t"})
    r = run_script(script, p, repos["none"], env, bash=bash)
    assert r.returncode == 0
    for bad in (f"{ESC}]0", "\x07", f"{ESC}[2J", f"{ESC}[5m", f"{ESC}[8m"):
        assert bad not in r.stdout, repr(bad)
    assert "Op" in r.stdout


def test_git_link_only_for_http_remotes(tmp_path, home, repos, bash):
    env = git_env(home)
    repo = repos["develop-clean"]
    script = generated(tmp_path, home, "git-link", bash)
    git(repo, "remote", "add", "origin", "https://github.com/octo/repo.git", env=env)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert f"{ESC}]8;;https://github.com/octo/repo{ESC}" in r.stdout.replace("\x07", ESC)
    git(repo, "remote", "set-url", "origin", "ext::sh -c touch% /tmp/x", env=env)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert f"{ESC}]8" not in r.stdout
    git(repo, "remote", "set-url", "origin", "https://h/\x1b]8;;evil\x07x", env=env)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert "evil\x07" not in r.stdout and r.stdout.count(f"{ESC}]8;;") <= 2


# ── numbers from the session JSON never reach shell arithmetic unfiltered ───

def _arith_payload(marker):
    evil = f"a[$(touch {marker})]"
    p = payload()
    p["context_window"]["used_percentage"] = evil
    p["cost"] = {"total_duration_ms": evil, "total_api_duration_ms": evil,
                 "total_lines_added": evil, "total_lines_removed": evil}
    return p


@pytest.mark.parametrize("cols", [30, 45, 200])
def test_three_tier_does_not_evaluate_a_crafted_percentage(tmp_path, home, repos, bash, cols):
    marker = tmp_path / "ARITH"
    r = run_script(REFERENCE, _arith_payload(marker), repos["none"], git_env(home), cols, bash)
    assert not marker.exists(), r.stderr


def test_generated_script_does_not_evaluate_crafted_numbers(tmp_path, home, repos, bash):
    marker = tmp_path / "ARITH"
    script = generated(tmp_path, home, "context-bar,context-pct,duration,api-duration,lines-changed", bash)
    r = run_script(script, _arith_payload(marker), repos["none"], git_env(home), bash=bash)
    assert not marker.exists(), r.stderr


@pytest.mark.parametrize("pct", [1e30, "99999999999999999999999", "461168601842738790", 250, -5])
@pytest.mark.parametrize("cols", [30, 45, 200])
def test_three_tier_survives_an_out_of_range_percentage(home, repos, bash, pct, cols):
    # Before: a value whose product with the bar width overflows 64 bits gave a negative
    # fill, so the bar loop ran for billions of steps on every prompt (461168601842738790
    # x 25 > 2**63).
    r = run_script(REFERENCE, payload(pct=pct), repos["none"], git_env(home), cols, bash)
    assert r.returncode == 0 and "🧠" in r.stdout


@pytest.mark.parametrize("pct", [1e30, "99999999999999999999999", "461168601842738800", 250, -5])
def test_generated_context_bar_survives_an_out_of_range_percentage(tmp_path, home, repos, bash, pct):
    script = generated(tmp_path, home, "context-bar,duration", bash)
    p = payload(pct=pct)
    p["cost"] = {"total_duration_ms": "9300000000000000000"}     # > 2**63
    r = run_script(script, p, repos["none"], git_env(home), bash=bash)
    assert r.returncode == 0 and ("█" in r.stdout or "░" in r.stdout)
    assert "⏱️ -" not in r.stdout          # a duration past 2**63 must not wrap to negative


def test_recipes_doc_teaches_the_safe_patterns():
    import re
    doc = (REFERENCE.parent.parent.parent / "create" / "references" / "item-recipes.md").read_text()
    assert "/tmp" not in doc
    code = "\n".join(re.findall(r"```bash\n(.*?)```", doc, re.S))
    for line in code.splitlines():
        if line.lstrip().startswith(("#", "_git()")):
            continue
        assert not re.search(r"(?<![\w-])git\s", line), line
        assert "printf '%b' \"" not in line or "${" not in line, line


def test_git_cache_from_the_future_is_not_trusted(tmp_path, home, repos, bash):
    # A timestamp ahead of the clock (the clock was set back) must not count as fresh, or
    # the cached branch would be shown until the clock caught up.
    env = git_env(home)
    script = generated(tmp_path, home, "git", bash)
    run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    [entry] = list((home / ".cache" / "claude-statusline").iterdir())
    import time
    entry.write_text(f"{int(time.time()) + 3600}\nstale-branch|0|0|0|0\n")
    r = run_script(script, payload(), repos["develop-clean"], env, bash=bash)
    assert "develop" in r.stdout and "stale-branch" not in r.stdout
