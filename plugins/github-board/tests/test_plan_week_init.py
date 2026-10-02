"""plan-week init / config, and exit 4 for every other subcommand without a config (#146)."""
import json
import os
import subprocess
import sys

import pytest

from gbtest import TEST_CFG, WEEKLY_FOCUS, cfg_copy, gh_calls, install_fake_gh, load_lib


def run_wf(tmp_path, *args, stdin=None):
    log = tmp_path / "gh.log"
    env = dict(os.environ, HOME=str(tmp_path / "home"), **install_fake_gh(tmp_path / "bin", [], log))
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), *args], input=stdin, env=env,
                       capture_output=True, text=True, timeout=30)
    return r, gh_calls(log)


def payload(**over):
    p = {"owner": "octo-user", "plan_week": cfg_copy()["plan_week"]}
    p.update(over)
    return json.dumps(p)


@pytest.mark.parametrize("args", [["sync"], ["sync", "--json"], ["show"], ["show", "--json"],
                                  ["set", "Next", "app#1"], ["pick", "app#1"], ["config"]])
def test_every_subcommand_but_init_exits_4_without_a_config(tmp_path, args):
    r, calls = run_wf(tmp_path, *args)
    assert r.returncode == 4, r.stderr
    assert "run `plan-week init`" in r.stderr
    assert calls == []          # nothing reached gh


def test_init_writes_the_config_from_stdin(tmp_path):
    r, calls = run_wf(tmp_path, "init", stdin=payload())
    assert r.returncode == 0, r.stderr
    assert calls == []
    cfg = json.loads(load_lib().config_path().read_text())
    assert cfg["plan_week"] == TEST_CFG["plan_week"] and cfg["owner"] == "octo-user"


def test_init_refuses_to_replace_without_force_then_force_replaces(tmp_path):
    assert run_wf(tmp_path, "init", stdin=payload())[0].returncode == 0
    path = load_lib().config_path()
    before = path.read_text()
    other = cfg_copy()["plan_week"]; other["frozen"] = []
    r, _ = run_wf(tmp_path, "init", stdin=payload(plan_week=other))
    assert r.returncode == 3 and "--force" in r.stderr
    assert path.read_text() == before
    r, _ = run_wf(tmp_path, "init", "--force", stdin=payload(plan_week=other))
    assert r.returncode == 0
    assert json.loads(path.read_text())["plan_week"]["frozen"] == []


def test_init_from_file(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(payload())
    r, _ = run_wf(tmp_path, "init", "--from", str(seed))
    assert r.returncode == 0, r.stderr


def test_init_from_a_missing_file_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", "--from", str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "cannot read" in r.stderr


def test_init_without_plan_week_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", stdin=json.dumps({"owner": "octo-user"}))
    assert r.returncode == 2 and "missing required key plan_week" in r.stderr


def test_init_with_an_unknown_argument_exits_2(tmp_path):
    r, _ = run_wf(tmp_path, "init", "--frobnicate", stdin=payload())
    assert r.returncode == 2 and "--frobnicate" in r.stderr


def test_config_prints_the_config(tmp_path, gb_config):
    r, calls = run_wf(tmp_path, "config")
    assert r.returncode == 0 and json.loads(r.stdout) == TEST_CFG and calls == []
