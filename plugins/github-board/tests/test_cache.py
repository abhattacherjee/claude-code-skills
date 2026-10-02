"""Metadata cache (#146): 7-day reuse, stale-id refetch once, --no-cache, unwritable dir."""
import json
import os
import subprocess
import sys
import time

import pytest

from gbtest import LIB, load_lib, load_weekly_focus

PROJECT_KEY = "plan-week-octo-user-project-Weekly Focus"


@pytest.fixture
def gbc():
    return load_lib()


def test_fresh_entry_is_reused(gbc):
    assert gbc.cache_put("k", {"a": 1})
    assert gbc.cache_get("k") == {"a": 1}


def test_entry_older_than_7_days_is_a_miss(gbc):
    gbc.cache_put("old", {"a": 1}, now=time.time() - 8 * 86400)
    gbc.cache_put("young", {"a": 1}, now=time.time() - 6 * 86400)
    assert gbc.cache_get("old") is None
    assert gbc.cache_get("young") == {"a": 1}


def test_empty_lookups_are_never_cached(gbc):
    for value in (None, [], {}, ""):
        assert gbc.cache_put("e", value) is False
    assert not (gbc.cache_dir() / "e.json").exists()


def test_a_corrupt_entry_is_a_miss(gbc):
    gbc.cache_dir().mkdir(parents=True)
    (gbc.cache_dir() / "bad.json").write_text("{nope")
    assert gbc.cache_get("bad") is None


def test_drop_prefix_and_containing(gbc):
    gbc.cache_put("plan-week-a", {"id": "PVT_1"})
    gbc.cache_put("plan-week-b", {"id": "PVT_2"})
    gbc.cache_put("other", {"id": "PVT_1"})
    assert gbc.cache_drop_prefix("plan-week-") == 2
    assert gbc.cache_drop_containing("PVT_1") == 1
    assert gbc.cache_get("other") is None


def test_unwritable_cache_warns_once_and_returns_false(gbc, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    assert gbc.cache_put("k", {"a": 1}) is False
    assert gbc.cache_put("k2", {"a": 1}) is False
    assert capsys.readouterr().err.count("metadata cache not written") == 1
    assert gbc.cache_get("k") is None


def _cli(*args, stdin=None, **env):
    return subprocess.run([sys.executable, str(LIB / "config.py"), "cache", *args], input=stdin,
                          capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))


def test_cli_get_miss_exits_1_and_put_get_round_trips():
    assert _cli("get", "nope").returncode == 1
    assert _cli("put", "k", stdin='{"a": 1}').returncode == 0
    r = _cli("get", "k")
    assert r.returncode == 0 and json.loads(r.stdout) == {"a": 1}


def test_cli_put_never_fails(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert _cli("put", "k", stdin='{"a": 1}', XDG_CACHE_HOME=str(blocker)).returncode == 0
    assert _cli("put", "k", stdin="not json").returncode == 0


def _bash(snippet, **env):
    return subprocess.run(["bash", "-c", f'. "{LIB}/config.sh"; {snippet}'], capture_output=True,
                          text=True, timeout=30, env=dict(os.environ, GB_PYTHON=sys.executable, **env))


def test_bash_helpers_respect_no_cache_and_refresh():
    assert _bash("echo '{\"a\":1}' | gb_cache_put k && gb_cache_get k").stdout.strip() == '{"a": 1}'
    assert _bash("gb_cache_get k", GB_NO_CACHE="1").returncode != 0
    assert _bash("gb_cache_get k", GB_CACHE_REFRESH="1").returncode != 0
    _bash("echo '{\"a\":2}' | gb_cache_put k", GB_NO_CACHE="1")
    assert _bash("gb_cache_get k").stdout.strip() == '{"a": 1}'      # --no-cache never writes
    _bash("echo '{\"a\":3}' | gb_cache_put k", GB_CACHE_REFRESH="1")
    assert _bash("gb_cache_get k").stdout.strip() == '{"a": 3}'      # a refresh still writes


# ---- plan-week ------------------------------------------------------------------

def _fake_gh(wf, calls, stale_numbers=(99,)):
    def fake(*args, parse=True, **kw):
        calls.append(args)
        q = next((a for a in args if a.startswith("query=")), "")
        if any(f"projectV2(number:{n})" in q for n in stale_numbers):
            raise wf.GhError("gh api graphql failed (exit 1): GraphQL: Could not resolve to a "
                             "ProjectV2 with the number 99. (user.projectV2)")
        if "projectsV2" in q:
            return json.dumps({"id": "PVT_new", "number": 36, "title": "Weekly Focus",
                               "url": "U36", "closed": False})
        if "projectV2(number:36)" in q or "search(query" in q:
            return ""
        raise AssertionError(f"unexpected gh call {args}")
    wf.gh = fake


def _project_queries(calls):
    return [c for c in calls if any("projectsV2" in a for a in c)]


def test_plan_week_reuses_the_cached_project(gb_config, capsys):
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    assert len(_project_queries(calls)) == 1
    calls.clear()
    wf2 = load_weekly_focus()
    _fake_gh(wf2, calls)
    wf2.main(["show", "--json"])
    assert _project_queries(calls) == []
    capsys.readouterr()


def test_stale_cached_project_is_dropped_and_refetched_once(gb_config, gbc, capsys):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["url"] == "U36"
    assert "refetching once" in captured.err
    assert gbc.cache_get(PROJECT_KEY)["number"] == 36


def test_a_second_stale_error_is_not_retried_again(gb_config, gbc):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls, stale_numbers=(99, 36))
    with pytest.raises(wf.GhError):
        wf.main(["show", "--json"])
    assert len(_project_queries(calls)) == 1


