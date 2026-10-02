"""plan-week takes owner, lanes, schedule, capacity and frozen/always from the config (#146)."""
import json
import subprocess
import sys

import pytest

from gbtest import TEST_CFG, WEEKLY_FOCUS, cfg_copy, load_lib, load_weekly_focus, write_config

SEASON = {"season-repo"}
TOOLING = {"tool-a", "tool-b"}


def legacy_lane_for(repo, labels):
    """weekly-focus.py's lane_for() before #146, verbatim, over TEST_CFG's repo sets."""
    if any("security" in l.lower() for l in labels):
        return "Security"
    if repo in SEASON:
        return "Season"
    return "Tooling" if repo in TOOLING else "Product"


# Every repo/label case the moved tests use, plus case and substring variants.
CASES = [("season-repo", ["Security"]), ("season-repo", ["bug"]), ("tool-a", []),
         ("some-app", []), ("tool-b", ["needs-security-review"]), ("some-app", ["SECURITY"]),
         ("tool-a", ["bug", "P1"]), ("season-repo", []), ("some-app", ["bug"])]


@pytest.mark.parametrize("repo,labels", CASES)
def test_config_lanes_give_the_same_lane_as_the_old_rule(repo, labels):
    assert load_weekly_focus(TEST_CFG).lane_for(repo, labels) == legacy_lane_for(repo, labels)


def test_first_matching_rule_wins():
    c = cfg_copy()
    c["plan_week"]["lanes"] = [{"name": "A", "repos": ["r"]}, {"name": "B", "repos": ["r"]}]
    c["plan_week"]["schedule"] = None
    assert load_weekly_focus(c).lane_for("r", []) == "A"


def test_single_lane_preset_puts_everything_in_the_default_lane():
    c = cfg_copy()
    c["plan_week"]["lanes"] = []
    c["plan_week"]["default_lane"] = "Work"
    c["plan_week"]["schedule"] = None
    wf = load_weekly_focus(c)
    assert wf.lane_for("anything", ["security"]) == "Work"
    assert wf.FIELDS["Lane"] == ["Work"]


def test_label_lane_is_the_first_label_rule_that_matches():
    wf = load_weekly_focus(TEST_CFG)
    assert wf.label_lane(["Security-Hotfix"]) == "Security"
    assert wf.label_lane(["bug"]) is None


def test_apply_config_sets_owner_title_and_queries():
    c = cfg_copy(); c["owner"] = "someone-else"; c["plan_week"]["board_title"] = "My Week"
    wf = load_weekly_focus(c)
    assert wf.OWNER == "someone-else" and wf.TITLE == "My Week"
    assert 'login:"someone-else"' in wf.PROJECTS_Q and 'login:"someone-else"' in wf.BOARD_ITEMS_Q
    assert "author:someone-else" in wf.PR_LINKED_Q


def test_add_skips_a_lane_the_board_does_not_have(capsys):
    wf = load_weekly_focus(TEST_CFG)
    sets = []
    wf.gh = lambda *a, **k: {"id": "ITEM"}
    wf.set_opt = lambda pid, item, field, opt: sets.append((field["id"], opt))
    fields = {"Lane": {"id": "L", "opts": {"Product": "p"}}, "Focus": {"id": "F", "opts": {"Next": "n"}}}
    wf.add(36, "PID", fields, "tool-a#1", [], "Next")
    assert sets == [("F", "Next")]
    assert "board has no Lane option 'Tooling'" in capsys.readouterr().err


def test_board_readme_is_built_from_the_config():
    text = load_weekly_focus(TEST_CFG).board_readme()
    assert "At most 3 repos per week besides Security" in text
    assert "Weekly rhythm (10-20h)" in text
    assert "- Thu: Tooling" in text and "- Fri: Season" in text
    assert "launchd runs `weekly-focus.py sync` at 07:00 and 18:00." in text
    assert "Frozen (not synced; issues kept open): frozen-repo." in text


def test_board_readme_without_a_schedule_or_launchd():
    c = cfg_copy()
    c["plan_week"]["schedule"] = None
    c["plan_week"]["launchd"]["enabled"] = False
    text = load_weekly_focus(c).board_readme()
    assert "No fixed days: Security first, then priority order." in text
    assert "launchd" not in text


def test_help_exits_0_without_a_config():
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "--help"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0 and "weekly-focus.py sync" in r.stdout


def test_show_without_a_config_exits_4():
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "show"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 4 and "plan-week init" in r.stderr


