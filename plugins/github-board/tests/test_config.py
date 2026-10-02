"""lib/config.py (#146): load, validate, init, and the CLI's exit codes."""
import json
import os
import subprocess
import sys

import pytest

from gbtest import LIB, TEST_CFG, cfg_copy, load_lib, write_config

CLI = [sys.executable, str(LIB / "config.py")]


def run_cli(*args, stdin=None):
    return subprocess.run(CLI + list(args), input=stdin, capture_output=True, text=True, timeout=30)


@pytest.fixture
def cfg_home(tmp_path):
    return tmp_path / "xdg-config"


def test_missing_config_exits_4_and_says_run_init():
    r = run_cli("get", "owner")
    assert r.returncode == 4
    assert "run `plan-week init`" in r.stderr


def test_load_returns_the_config(gb_config):
    gbc = load_lib()
    assert gbc.load(require=("plan_week",))["owner"] == "octo-user"
    assert gbc.config_path() == gb_config


def test_unparseable_file_exits_2(cfg_home):
    write_config(cfg_home, "{not json")
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "not valid JSON" in r.stderr


def test_unknown_version_exits_2_naming_version(cfg_home):
    c = cfg_copy(); c["version"] = 2
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "unknown version 2" in r.stderr


@pytest.mark.parametrize("path", [
    ("owner",), ("plan_week", "lanes"), ("plan_week", "schedule"), ("plan_week", "frozen"),
    ("plan_week", "capacity", "hours"), ("plan_week", "launchd", "label_prefix"),
])
def test_missing_key_exits_2_naming_the_key(cfg_home, path):
    c = cfg_copy()
    node = c
    for part in path[:-1]:
        node = node[part]
    del node[path[-1]]
    write_config(cfg_home, c)
    r = run_cli("get", "plan_week.board_title")
    assert r.returncode == 2
    assert "missing required key " + ".".join(path) in r.stderr


def test_schedule_with_unknown_lane_exits_2_naming_the_day(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"]["thu"] = ["Tolling"]
    write_config(cfg_home, c)
    r = run_cli("get", "plan_week.board_title")
    assert r.returncode == 2
    assert "plan_week.schedule.thu" in r.stderr and "'Tolling'" in r.stderr


def test_schedule_with_unknown_day_exits_2(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"]["funday"] = []
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "plan_week.schedule.funday" in r.stderr


@pytest.mark.parametrize("mutate,key", [
    (lambda pw: pw.update(default_lane="Tooling"), "plan_week.default_lane"),
    (lambda pw: pw["lanes"].append({"name": "Security", "repos": ["x"]}), "plan_week.lanes[3].name"),
    (lambda pw: pw["lanes"].append({"name": "Empty"}), "plan_week.lanes[3]"),
    (lambda pw: pw.update(always=["no-hash-here"]), "plan_week.always[0]"),
    (lambda pw: pw["launchd"].update(times=["7:00"]), "plan_week.launchd.times[0]"),
    (lambda pw: pw["launchd"].update(times=[]), "plan_week.launchd.times"),
    (lambda pw: pw["launchd"].update(label_prefix="has space"), "plan_week.launchd.label_prefix"),
    (lambda pw: pw["capacity"].update(hours=[20, 10]), "plan_week.capacity.hours"),
    (lambda pw: pw["capacity"].update(max_repos_besides_security=True), "plan_week.capacity.max_repos_besides_security"),
])
def test_bad_values_exit_2_naming_the_key(cfg_home, mutate, key):
    c = cfg_copy(); mutate(c["plan_week"])
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and key in r.stderr


def test_schedule_null_and_launchd_disabled_without_times_are_valid(cfg_home):
    c = cfg_copy(); c["plan_week"]["schedule"] = None
    c["plan_week"]["launchd"] = {"enabled": False, "times": [], "label_prefix": "dev.x"}
    write_config(cfg_home, c)
    assert run_cli("get", "plan_week.schedule").stdout == "null\n"


def test_get_prints_scalars_raw_and_lists_one_per_line(gb_config):
    assert run_cli("get", "plan_week.launchd.label_prefix").stdout == "dev.example.plan-week\n"
    assert run_cli("get", "plan_week.launchd.enabled").stdout == "true\n"
    assert run_cli("get", "plan_week.launchd.times", "--lines").stdout == "07:00\n18:00\n"
    assert json.loads(run_cli("get", "plan_week.capacity").stdout) == TEST_CFG["plan_week"]["capacity"]


@pytest.mark.parametrize("section, hint", [("create_board", "create-board init"),
                                           ("plan_week", "plan-week init")])
def test_get_of_a_missing_section_exits_4_naming_its_init(cfg_home, section, hint):
    # C1: create-board init ran first, so the file exists but has no plan_week (or the other
    # way round). That is "not set up yet" (exit 4, run init), not an invalid config (2).
    c = cfg_copy(); del c[section]
    write_config(cfg_home, c)
    r = run_cli("get", f"{section}.x")
    assert r.returncode == 4, r.stderr
    assert hint in r.stderr and section in r.stderr


def test_get_optional_of_a_missing_key_prints_nothing_and_exits_0(cfg_home):
    write_config(cfg_home, cfg_copy())
    r = run_cli("get", "prune_branches.tracking_issue_authors", "--lines", "--optional")
    assert (r.returncode, r.stdout) == (0, "")


def test_get_optional_without_a_config_exits_0_but_an_invalid_one_still_exits_2(cfg_home):
    assert run_cli("get", "prune_branches.tracking_issue_authors", "--optional").returncode == 0
    write_config(cfg_home, "{nope")
    assert run_cli("get", "prune_branches.tracking_issue_authors", "--optional").returncode == 2


def test_prune_branches_tracking_issue_authors_is_validated(cfg_home):
    c = cfg_copy(); c["prune_branches"] = {"tracking_issue_authors": ["triage-bot[bot]", "a b"]}
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "prune_branches.tracking_issue_authors[1]" in r.stderr
    c["prune_branches"]["tracking_issue_authors"] = ["triage-bot[bot]", "app/triage", "octo-user"]
    write_config(cfg_home, c)
    assert run_cli("get", "prune_branches.tracking_issue_authors", "--lines").stdout.split() == \
        ["triage-bot[bot]", "app/triage", "octo-user"]


def test_a_dangling_config_symlink_exits_2_naming_it(cfg_home, tmp_path):
    # S5: a symlink to a moved dotfiles checkout read as "no config, run init", and init then
    # replaced the link with a plain file.
    path = cfg_home / "github-board" / "config.json"
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path / "gone" / "config.json")
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "dangling symlink" in r.stderr and str(path) in r.stderr
    r = run_cli("init", "--require", "plan_week", stdin=_payload())
    assert r.returncode == 2 and path.is_symlink()


def test_bad_create_board_template_number_exits_2(cfg_home):
    c = cfg_copy(); c["create_board"]["template_number"] = 0
    write_config(cfg_home, c)
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "create_board.template_number" in r.stderr


# ---- init -------------------------------------------------------------------

def _payload(**over):
    p = {"owner": "octo-user", "plan_week": cfg_copy()["plan_week"]}
    p.update(over)
    return json.dumps(p)


def test_init_writes_the_file_from_stdin():
    gbc = load_lib()
    r = run_cli("init", "--require", "plan_week", stdin=_payload())
    assert r.returncode == 0, r.stderr
    written = json.loads(gbc.config_path().read_text())
    assert written["version"] == 1 and written["plan_week"] == TEST_CFG["plan_week"]


def test_init_refuses_a_different_section_without_force():
    gbc = load_lib()
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0
    before = gbc.config_path().read_text()
    changed = cfg_copy()["plan_week"]; changed["board_title"] = "Other"
    r = run_cli("init", "--require", "plan_week", stdin=_payload(plan_week=changed))
    assert r.returncode == 3 and "plan_week" in r.stderr and "--force" in r.stderr
    assert gbc.config_path().read_text() == before
    r = run_cli("init", "--require", "plan_week", "--force", stdin=_payload(plan_week=changed))
    assert r.returncode == 0
    assert json.loads(gbc.config_path().read_text())["plan_week"]["board_title"] == "Other"


def test_init_with_the_same_values_is_not_a_conflict():
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0
    assert run_cli("init", "--require", "plan_week", stdin=_payload()).returncode == 0


def test_init_adds_a_section_to_an_existing_config(gb_config):
    c = cfg_copy(); del c["create_board"]
    write_config(gb_config.parent.parent, c)
    r = run_cli("init", "--require", "create_board",
                stdin=json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}}))
    assert r.returncode == 0, r.stderr
    written = json.loads(gb_config.read_text())
    assert written["create_board"]["template_number"] == 4 and written["plan_week"] == TEST_CFG["plan_week"]