def test_no_cache_never_reads_or_writes(gb_config, gbc, capsys):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    before = sorted(p.name for p in gbc.cache_dir().iterdir())
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json", "--no-cache"])
    assert json.loads(capsys.readouterr().out)["url"] == "U36"
    assert gbc.cache_get(PROJECT_KEY)["number"] == 99            # untouched
    assert sorted(p.name for p in gbc.cache_dir().iterdir()) == before


def test_plan_week_runs_when_the_cache_cannot_be_written(gb_config, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "cache-is-a-file"
    blocker.write_text("x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    calls = []
    wf = load_weekly_focus()
    _fake_gh(wf, calls)
    wf.main(["show", "--json"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["url"] == "U36"
    assert captured.err.count("metadata cache not written") == 1


SCOPE_ERR = ("GraphQL: Your token has not been granted the required scopes to execute this query. "
             "The 'id' field requires one of the following scopes: ['read:project']")


def test_scope_error_is_not_retried_and_names_the_fix(monkeypatch):
    wf = load_weekly_focus(stub_gh=False)
    runs, sleeps = [], []
    monkeypatch.setattr(wf.time, "sleep", sleeps.append)

    def fake_run(cmd, **kw):
        runs.append(cmd)
        raise subprocess.CalledProcessError(1, cmd, output="", stderr=SCOPE_ERR)
    monkeypatch.setattr(wf.subprocess, "run", fake_run)
    with pytest.raises(wf.GhError) as ei:
        wf.gh("api", "graphql", "-f", "query=x")
    assert "gh auth refresh -s read:project,project" in str(ei.value)
    assert len(runs) == 1 and sleeps == []


def test_scope_error_writes_no_cache(gb_config, gbc, monkeypatch):
    wf = load_weekly_focus(stub_gh=False)
    monkeypatch.setattr(wf.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, cmd, output="", stderr=SCOPE_ERR)))
    with pytest.raises(wf.GhError):
        wf.main(["show", "--json"])
    assert not gbc.cache_dir().exists() or list(gbc.cache_dir().iterdir()) == []


# ---- added during implementation ------------------------------------------------

def test_age_limit_boundary(gbc):
    now = time.time()
    gbc.cache_put("edge-in", {"a": 1}, now=now - 7 * 86400 + 60)
    gbc.cache_put("edge-out", {"a": 1}, now=now - 7 * 86400 - 60)
    assert gbc.cache_get("edge-in", now=now) == {"a": 1}
    assert gbc.cache_get("edge-out", now=now) is None


def test_an_entry_from_the_future_is_a_miss(gbc):
    gbc.cache_put("future", {"a": 1}, now=time.time() + 3600)
    assert gbc.cache_get("future") is None


def test_keys_that_sanitize_to_the_same_file_do_not_read_each_other(gbc):
    # "Weekly Focus" and "Weekly_Focus" share a file name; the stored key tells them apart.
    gbc.cache_put("project-Weekly Focus", {"id": "A"})
    assert gbc.cache_get("project-Weekly_Focus") is None
    assert gbc.cache_get("project-Weekly Focus") == {"id": "A"}


def test_a_cached_id_failure_with_any_gh_error_refetches_once(gb_config, gbc, capsys):
    # A stale option id or a renamed field need not say "Could not resolve"; with cached ids
    # in use, any gh failure that is not a rate limit or a scope error gets one fresh retry.
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()

    def fake(*args, parse=True, **kw):
        calls.append(args)
        q = next((a for a in args if a.startswith("query=")), "")
        if "projectV2(number:99)" in q:
            raise wf.GhError("gh api graphql failed (exit 1): GraphQL: something about field ids")
        if "projectsV2" in q:
            return json.dumps({"id": "PVT_new", "number": 36, "title": "Weekly Focus",
                               "url": "U36", "closed": False})
        return ""
    wf.gh = fake
    wf.main(["show", "--json"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["url"] == "U36" and "refetching once" in captured.err


@pytest.mark.parametrize("message", [
    "GitHub GraphQL rate limit exhausted: gh api graphql",
    "GitHub token lacks the project scope; run `gh auth refresh -s read:project,project`",
])
def test_rate_limit_and_scope_errors_are_never_refetched(gb_config, gbc, message):
    gbc.cache_put(PROJECT_KEY, {"id": "PVT_old", "number": 99, "url": "U99", "title": "Weekly Focus"})
    calls = []
    wf = load_weekly_focus()

    def fake(*args, parse=True, **kw):
        calls.append(args)
        raise wf.GhError(message)
    wf.gh = fake
    with pytest.raises(wf.GhError):
        wf.main(["show", "--json"])
    assert _project_queries(calls) == []
    assert gbc.cache_get(PROJECT_KEY)["number"] == 99      # not dropped either
