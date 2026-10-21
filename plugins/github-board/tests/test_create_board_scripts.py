"""create-board scripts: NOT_FOUND falls back to the org lookup; failures are not "0 items".

gh exits 1 on a NOT_FOUND GraphQL error (JSON body on stdout), so the user-then-org fallback in
inspect-template.sh and sync-workflows.sh must tell that apart from a real failure.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gbtest import gh_calls, install_fake_gh

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "create-board" / "scripts"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")

NOT_FOUND = json.dumps({"data": {"user": None},
                        "errors": [{"type": "NOT_FOUND", "path": ["user"],
                                    "message": "Could not resolve to a User with the login of 'acme'."}]})


def _run(script, args, env, timeout=60):
    return subprocess.run(["bash", str(SCRIPTS / script), *args], capture_output=True, text=True,
                          env=env, timeout=timeout)


def _env(tmp_path, routes, **extra):
    log = tmp_path / "gh.log"
    env = dict(os.environ, **install_fake_gh(tmp_path / "bin", routes, log), **extra)
    return env, log


def test_inspect_template_falls_back_to_the_org_when_the_user_is_not_found(tmp_path):
    org = {"data": {"organization": {"projectV2": {"id": "PVT_1", "title": "T"}}}}
    env, log = _env(tmp_path, [
        {"match": ["user(login"], "stdout": NOT_FOUND, "stderr": "gh: Could not resolve to a User", "rc": 1},
        {"match": ["organization(login"], "stdout": json.dumps(org)},
    ])
    out = tmp_path / "snap.json"
    done = _run("inspect-template.sh", ["--owner", "acme", "--number", "3", "--out", str(out)], env)
    assert done.returncode == 0, done.stderr
    assert json.loads(out.read_text()) == org


def test_inspect_template_still_exits_on_a_real_failure(tmp_path):
    env, _ = _env(tmp_path, [{"match": ["user(login"], "stderr": "HTTP 502", "rc": 1}])
    done = _run("inspect-template.sh",
                ["--owner", "acme", "--number", "3", "--out", str(tmp_path / "s.json")], env)
    assert done.returncode == 1
    assert "502" in done.stderr


def _wf_snapshot(tmp_path):
    snap = tmp_path / "tmpl.json"
    snap.write_text(json.dumps({"data": {"user": {"projectV2": {"workflows": {"nodes": []}}}}}))
    return snap


def test_sync_workflows_falls_back_to_the_org_and_passes_login_as_a_string(tmp_path):
    org = {"data": {"organization": {"projectV2": {"workflows": {"nodes": [
        {"id": "W1", "name": "Auto-add to project", "enabled": True}]}}}}}
    env, log = _env(tmp_path, [
        {"match": ["user(login"], "stdout": NOT_FOUND, "stderr": "gh: Could not resolve", "rc": 1},
        {"match": ["organization(login"], "stdout": json.dumps(org)},
        {"match": ["/users/acme"], "stdout": "Organization\n"},
    ])
    done = _run("sync-workflows.sh", ["--snapshot", str(_wf_snapshot(tmp_path)), "--new-project-id",
                                      "PVT_1", "--new-owner", "acme", "--new-number", "3",
                                      "--tgt-repo", "acme/app"], env)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["auto_add_present"] is True
    for call in gh_calls(log):
        if call[:2] == ["api", "graphql"]:
            i = call.index("login=acme")
            assert call[i - 1] == "-f", call


@pytest.mark.parametrize("owner", ["a b", "@file", "-x", "a;b"])
def test_sync_workflows_rejects_a_malformed_owner(tmp_path, owner):
    env, log = _env(tmp_path, [])
    done = _run("sync-workflows.sh", ["--snapshot", str(_wf_snapshot(tmp_path)), "--new-project-id",
                                      "PVT_1", "--new-owner", owner, "--new-number", "3",
                                      "--tgt-repo", "acme/app"], env)
    assert done.returncode == 2 and gh_calls(log) == [], done.stderr


def test_backfill_exits_nonzero_when_the_issue_list_fails(tmp_path):
    env, _ = _env(tmp_path, [{"match": ["issue", "list"], "stderr": "HTTP 401", "rc": 1}])
    done = _run("backfill-issues.sh",
                ["--project", "3", "--target-owner", "acme", "--repo", "acme/app"], env)
    assert done.returncode != 0
    assert "Backfilled 0 items" not in done.stdout


def test_backfill_exits_nonzero_when_the_pr_list_fails(tmp_path):
    env, _ = _env(tmp_path, [
        {"match": ["issue", "list"], "stdout": ""},
        {"match": ["pr", "list"], "stderr": "HTTP 401", "rc": 1},
    ])
    done = _run("backfill-issues.sh", ["--project", "3", "--target-owner", "acme", "--repo",
                                       "acme/app", "--include-prs"], env)
    assert done.returncode != 0
    assert "Backfilled 0 items" not in done.stdout


def test_backfill_still_reports_when_the_retry_add_fails(tmp_path):
    env, _ = _env(tmp_path, [
        {"match": ["issue", "list"], "stdout": "https://github.com/acme/app/issues/1\n"},
        {"match": ["item-add"], "stderr": "boom", "rc": 1},
        {"match": ["item-list"], "stdout": ""},
    ], BACKFILL_RETRY_SLEEP="0")
    done = _run("backfill-issues.sh",
                ["--project", "3", "--target-owner", "acme", "--repo", "acme/app"], env)
    assert done.returncode == 1
    assert "Backfilled 1 items (0 added, 1 failed)" in done.stdout, done.stdout + done.stderr


def test_verify_board_exits_two_when_the_new_snapshot_cannot_be_read(tmp_path):
    env, _ = _env(tmp_path, [{"match": ["graphql"], "stderr": "HTTP 502", "rc": 1}])
    snap = _wf_snapshot(tmp_path)
    done = _run("verify-board.sh", ["--snapshot", str(snap), "--new-owner", "acme",
                                    "--new-number", "3"], env)
    assert done.returncode == 2, done.stdout + done.stderr


def test_inspect_template_passes_login_as_a_string_in_both_queries(tmp_path):
    org = {"data": {"organization": {"projectV2": {"id": "PVT_1", "title": "T"}}}}
    env, log = _env(tmp_path, [
        {"match": ["user(login"], "stdout": NOT_FOUND, "stderr": "gh: Could not resolve", "rc": 1},
        {"match": ["organization(login"], "stdout": json.dumps(org)},
    ])
    done = _run("inspect-template.sh",
                ["--owner", "123", "--number", "3", "--out", str(tmp_path / "s.json")], env)
    assert done.returncode == 0, done.stderr
    calls = [c for c in gh_calls(log) if c[:2] == ["api", "graphql"]]
    assert len(calls) == 2                      # the user query and the org fallback
    for call in calls:
        i = call.index("login=123")
        assert call[i - 1] == "-f", call