def test_init_from_file(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(_payload())
    assert run_cli("init", "--require", "plan_week", "--from", str(seed)).returncode == 0


def test_init_from_a_missing_file_exits_2(tmp_path):
    r = run_cli("init", "--from", str(tmp_path / "nope.json"))
    assert r.returncode == 2 and "cannot read" in r.stderr


def test_init_with_an_invalid_payload_writes_nothing():
    gbc = load_lib()
    bad = cfg_copy()["plan_week"]; bad["schedule"]["mon"] = ["Nope"]
    r = run_cli("init", "--require", "plan_week", stdin=_payload(plan_week=bad))
    assert r.returncode == 2 and "plan_week.schedule.mon" in r.stderr
    assert not gbc.config_path().exists()


def test_init_require_plan_week_rejects_a_payload_without_it():
    r = run_cli("init", "--require", "plan_week", stdin=json.dumps({"owner": "octo-user"}))
    assert r.returncode == 2 and "missing required key plan_week" in r.stderr


def test_init_with_an_unreadable_config_exits_2_without_a_traceback(cfg_home):
    (cfg_home / "github-board" / "config.json").mkdir(parents=True)
    for args in (("init", "--require", "plan_week"), ("init", "--require", "plan_week", "--force")):
        r = run_cli(*args, stdin=_payload())
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
    r = run_cli("get", "owner")
    assert r.returncode == 2 and "cannot read" in r.stderr

# ---- config.sh --------------------------------------------------------------

def _bash(snippet):
    return subprocess.run(["bash", "-c", f'. "{LIB}/config.sh"; {snippet}'], capture_output=True,
                          text=True, timeout=30, env=dict(os.environ, GB_PYTHON=sys.executable))


def test_config_sh_get(gb_config):
    r = _bash("gb_config_get plan_week.launchd.label_prefix")
    assert r.returncode == 0 and r.stdout == "dev.example.plan-week\n"


def test_config_sh_get_passes_exit_4_through():
    assert _bash("gb_config_get owner").returncode == 4
