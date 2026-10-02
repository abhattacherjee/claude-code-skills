"""promote-shipped must never credit an issue with a pull request from another repository.

A CrossReferencedEvent can come from any repo. A foreign PR whose body says `fixes #42` closes
issue 42 of ITS OWN repo, not ours, yet the old timeline filter accepted it, checked its merge
commit against the foreign repo's main, and promoted our issue with a "Released in" comment.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts"
FIND = SCRIPTS / "find-promotable.sh"
APPLY = SCRIPTS / "apply-promotions.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def _inventory():
    return {
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "PVTSSF_1", "name": "Status",
                        "options": [{"id": "opt_dev", "name": "Dev Complete"},
                                    {"id": "opt_done", "name": "Done"}],
                        "doneOptionId": "opt_done", "doneOptionName": "Done"},
        "items": [{
            "itemId": "PVTI_1", "status": "Dev Complete", "statusOptionId": "opt_dev",
            "contentType": "Issue",
            "issue": {"number": 42, "title": "an issue", "state": "CLOSED",
                      "stateReason": "COMPLETED", "url": "https://github.com/o/r/issues/42",
                      "repo": "o/r", "linkedPRs": []},
            "pullRequest": None, "draftTitle": None,
        }],
    }


def _pr(repo, body, number=7, sha="f00d"):
    return {"__typename": "PullRequest", "number": number, "merged": True,
            "baseRefName": "main", "mergedAt": "2026-01-01T00:00:00Z", "body": body,
            "mergeCommit": {"oid": sha}, "repository": {"nameWithOwner": repo}}


def _timeline(*prs):
    nodes = [{"__typename": "CrossReferencedEvent", "source": p} for p in prs]
    return {"data": {"repository": {"issue": {"timelineItems": {"nodes": nodes}}}}}


# The stub applies --jq the way gh does, so the script's own filter is what is tested.
_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
jqf=""; prev=""
for a in "$@"; do [ "$prev" = "--jq" ] && jqf="$a"; prev="$a"; done
case "$1 $2" in
  "api graphql") jq -c "$jqf" "$TIMELINE"; exit $? ;;
esac
case "$2" in
  */compare/*) echo ahead; exit 0 ;;
esac
exit 1
'''


def _find(tmp_path, timeline):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_STUB)
    (bindir / "gh").chmod(0o755)
    (tmp_path / "timeline.json").write_text(json.dumps(timeline))
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps(_inventory()))
    log = tmp_path / "gh.log"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log),
               TIMELINE=str(tmp_path / "timeline.json"))
    done = subprocess.run(["bash", str(FIND), str(inv)], capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    return json.loads(done.stdout), calls


def test_a_foreign_repo_pr_saying_fixes_n_is_not_promotable(tmp_path):
    out, calls = _find(tmp_path, _timeline(_pr("evil/fork", "see o/r#42\n\nfixes #42")))
    assert out["candidates"] == [], "a PR from another repo promoted our issue"
    assert [c["promoteClass"] for c in out["held"]] == ["hold-foreign-pr"]
    assert not [c for c in calls if "evil/fork" in c], "reachability was checked in the foreign repo"


def test_a_same_repo_pr_saying_fixes_n_is_still_promoted(tmp_path):
    """Negative control: the same fixture with the PR in the issue's repo promotes."""
    out, calls = _find(tmp_path, _timeline(_pr("o/r", "fixes #42")))
    assert [c["promoteClass"] for c in out["candidates"]] == ["merged"]
    assert [c for c in calls if "/repos/o/r/compare/f00d...main" in c]


def test_a_fully_qualified_reference_to_the_issue_repo_counts(tmp_path):
    out, _ = _find(tmp_path, _timeline(_pr("o/r", "Fixes o/r#42")))
    assert [c["promoteClass"] for c in out["candidates"]] == ["merged"]


def test_a_fully_qualified_reference_from_another_repo_is_still_refused(tmp_path):
    out, _ = _find(tmp_path, _timeline(_pr("evil/fork", "Fixes o/r#42")))
    assert out["candidates"] == []


def test_a_same_repo_pr_wins_over_a_foreign_one(tmp_path):
    out, calls = _find(tmp_path, _timeline(_pr("evil/fork", "fixes #42", number=9, sha="bad"),
                                           _pr("o/r", "fixes #42")))
    assert [c["promoteClass"] for c in out["candidates"]] == ["merged"]
    assert [p["repo"] for p in out["candidates"][0]["mergedPRs"]] == ["o/r"]
    assert not [c for c in calls if "evil/fork" in c or "bad...main" in c]


# ---- apply-promotions.sh: defence in depth on a hand-edited or old candidates file -------

_APPLY_STUB = r'''#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
if [ "$1 $2" = "auth status" ]; then echo "  - Token scopes: 'project', 'read:project', 'repo'"; exit 0; fi
case "$1 $2" in
  "api graphql") echo '{"data":{}}'; exit 0 ;;
  "issue comment") exit 0 ;;
  "issue view") echo 0; exit 0 ;;
esac
case "$2" in
  */releases) echo '[{"tag_name":"v1","html_url":"u","published_at":"2026-01-02T00:00:00Z","draft":false}]'; exit 0 ;;
  */compare/*) echo ahead; exit 0 ;;
esac
exit 1
'''


def _apply(tmp_path, pr_repo, *mode):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_APPLY_STUB)
    (bindir / "gh").chmod(0o755)
    cand = {
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "F1", "doneOptionId": "opt_done", "doneOptionName": "Done"},
        "candidates": [{
            "itemId": "PVTI_1", "status": "Dev Complete", "contentType": "Issue", "number": 42,
            "title": "an issue", "url": "https://github.com/o/r/issues/42", "repo": "o/r",
            "promoteClass": "merged",
            "mergedPRs": [{"number": 7, "repo": pr_repo, "mergeCommitOid": "f00d", "inMain": "yes"}],
        }],
        "held": [],
    }
    path = tmp_path / "cand.json"
    path.write_text(json.dumps(cand))
    log = tmp_path / "gh.log"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(log))
    done = subprocess.run(["bash", str(APPLY), str(path), *mode], capture_output=True,
                          text=True, env=env, timeout=60)
    return done, (log.read_text().splitlines() if log.exists() else [])


def test_apply_refuses_a_merged_candidate_whose_pr_is_from_another_repo(tmp_path):
    done, calls = _apply(tmp_path, "evil/fork", "--apply")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "another repository" in done.stdout
    assert not [c for c in calls if c.startswith("issue comment")], "commented anyway"
    assert not [c for c in calls if "updateProjectV2ItemFieldValue" in c], "moved the card anyway"
    assert not [c for c in calls if "evil/fork" in c]


def test_apply_still_promotes_a_same_repo_pr(tmp_path):
    done, calls = _apply(tmp_path, "o/r", "--apply")
    assert done.returncode == 0, done.stdout + done.stderr
    assert [c for c in calls if c.startswith("issue comment")]
