"""promote-shipped sets the release milestone of each shipped item (#203).

For a `merged` candidate, apply-promotions.sh maps the release tag it already resolves
(or --release-tag) to a milestone: the exact vX.Y.Z title first, then vX.Y. When the
item's milestone differs it is set through REST by number, so a closed release
milestone works. wontfix and nopr items keep theirs. A failed milestone write never
undoes the board move. Every `gh` call here is a stub on PATH.
"""
import json
import os
import shutil
import subprocess

import pytest

from gbtest import SKILLS_DIR, gh_calls, install_fake_gh

SCRIPTS = SKILLS_DIR / "promote-shipped" / "scripts"
APPLY = SCRIPTS / "apply-promotions.sh"
SHA = "aaa"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")

MILESTONES = [{"title": "v4.0", "number": 15, "state": "closed"},
              {"title": "v4.1", "number": 13, "state": "open"}]
V40 = {"number": 15, "title": "v4.0", "state": "CLOSED"}
V41 = {"number": 13, "title": "v4.1", "state": "OPEN"}

# Logs each call. $REL_JSON holds the releases; compare answers $COMPARE (default ahead).
# $MS_PAGES holds a JSON list of pages, printed back to back like an older gh does.
# $MS_FAIL fails the milestone list; $PATCH_FAIL fails every PATCH with a 422 body.
_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
if [ "$1 $2" = "auth status" ]; then
  echo "  - Token scopes: 'project', 'read:project', 'repo'"; exit 0
fi
case "$*" in
  "api -X PATCH "*)
    # Prints what --jq .milestone.number prints: the number sent, 99 with $PATCH_WRONG.
    # On an HTTP error gh prints the response body on stdout.
    if [ -n "${PATCH_FAIL:-}" ]; then
      echo '{"message":"Validation Failed","errors":[{"resource":"Issue","field":"milestone","code":"invalid"}]}'
      echo "gh: Validation Failed (HTTP 422)" >&2; exit 1
    fi
    [ -n "${PATCH_WRONG:-}" ] && { echo 99; exit 0; }
    echo "${6#milestone=}"; exit 0 ;;
  "api graphql"*) echo '{"data":{}}'; exit 0 ;;
  "issue comment"*) exit 0 ;;
  "issue view"*) echo 0; exit 0 ;;