def test_show_with_a_bad_config_exits_2_naming_the_key(tmp_path):
    from gbtest import write_config
    c = cfg_copy(); del c["plan_week"]["frozen"]
    write_config(tmp_path / "xdg-config", c)
    r = subprocess.run([sys.executable, str(WEEKLY_FOCUS), "show"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 2 and "plan_week.frozen" in r.stderr


@pytest.mark.parametrize("day,monday", [
    ("2026-12-31", "2026-12-28"),   # ISO week 53
    ("2027-01-01", "2026-12-28"),   # year rollover, still ISO week 53 of 2026
    ("2027-01-03", "2026-12-28"),   # Sunday of that week
    ("2027-01-04", "2027-01-04"),   # Monday of ISO week 1
    ("2026-03-08", "2026-03-02"),   # US DST starts
    ("2026-11-01", "2026-10-26"),   # US DST ends
    ("2028-02-29", "2028-02-28"),   # leap day
])
def test_week_start_across_calendar_boundaries(day, monday):
    import datetime
    wf = load_weekly_focus(TEST_CFG)
    assert wf.week_start(datetime.date.fromisoformat(day)).isoformat() == monday


# ---- S2: a config lane missing from the board's Lane field fails loudly ----------------

def test_a_config_lane_the_board_lacks_fails_naming_it(gb_config):
    from gbtest import TEST_CFG as CFG
    wf = load_weekly_focus(CFG)
    fields = [{"id": "F_focus", "name": "Focus", "options": [{"id": f"o{i}", "name": n} for i, n in
                                                            enumerate(["This week", "Next", "Later"])]},
              {"id": "F_lane", "name": "Lane", "options": [{"id": "l1", "name": "Security"},
                                                          {"id": "l2", "name": "Product"}]}]
    calls = []

    def fake(*args, parse=True, **kw):
        calls.append(args)
        return "\n".join(json.dumps(f) for f in fields)
    wf.gh = fake
    with pytest.raises(wf.BoardSetupError) as ei:
        wf.ensure_fields(36)
    msg = str(ei.value)
    assert "Season" in msg and "Tooling" in msg and "Lane" in msg
    assert not any("field-create" in a for c in calls for a in c)
    assert load_lib().cache_get(("plan-week", "octo-user", "fields", "36")) is None


# ---- R4: lane names cannot contain ',' (gh joins options with ',') ----------------------

@pytest.mark.parametrize("where", ["lane", "default"])
def test_a_comma_in_a_lane_name_is_rejected(tmp_path, where):
    c = cfg_copy()
    if where == "lane":
        c["plan_week"]["lanes"][2]["name"] = "Tooling, misc"
        c["plan_week"]["schedule"]["thu"] = ["Tooling, misc"]
        key = "plan_week.lanes[2].name"
    else:
        c["plan_week"]["default_lane"] = "Product, other"
        c["plan_week"]["schedule"] = None
        key = "plan_week.default_lane"
    write_config(tmp_path / "xdg-config", c)
    gbc = load_lib()
    with pytest.raises(gbc.ConfigError) as ei:
        gbc.load()
    assert ei.value.key == key and "," in str(ei.value)


# ---- C-006: a Focus or Lane field that is not single-select fails with a BoardSetupError ----

@pytest.mark.parametrize("bad", ["Lane", "Focus"])
def test_a_field_that_is_not_single_select_fails_naming_it(gb_config, bad):
    from gbtest import TEST_CFG as CFG
    wf = load_weekly_focus(CFG)
    opts = {"Focus": ["This week", "Next", "Later"],
            "Lane": ["Security", "Season", "Tooling", "Product"]}
    fields = [{"id": f"F_{n}", "name": n, "options": [{"id": f"{n}{i}", "name": o}
                                                      for i, o in enumerate(opts[n])]}
              for n in ("Focus", "Lane")]
    fields = [f if f["name"] != bad else {"id": f["id"], "name": bad} for f in fields]
    calls = []

    def fake(*args, parse=True, **kw):
        calls.append(args)
        return "\n".join(json.dumps(f) for f in fields)
    wf.gh = fake
    with pytest.raises(wf.BoardSetupError) as ei:
        wf.ensure_fields(36)
    msg = str(ei.value)
    assert bad in msg and "single-select" in msg
    assert not any("field-create" in a for c in calls for a in c)


# ---- X-007: lane refresh applies the configured rule order (first match wins) -----------

def _repo_first_cfg():
    from gbtest import cfg_copy
    c = cfg_copy()
    c["plan_week"]["lanes"] = [{"name": "Infra", "repos": ["infra-repo"]},
                               {"name": "Security", "labels_containing": ["security"]}]
    c["plan_week"]["schedule"] = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    return c


def _refresh(wf, lane, repo, labels):
    sets = []
    wf.set_opt = lambda pid, item, field, opt: sets.append((item, opt))
    fields = {"Lane": {"id": "L", "opts": {n: n for n in ("Infra", "Security", "Product")}}}
    have = {f"{repo}#1": {"id": "i1", "lane": lane}}
    issues = {f"{repo}#1": {"repo": repo, "labels": labels}}
    return wf.refresh_lanes("P", fields, have, issues), sets


def test_a_repo_rule_before_a_label_rule_wins_in_lane_refresh():
    wf = load_weekly_focus(_repo_first_cfg())
    assert wf.lane_for("infra-repo", ["security"]) == "Infra"
    changed, sets = _refresh(wf, "Infra", "infra-repo", ["security"])
    assert changed == [] and sets == []
    changed, sets = _refresh(wf, "", "infra-repo", ["security"])
    assert sets == [("i1", "Infra")]


def test_a_label_rule_still_lifts_a_repo_that_no_earlier_rule_matches():
    wf = load_weekly_focus(_repo_first_cfg())
    changed, sets = _refresh(wf, "Product", "other-repo", ["security"])
    assert sets == [("i1", "Security")]
    assert changed == [{"key": "other-repo#1", "from": "Product", "to": "Security"}]
