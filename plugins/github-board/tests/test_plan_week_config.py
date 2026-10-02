"""plan-week takes owner, lanes, schedule, capacity and frozen/always from the config (#146)."""
import json
import subprocess
import sys

import pytest

from gbtest import TEST_CFG, WEEKLY_FOCUS, cfg_copy, load_weekly_focus

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