esac
case "$2" in
  */releases) [ -n "${REL_FAIL:-}" ] && { echo "HTTP 401" >&2; exit 1; }; cat "$REL_JSON"; exit 0 ;;
  */compare/*) echo "${COMPARE:-ahead}"; exit 0 ;;
  *"/milestones?"*)
    [ -n "${MS_FAIL:-}" ] && { echo "HTTP 502: Bad Gateway" >&2; exit 1; }
    jq -c '.[]' "$MS_PAGES"; exit 0 ;;
esac
echo "unexpected gh call: $*" >&2
exit 1
'''


def _candidate(item_id="PVTI_1", number=7, milestone=None, pclass="merged", **extra):
    c = {"itemId": item_id, "number": number, "title": "shipped thing",
         "status": "Dev Complete", "url": f"https://github.com/o/r/issues/{number}",
         "repo": "o/r", "promoteClass": pclass,
         "mergedPRs": ([{"number": 8, "baseRefName": "develop", "mergeCommitOid": SHA,
                         "repo": "o/r", "inMain": "yes"}] if pclass == "merged" else [])}
    if milestone != "absent":
        c["milestone"] = milestone
    c.update(extra)
    return c


def _run(tmp_path, *args, candidates=None, milestones=None, pages=None, tag="v4.0.0",
         stub=_STUB, **env):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(stub)
    (bindir / "gh").chmod(0o755)
    rel = tmp_path / "releases.json"
    rel.write_text(json.dumps([{"tag_name": tag, "html_url": "https://example.test/rel",
                                "published_at": "2026-10-01T00:00:00Z", "draft": False}]))
    ms = tmp_path / "ms_pages.json"
    ms.write_text(json.dumps(pages if pages is not None else
                             [MILESTONES if milestones is None else milestones]))
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status", "doneOptionId": "opt_done"},
        "candidates": candidates if candidates is not None else [_candidate(milestone=V41)],
    }))
    log = tmp_path / "gh.log"
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log),
             REL_JSON=str(rel), MS_PAGES=str(ms))
    e.update(env)
    r = subprocess.run(["bash", str(APPLY), str(cand), *args], capture_output=True, text=True,
                       env=e, timeout=60, cwd=str(tmp_path))
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def _patches(calls):
    return [c for c in calls if c.startswith("api -X PATCH")]


def _ms_lists(calls):
    return [c for c in calls if "/milestones?" in c]


def test_dry_run_lists_mismatch(tmp_path):
    r, calls = _run(tmp_path, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would set milestone: v4.1 -> v4.0 (v4.0.0)" in r.stdout
    assert _patches(calls) == []


def test_apply_fixes_into_closed_milestone_by_number(tmp_path):
    r, calls = _run(tmp_path, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls
    # The board move comes first; the milestone is annotation, like the comment.
    move = [i for i, c in enumerate(calls) if c.startswith("api graphql")][0]
    assert move < calls.index("api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number")
    assert "Milestones: 1 set, 0 unchanged, 0 skipped, 0 failed" in r.stdout


def test_matching_milestone_no_write(tmp_path):
    cands = [_candidate(milestone=V40)]
    r, calls = _run(tmp_path, "--dry-run", candidates=cands)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would set milestone" not in r.stdout
    r, calls = _run(tmp_path, "--apply", candidates=cands)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _patches(calls) == []
    assert "Milestones: 0 set, 1 unchanged" in r.stdout


def test_null_milestone_gets_fixed(tmp_path):
    r, _ = _run(tmp_path, "--dry-run", candidates=[_candidate(milestone=None)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would set milestone: none -> v4.0 (v4.0.0)" in r.stdout


def test_candidate_without_milestone_field_reads_unknown(tmp_path):
    # An older candidates file has no milestone key: say so rather than claim "none".
    r, calls = _run(tmp_path, "--apply", candidates=[_candidate(milestone="absent")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "unknown -> v4.0" in r.stdout
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls


def test_exact_patch_title_wins(tmp_path):
    ms = [{"title": "v3.18", "number": 20, "state": "closed"},
          {"title": "v3.18.1", "number": 21, "state": "closed"}]
    r, calls = _run(tmp_path, "--apply", milestones=ms, tag="v3.18.1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=21 --jq .milestone.number" in calls


def test_minor_title_is_the_fallback(tmp_path):
    ms = [{"title": "v3.18", "number": 20, "state": "closed"},
          {"title": "v3.18.2", "number": 22, "state": "open"}]
    r, calls = _run(tmp_path, "--apply", milestones=ms, tag="v3.18.1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=20 --jq .milestone.number" in calls


@pytest.mark.parametrize("title,tag", [("4.0", "v4.0.0"), ("v4.0", "4.0.0")])
def test_leading_v_is_optional_on_both_sides(tmp_path, title, tag):
    ms = [{"title": title, "number": 15, "state": "closed"}]
    r, calls = _run(tmp_path, "--apply", milestones=ms, tag=tag)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls


def test_two_matching_titles_are_refused(tmp_path):
    ms = [{"title": "v4.0", "number": 15, "state": "closed"},
          {"title": "4.0", "number": 16, "state": "open"}]
    r, calls = _run(tmp_path, "--apply", milestones=ms)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ambiguous" in (r.stdout + r.stderr).lower()
    assert _patches(calls) == []


def test_no_matching_milestone_warns_and_skips(tmp_path):
    r, calls = _run(tmp_path, "--apply", tag="v9.0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stderr and "v9.0.0" in r.stderr
    assert _patches(calls) == []
    assert "Milestones: 0 set, 0 unchanged, 1 skipped, 0 failed" in r.stdout


def test_tag_not_shaped_like_a_version_warns_and_skips(tmp_path):
    r, calls = _run(tmp_path, "--apply", "--release-tag", "nightly-2026-10-01")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stderr and "is not vX.Y.Z or vX.Y" in r.stderr
    assert _patches(calls) == []


def test_wontfix_and_nopr_untouched(tmp_path):
    cands = [_candidate("PVTI_1", 7, milestone=V41, pclass="wontfix"),
             _candidate("PVTI_2", 9, milestone=V41, pclass="nopr")]
    for mode in ("--dry-run", "--apply"):
        r, calls = _run(tmp_path, mode, "--release-tag", "v4.0.0", candidates=cands)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "milestone" not in r.stdout.lower(), r.stdout
        assert _patches(calls) == []
        assert _ms_lists(calls) == []


def test_forced_tag_used_for_milestone(tmp_path):
    # The release lookup would fail; --release-tag must skip it entirely.
    r, calls = _run(tmp_path, "--apply", "--release-tag", "v4.0.0", tag="v9.9.9", REL_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [c for c in calls if "/releases" in c]
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls


def test_no_release_comment_still_fixes_milestone(tmp_path):
    r, calls = _run(tmp_path, "--apply", "--no-release-comment")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c for c in calls if "/releases" in c], "the release lookup was skipped"
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls
    assert not [c for c in calls if c.startswith("issue comment")]


def test_no_release_comment_dry_run_shows_the_milestone(tmp_path):
    r, _ = _run(tmp_path, "--dry-run", "--no-release-comment")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would set milestone: v4.1 -> v4.0 (v4.0.0)" in r.stdout


def test_milestone_write_failure_is_reported_not_fatal(tmp_path):
    r, calls = _run(tmp_path, "--apply", PATCH_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c for c in calls if c.startswith("api graphql")], "the board move did not run"
    assert "Promotions: 1 ok, 0 failed" in r.stdout
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout
    assert "422" in r.stdout and '"code":"invalid"' in r.stdout
    assert "ACTION NEEDED" in r.stdout
    assert "--apply --no-release-comment" in r.stdout


def test_failed_status_move_writes_no_milestone(tmp_path):
    stub = _STUB.replace('''"api graphql"*) echo '{"data":{}}'; exit 0 ;;''',
                         '''"api graphql"*) echo "HTTP 500" >&2; exit 1 ;;''')
    assert stub != _STUB
    r, calls = _run(tmp_path, "--apply", stub=stub)
    assert r.returncode == 1
    assert [c for c in calls if c.startswith("api graphql")]
    assert _patches(calls) == []
    assert "1 set" not in r.stdout, "counted a milestone write that never happened"


def test_milestone_list_failure_warns_once_and_counts_failures(tmp_path):
    cands = [_candidate("PVTI_1", 7, milestone=V41), _candidate("PVTI_2", 8, milestone=V41)]
    r, calls = _run(tmp_path, "--apply", candidates=cands, MS_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stderr.count("could not list milestones") == 1, r.stderr
    assert "502" in r.stderr
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 2 failed" in r.stdout
    assert _patches(calls) == []


def test_milestone_list_failure_is_unavailable_in_dry_run(tmp_path):
    r, _ = _run(tmp_path, "--dry-run", MS_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "milestone: UNAVAILABLE" in r.stdout


def test_milestone_list_is_fetched_once_per_repo(tmp_path):
    cands = [_candidate("PVTI_1", 7, milestone=V41), _candidate("PVTI_2", 8, milestone=V41)]
    r, calls = _run(tmp_path, "--apply", candidates=cands)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_ms_lists(calls)) == 1
    assert "state=all" in _ms_lists(calls)[0] and "--paginate" in _ms_lists(calls)[0]
    assert len(_patches(calls)) == 2


def test_milestone_on_a_later_page_is_found(tmp_path):
    pages = [[{"title": f"m{i}", "number": 100 + i, "state": "open"} for i in range(100)],
             [{"title": "v4.0", "number": 15, "state": "closed"}]]
    r, calls = _run(tmp_path, "--apply", pages=pages)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls


def test_unavailable_release_counts_a_milestone_failure(tmp_path):
    r, calls = _run(tmp_path, "--apply", REL_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout
    assert _patches(calls) == []


def test_no_containing_release_skips_the_milestone(tmp_path):
    r, calls = _run(tmp_path, "--apply", COMPARE="behind")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _patches(calls) == [] and _ms_lists(calls) == []
    assert "Milestones: 0 set, 0 unchanged, 1 skipped, 0 failed" in r.stdout


def test_malformed_issue_number_gets_no_patch(tmp_path):
    r, calls = _run(tmp_path, "--apply", candidates=[_candidate(number="7/lock", milestone=V41)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert _patches(calls) == []
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout


# ---- inventory-board.sh and find-promotable.sh carry the milestone -----------------------

def test_inventory_and_find_promotable_carry_the_milestone(tmp_path):
    # The fake gh below answers whatever the query asks, so check the query itself:
    # both the Issue and the PullRequest fragment must fetch the milestone.
    text = (SCRIPTS / "inventory-board.sh").read_text()
    issue_frag = text.split("... on Issue {", 1)[1].split("... on PullRequest {", 1)[0]
    pr_frag = text.split("... on PullRequest {", 1)[1].split("... on DraftIssue", 1)[0]
    assert "milestone { number title state }" in issue_frag
    assert "milestone { number title state }" in pr_frag
    meta = {"data": {"node": {"id": "PVT_1", "title": "Board", "number": 1, "fields": {"nodes": [
        {"id": "F1", "name": "Status", "options": [{"id": "o_dev", "name": "Dev Complete"},
                                                    {"id": "o_done", "name": "Done"}]}]}}}}
    sv = {"nodes": [{"field": {"id": "F1", "name": "Status"}, "name": "Dev Complete",
                     "optionId": "o_dev"}]}
    pr = {"number": 8, "title": "pr", "url": "u", "merged": True, "mergedAt": "2026-10-01",
          "baseRefName": "develop", "state": "MERGED", "mergeCommit": {"oid": SHA},
          "repository": {"nameWithOwner": "o/r"}}
    items = {"data": {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [
            {"id": "PVTI_1", "fieldValues": sv, "content": {
                "__typename": "Issue", "number": 7, "title": "i", "state": "CLOSED",
                "stateReason": "COMPLETED", "url": "https://github.com/o/r/issues/7",
                "repository": {"nameWithOwner": "o/r"}, "milestone": V41,
                "closedByPullRequestsReferences": {"pageInfo": {"hasNextPage": False},
                                                   "nodes": [pr]}}},
            {"id": "PVTI_2", "fieldValues": sv, "content": dict(
                pr, __typename="PullRequest", number=9, milestone=None)},
        ]}}}}
    routes = [{"match": ["auth", "status"],
               "stdout": "  - Token scopes: 'project', 'read:project', 'repo'\n"},
              {"match": ["api", "graphql", "fields(first:50)"], "stdout": json.dumps(meta)},
              {"match": ["api", "graphql", "items(first:100"], "stdout": json.dumps(items)},
              {"match": ["compare"], "stdout": "ahead"}]
    env = dict(os.environ, **install_fake_gh(tmp_path / "bin", routes, tmp_path / "gh.log"))
    inv = subprocess.run(["bash", str(SCRIPTS / "inventory-board.sh"), "--board-id", "PVT_1"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert inv.returncode == 0, inv.stderr
    issue = json.loads(inv.stdout)["items"][0]["issue"]
    assert issue["milestone"] == V41
    assert json.loads(inv.stdout)["items"][1]["pullRequest"]["milestone"] is None
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(inv.stdout)
    found = subprocess.run(["bash", str(SCRIPTS / "find-promotable.sh"), str(inv_file)],
                           capture_output=True, text=True, env=env, timeout=60)
    assert found.returncode == 0, found.stderr
    by_num = {c["number"]: c for c in json.loads(found.stdout)["candidates"]}
    assert by_num[7]["milestone"] == V41
    assert "milestone" in by_num[9] and by_num[9]["milestone"] is None
    assert not [c for c in gh_calls(tmp_path / "gh.log") if "PATCH" in c]


def test_empty_milestone_listing_is_a_failure_not_an_empty_list(tmp_path):
    # gh prints [] for a repo with no milestones. No output at all is not that answer.
    stub = _STUB.replace('''jq -c '.[]' "$MS_PAGES"; exit 0 ;;''', '''exit 0 ;;''')
    assert stub != _STUB
    r, calls = _run(tmp_path, "--apply", stub=stub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "could not list milestones" in r.stderr
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout


# ---- PR #205 review round 1 ---------------------------------------------------------------

def test_forced_tag_with_no_comment_skips_the_lookup_and_sets_the_milestone(tmp_path):
    r, calls = _run(tmp_path, "--apply", "--release-tag", "v4.0.0", "--no-release-comment",
                    tag="v9.9.9", REL_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [c for c in calls if "/releases" in c]
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls
    assert not [c for c in calls if c.startswith("issue comment")]


def test_two_part_tag_maps_to_the_exact_title(tmp_path):
    ms = [{"title": "v4", "number": 4, "state": "closed"},
          {"title": "v4.0", "number": 15, "state": "closed"}]
    r, calls = _run(tmp_path, "--apply", milestones=ms, tag="v4.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api -X PATCH repos/o/r/issues/7 -F milestone=15 --jq .milestone.number" in calls


@pytest.mark.parametrize("repo", ["../..", "o/..", "./r"])
def test_dot_segments_in_repo_get_no_patch(tmp_path, repo):
    cand = _candidate(milestone=V41, repo=repo)
    cand["mergedPRs"][0]["repo"] = repo
    r, calls = _run(tmp_path, "--apply", "--release-tag", "v4.0.0", candidates=[cand])
    assert r.returncode == 0, r.stdout + r.stderr
    assert _patches(calls) == [] and _ms_lists(calls) == []
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout


def test_patch_reply_with_another_milestone_is_a_failure(tmp_path):
    r, _ = _run(tmp_path, "--apply", PATCH_WRONG="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "99" in r.stdout
    assert "Milestones: 0 set, 0 unchanged, 0 skipped, 1 failed" in r.stdout


@pytest.mark.parametrize("why,kw,reason", [
    pytest.param("no-match", dict(tag="v9.0.0"), "no milestone titled 9.0.0 or 9.0", id="no-match"),
    pytest.param("two", dict(milestones=[{"title": "v4.0", "number": 15, "state": "closed"},
                                         {"title": "4.0", "number": 16, "state": "open"}]),
                 "ambiguous", id="two-matches"),
    pytest.param("shape", dict(tag="nightly-1"), "is not vX.Y.Z or vX.Y", id="not-a-version"),
])
def test_dry_run_prints_why_the_milestone_is_skipped(tmp_path, why, kw, reason):
    r, _ = _run(tmp_path, "--dry-run", **kw)
    assert r.returncode == 0, r.stdout + r.stderr
    line = [ln for ln in r.stdout.splitlines() if "milestone: skipped" in ln]
    assert line and reason in line[0], r.stdout
    assert "Milestones: 0 to set, 0 unchanged, 1 skipped, 0 cannot check" in r.stdout
