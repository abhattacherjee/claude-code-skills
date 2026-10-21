"""promote-shipped: unmerged timeline PRs hold the issue, `Closes: #N` counts, big boards load.

find-promotable.sh: an unmerged PR found on the issue timeline is a linked PR, so the issue is
held (hold-unmerged-pr) instead of promoting as "no PR". GitHub accepts `Closes: #42`.
inventory-board.sh: the item array must not travel through argv (E2BIG on a large board).
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_cross_repo_prs import _find, _pr, _timeline

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "promote-shipped" / "scripts"
INVENTORY = SCRIPTS / "inventory-board.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def _unmerged(repo, body):
    pr = _pr(repo, body)
    pr["merged"] = False
    pr["mergeCommit"] = None
    return pr


def test_an_unmerged_same_repo_pr_on_the_timeline_holds_the_issue(tmp_path):
    out, _ = _find(tmp_path, _timeline(_unmerged("o/r", "fixes #42")))
    assert out["candidates"] == []
    assert [c["promoteClass"] for c in out["held"]] == ["hold-unmerged-pr"]


def test_a_timeline_with_no_pr_at_all_still_promotes_as_nopr(tmp_path):
    """Negative control for the test above: same fixture without the unmerged PR."""
    out, _ = _find(tmp_path, _timeline())
    assert [c["promoteClass"] for c in out["candidates"]] == ["nopr"]


@pytest.mark.parametrize("body", ["Closes: #42", "fixes:#42", "Resolves:   #42", "Closes #42"])
def test_closing_keyword_with_an_optional_colon_counts(tmp_path, body):
    out, _ = _find(tmp_path, _timeline(_pr("o/r", body)))
    assert [c["promoteClass"] for c in out["candidates"]] == ["merged"], body


def test_a_keyword_glued_to_the_number_still_does_not_count(tmp_path):
    out, _ = _find(tmp_path, _timeline(_pr("o/r", "closes#42")))
    assert [c["promoteClass"] for c in out["candidates"]] == ["nopr"]


_GH = r'''#!/usr/bin/env bash
case "$1 $2" in
  "auth status") echo "  - Token scopes: 'project', 'read:project', 'repo'"; exit 0 ;;
  "api graphql")
    case "$*" in
      *"fields(first:50)"*) cat "$META_FILE"; exit 0 ;;
      *) cat "$ITEMS_FILE"; exit 0 ;;
    esac ;;
esac
exit 1
'''


def test_a_large_board_does_not_overflow_argv(tmp_path):
    meta = {"data": {"node": {"id": "PVT_1", "title": "Board", "number": 1, "fields": {"nodes": [
        {"id": "F1", "name": "Status",
         "options": [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "Done"}]}]}}}}
    pad = "x" * 1000
    nodes = [{"id": f"I{i}", "fieldValues": {"nodes": []},
              "content": {"__typename": "Issue", "number": i, "title": pad, "state": "OPEN",
                          "stateReason": None, "url": f"https://github.com/o/r/issues/{i}",
                          "repository": {"nameWithOwner": "o/r"},
                          "closedByPullRequestsReferences": {"pageInfo": {"hasNextPage": False},
                                                             "nodes": []}}}
             for i in range(1, 2001)]
    items = {"data": {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                         "nodes": nodes}}}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    (tmp_path / "items.json").write_text(json.dumps(items))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH)
    (bindir / "gh").chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               META_FILE=str(tmp_path / "meta.json"), ITEMS_FILE=str(tmp_path / "items.json"),
               XDG_CACHE_HOME=str(tmp_path / "cache"))
    done = subprocess.run(["bash", str(INVENTORY), "--board-id", "PVT_1"], capture_output=True,
                          text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-500:]
    assert len(json.loads(done.stdout)["items"]) == 2000
