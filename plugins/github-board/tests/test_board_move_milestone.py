"""move-card sets the next-release milestone when an issue moves to a post-merge column (#204).

A post-merge column is one whose resolved name is "development complete", "dev complete" or
"done in develop" (any case), or one named in move_card.post_merge_columns, which replaces
that list. Only --issue moves touch the milestone. The card moves first; a milestone problem
warns and never changes the exit code. Every gh call is a stub on PATH.
"""
import json
import os
import subprocess
import sys

import pytest

from gbtest import SKILLS_DIR, cfg_copy, gh_calls, install_fake_gh, write_config

MOVE = SKILLS_DIR / "move-card" / "scripts" / "board-move.sh"
AUTH = {"match": ["auth", "status"],
        "stdout": "github.com\n  - Token scopes: 'project', 'read:org', 'repo'\n"}
FIELD = {"id": "F1", "name": "Status", "options": [
    {"id": "o1", "name": "Todo"}, {"id": "o2", "name": "In Progress"},
    {"id": "o3", "name": "Development Complete"}, {"id": "o4", "name": "DONE IN DEVELOP"},
    {"id": "o5", "name": "QA Passed"}, {"id": "o6", "name": "Done"}]}
V40 = {"number": 15, "title": "v4.0"}
MILESTONES = [{"title": "v4.0", "number": 15, "state": "closed"},
              {"title": "v4.2", "number": 9, "state": "open"},
              {"title": "v4.1", "number": 13, "state": "open"}]
PATCH_CALL = ["api", "-X", "PATCH", "repos/octo-user/app/issues/5", "-F", "milestone=13",
              "--jq", ".milestone.number"]


def content(kind="issue", milestone=V40, on_board=True):
    items = [{"id": "ITEM1", "project": {"number": 7}}] if on_board else []
    return {"data": {"repository": {kind: {"id": "I_1", "milestone": milestone,
                                           "projectItems": {"nodes": items}}}}}


def routes(kind="issue", milestone=V40, on_board=True, ms_route=None, patch=None):
    return [
        AUTH,
        patch or {"match": ["-X", "PATCH"], "stdout": "13\n"},
        ms_route or {"match": ["milestones?state=all&per_page=100", "--paginate"],
                     "stdout": json.dumps(MILESTONES) + "\n"},
        {"match": ["updateProjectV2ItemFieldValue"], "stdout": "ITEM1\n"},
        {"match": ["addProjectV2ItemById"], "stdout": "ITEM1\n"},
        {"match": ["projectsV2(first:100)"],
         "stdout": json.dumps([{"number": 7, "title": "Board", "closed": False}])},
        {"match": ["projectV2(number:$p){id}"], "stdout": "PVT_1\n"},
        {"match": ["fields(first:50)"], "stdout": json.dumps(FIELD)},
        {"match": ["projectItems(first:100)"], "stdout": json.dumps(content(kind, milestone, on_board))},
    ]


def run(tmp_path, *args, rts=None, config=None):
    if config is not None:
        write_config(tmp_path / "xdg-config", config)
    log = tmp_path / "gh.log"
    log.unlink(missing_ok=True)
    env = dict(os.environ, GB_PYTHON=sys.executable,
               **install_fake_gh(tmp_path / "bin", rts if rts is not None else routes(), log))
    r = subprocess.run(["bash", str(MOVE), *args, "--repo", "octo-user/app"], env=env,
                       capture_output=True, text=True, timeout=60)
    return r, gh_calls(log)


def issue(to, *extra):
    return ("--issue", "5", "--to", to, *extra)


def patches(calls):
    return [c for c in calls if c[:3] == ["api", "-X", "PATCH"]]


def ms_lists(calls):
    return [c for c in calls if any("milestones?" in a for a in c)]


def moves(calls):
    return [i for i, c in enumerate(calls) if "updateProjectV2ItemFieldValue" in " ".join(c)]


def test_a_post_merge_move_sets_the_next_release_milestone(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete"))
    assert r.returncode == 0, r.stderr
    assert patches(calls) == [PATCH_CALL]
    # The card moves first, so a milestone problem can never block it.
    assert moves(calls)[0] < calls.index(PATCH_CALL)
    assert 'Moved issue #5 -> "Development Complete"' in r.stdout
    assert "milestone: v4.0 -> v4.1" in r.stdout
    assert "lowest open version" in r.stderr


def test_an_issue_with_no_milestone_reads_none(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete"), rts=routes(milestone=None))
    assert r.returncode == 0, r.stderr
    assert "milestone: none -> v4.1" in r.stdout and patches(calls) == [PATCH_CALL]


def test_the_current_milestone_comes_from_the_item_lookup(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete"))
    lookup = [c for c in calls if "projectItems(first:100)" in " ".join(c)]
    assert len(lookup) == 1 and "milestone{number title}" in " ".join(lookup[0])
    # One list read and one write: no extra call for the current milestone.
    assert len(ms_lists(calls)) == 1 and len(calls) == 8


def test_already_in_the_milestone_writes_nothing(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete"),
                   rts=routes(milestone={"number": 13, "title": "v4.1"}))
    assert r.returncode == 0, r.stderr
    assert patches(calls) == []
    assert "milestone: unchanged (v4.1)" in r.stdout


def test_dry_run_shows_the_change_and_writes_nothing(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete", "--dry-run"))
    assert r.returncode == 0, r.stderr
    assert "would set milestone: v4.0 -> v4.1" in r.stdout
    assert patches(calls) == [] and moves(calls) == []


def test_dry_run_with_add_shows_the_milestone_too(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete", "--dry-run", "--add"),
                   rts=routes(on_board=False))
    assert r.returncode == 0, r.stderr
    assert "would add issue #5" in r.stdout
    assert "would set milestone: v4.0 -> v4.1" in r.stdout
    assert patches(calls) == [] and moves(calls) == []


def test_add_then_move_sets_the_milestone(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete", "--add"), rts=routes(on_board=False))
    assert r.returncode == 0, r.stderr
    assert "Added issue #5" in r.stdout and patches(calls) == [PATCH_CALL]


def test_no_candidate_warns_and_still_moves(tmp_path):
    ms = {"match": ["milestones?state=all"], "stdout": json.dumps([{"title": "Backlog",
                                                                    "number": 2, "state": "open"}])}
    r, calls = run(tmp_path, *issue("Development Complete"), rts=routes(ms_route=ms))
    assert r.returncode == 0, r.stderr
    assert 'Moved issue #5 -> "Development Complete"' in r.stdout
    assert "no next-release milestone" in r.stderr and "milestone not set" in r.stderr
    assert patches(calls) == []


def test_an_unreadable_milestone_list_warns_and_still_moves(tmp_path):
    ms = {"match": ["milestones?state=all"], "stderr": "HTTP 502: Bad Gateway\n", "rc": 1}
    r, calls = run(tmp_path, *issue("Development Complete"), rts=routes(ms_route=ms))
    assert r.returncode == 0, r.stderr
    assert moves(calls) and patches(calls) == []
    assert "502" in r.stderr
    assert "milestone not set: could not read the next-release milestone" in r.stderr
    assert "has no next-release milestone" not in r.stderr


def test_a_failed_patch_warns_with_the_reply_and_keeps_exit_0(tmp_path):
    patch = {"match": ["-X", "PATCH"], "rc": 1, "stderr": "gh: Validation Failed (HTTP 422)\n",
             "stdout": '{"message":"Validation Failed","errors":[{"code":"invalid"}]}\n'}
    r, calls = run(tmp_path, *issue("Development Complete"), rts=routes(patch=patch))
    assert r.returncode == 0, r.stderr
    assert moves(calls) and patches(calls) == [PATCH_CALL]
    assert "422" in r.stderr and '"code":"invalid"' in r.stderr
    assert "milestone not set" in r.stderr and "milestone: v4.0 -> v4.1" not in r.stdout


def test_a_reply_naming_another_milestone_is_a_failure(tmp_path):
    r, _ = run(tmp_path, *issue("Development Complete"),
               rts=routes(patch={"match": ["-X", "PATCH"], "stdout": "99\n"}))
    assert r.returncode == 0, r.stderr
    assert "99" in r.stderr and "milestone not set" in r.stderr
    assert "milestone: v4.0 -> v4.1" not in r.stdout


def test_a_pr_move_makes_no_milestone_call(tmp_path):
    r, calls = run(tmp_path, "--pr", "5", "--to", "Development Complete",
                   rts=routes(kind="pullRequest"))
    assert r.returncode == 0, r.stderr
    assert ms_lists(calls) == [] and patches(calls) == []
    assert "milestone" not in r.stdout + r.stderr


@pytest.mark.parametrize("to", ["In Progress", "Done", "Todo"])
def test_a_column_that_is_not_post_merge_makes_no_milestone_call(tmp_path, to):
    r, calls = run(tmp_path, *issue(to))
    assert r.returncode == 0, r.stderr
    assert ms_lists(calls) == [] and patches(calls) == []
    assert "milestone" not in r.stdout + r.stderr


@pytest.mark.parametrize("to", ["done in develop", "complete"])
def test_the_resolved_column_name_decides_in_any_case(tmp_path, to):
    # "complete" resolves by unique substring to "Development Complete"; the board's
    # "DONE IN DEVELOP" matches the built-in "done in develop" in any case.
    r, calls = run(tmp_path, *issue(to))
    assert r.returncode == 0, r.stderr
    assert patches(calls) == [PATCH_CALL]


def test_dev_complete_is_a_built_in_name(tmp_path):
    field = dict(FIELD, options=[{"id": "o1", "name": "Todo"}, {"id": "o9", "name": "Dev Complete"}])
    rts = [r if "fields(first:50)" not in r["match"] else
           {"match": ["fields(first:50)"], "stdout": json.dumps(field)} for r in routes()]
    r, calls = run(tmp_path, *issue("dev complete"), rts=rts)
    assert r.returncode == 0, r.stderr
    assert patches(calls) == [PATCH_CALL]


def test_the_config_list_replaces_the_built_in_names(tmp_path):
    cfg = cfg_copy()
    cfg["move_card"] = {"post_merge_columns": ["qa passed"]}
    r, calls = run(tmp_path, *issue("QA Passed"), config=cfg)
    assert r.returncode == 0, r.stderr
    assert patches(calls) == [PATCH_CALL]
    r, calls = run(tmp_path, *issue("Development Complete"), config=cfg)
    assert r.returncode == 0, r.stderr
    assert ms_lists(calls) == [] and patches(calls) == []


def test_an_empty_config_list_turns_the_milestone_off(tmp_path):
    cfg = cfg_copy()
    cfg["move_card"] = {"post_merge_columns": []}
    r, calls = run(tmp_path, *issue("Development Complete"), config=cfg)
    assert r.returncode == 0, r.stderr
    assert ms_lists(calls) == [] and patches(calls) == []


def test_a_config_without_the_key_uses_the_built_in_names(tmp_path):
    r, calls = run(tmp_path, *issue("Development Complete"), config=cfg_copy())
    assert r.returncode == 0, r.stderr
    assert patches(calls) == [PATCH_CALL]


def test_the_configured_next_release_is_used(tmp_path):
    cfg = cfg_copy()
    cfg["milestones"] = {"next_release": {"octo-user/app": "v4.2"}}
    r, calls = run(tmp_path, *issue("Development Complete"), config=cfg,
                   rts=routes(patch={"match": ["-X", "PATCH"], "stdout": "9\n"}))
    assert r.returncode == 0, r.stderr
    assert [c for c in patches(calls) if "milestone=9" in c]
    assert "milestone: v4.0 -> v4.2" in r.stdout


def test_an_invalid_config_warns_and_still_moves(tmp_path):
    cfg = cfg_copy()
    cfg["move_card"] = {"post_merge_columns": "Development Complete"}
    r, calls = run(tmp_path, *issue("Development Complete"), config=cfg)
    assert r.returncode == 0, r.stderr
    assert moves(calls) and patches(calls) == []
    assert "milestone not set: cannot read move_card.post_merge_columns" in r.stderr
    assert ms_lists(calls) == []
